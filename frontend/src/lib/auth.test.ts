import { beforeEach, describe, expect, it, vi } from 'vitest'

const token = vi.fn()
vi.mock('@neondatabase/neon-js/auth', () => ({ createAuthClient: () => ({ token }) }))

function jwt(expSeconds: number) {
  const payload = btoa(JSON.stringify({ exp: expSeconds })).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
  return `header.${payload}.sig`
}

async function load() {
  vi.resetModules()
  return import('./auth')
}

beforeEach(() => token.mockReset())

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

  it('fetches once and reuses the token while it has more than a minute left', async () => {
    const { getAccessToken } = await load()
    token.mockResolvedValue({ data: { token: jwt(now() / 1000 + 600) } })
    expect(await getAccessToken(now)).toBe(jwt(now() / 1000 + 600))
    await getAccessToken(now)
    await getAccessToken(now)
    expect(token).toHaveBeenCalledTimes(1)
  })

  it('renews a token that is about to expire', async () => {
    const { getAccessToken } = await load()
    token.mockResolvedValueOnce({ data: { token: jwt(now() / 1000 + 30) } }).mockResolvedValueOnce({ data: { token: jwt(now() / 1000 + 900) } })
    await getAccessToken(now)
    expect(await getAccessToken(now)).toBe(jwt(now() / 1000 + 900))
    expect(token).toHaveBeenCalledTimes(2)
  })

  it('shares one request between callers that ask at the same moment', async () => {
    const { getAccessToken } = await load()
    token.mockResolvedValue({ data: { token: jwt(now() / 1000 + 600) } })
    const [a, b, c] = await Promise.all([getAccessToken(now), getAccessToken(now), getAccessToken(now)])
    expect(a).toBe(b)
    expect(b).toBe(c)
    expect(token).toHaveBeenCalledTimes(1)
  })

  it('returns null when nobody is signed in, and asks again next time', async () => {
    const { getAccessToken } = await load()
    token.mockResolvedValue({ data: null })
    expect(await getAccessToken(now)).toBeNull()
    expect(await getAccessToken(now)).toBeNull()
    expect(token).toHaveBeenCalledTimes(2)
  })

  it('forgets the token after sign-out', async () => {
    const { getAccessToken, clearAccessToken } = await load()
    token.mockResolvedValue({ data: { token: jwt(now() / 1000 + 600) } })
    await getAccessToken(now)
    clearAccessToken()
    await getAccessToken(now)
    expect(token).toHaveBeenCalledTimes(2)
  })
})
