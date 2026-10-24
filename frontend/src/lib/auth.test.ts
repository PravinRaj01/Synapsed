import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The SDK client is only used for sign-in and the session here. Tokens come from the HTTP endpoint, whose real
// answer (checked against the live service) is {"token": "<jwt>"} with status 200, or an error status when signed out.
vi.mock('@neondatabase/neon-js/auth', () => ({ createAuthClient: () => ({}) }))

function jwt(expSeconds: number) {
  const payload = btoa(JSON.stringify({ exp: expSeconds })).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `header.${payload}.sig`
}

const tokenResponse = (token: string) => new Response(JSON.stringify({ token }), { status: 200, headers: { 'content-type': 'application/json' } })

const fetchMock = vi.fn()

async function load() {
  vi.resetModules()
  return import('./auth')
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('tokenExpiry', () => {
  it('reads exp from the payload in milliseconds', async () => {
    const { tokenExpiry } = await load()
    expect(tokenExpiry(jwt(1_800_000_000))).toBe(1_800_000_000_000)
  })

  it.each(['', 'nope', 'a.b.c', 'a..c'])('is null for %j', async (bad) => {
    const { tokenExpiry } = await load()
    expect(tokenExpiry(bad)).toBeNull()
  })
})

describe('getAccessToken', () => {
  const now = () => 1_000_000_000_000
  const fresh = () => jwt(now() / 1000 + 600)

  it('asks the same-origin token endpoint with the session cookie, and returns the token', async () => {
    const { getAccessToken } = await load()
    fetchMock.mockResolvedValue(tokenResponse(fresh()))
    expect(await getAccessToken(now)).toBe(fresh())
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`${window.location.origin}/neon-auth/token`)
    expect(init).toMatchObject({ credentials: 'same-origin' })
  })

  it('fetches once and reuses the token while it has more than a minute left', async () => {
    const { getAccessToken } = await load()
    fetchMock.mockResolvedValue(tokenResponse(fresh()))
    await getAccessToken(now)
    await getAccessToken(now)
    await getAccessToken(now)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('renews a token that is about to expire', async () => {
    const { getAccessToken } = await load()
    fetchMock.mockResolvedValueOnce(tokenResponse(jwt(now() / 1000 + 30))).mockResolvedValueOnce(tokenResponse(jwt(now() / 1000 + 900)))
    await getAccessToken(now)
    expect(await getAccessToken(now)).toBe(jwt(now() / 1000 + 900))
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('shares one request between callers that ask at the same moment', async () => {
    const { getAccessToken } = await load()
    fetchMock.mockResolvedValue(tokenResponse(fresh()))
    const results = await Promise.all([getAccessToken(now), getAccessToken(now), getAccessToken(now)])
    expect(new Set(results).size).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['signed out (401)', () => new Response('{}', { status: 401 })],
    ['a body without a token', () => new Response('{}', { status: 200 })],
    ['a body that is not JSON', () => new Response('<html>', { status: 200 })],
    ['a non-string token', () => new Response(JSON.stringify({ token: { session: {} } }), { status: 200 })],
    ['an empty token', () => new Response(JSON.stringify({ token: '' }), { status: 200 })],
  ])('returns null for %s, and asks again next time', async (_label, make) => {
    const { getAccessToken } = await load()
    fetchMock.mockImplementation(async () => make())
    expect(await getAccessToken(now)).toBeNull()
    expect(await getAccessToken(now)).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('returns null when the network fails, and recovers on the next call', async () => {
    const { getAccessToken } = await load()
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce(tokenResponse(fresh()))
    expect(await getAccessToken(now)).toBeNull()
    expect(await getAccessToken(now)).toBe(fresh())
  })

  it('forgets the token after sign-out', async () => {
    const { getAccessToken, clearAccessToken } = await load()
    fetchMock.mockResolvedValue(tokenResponse(fresh()))
    await getAccessToken(now)
    clearAccessToken()
    await getAccessToken(now)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
