import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ getAccessToken: vi.fn(), clearAccessToken: vi.fn() }))
vi.mock('./auth', () => auth)

import { ApiError } from './errors'
import { createApi, resetUnauthorizedThrottle, setUnauthorizedHandler, unwrap, unwrapEmpty, warmUpApi } from './api'

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } })

const fetchMock = vi.fn()
const unauthorized = vi.fn()

function sentAuth(call: number) {
  return (fetchMock.mock.calls[call][0] as Request).headers.get('Authorization')
}

beforeEach(() => {
  fetchMock.mockReset()
  unauthorized.mockReset()
  auth.getAccessToken.mockReset()
  auth.clearAccessToken.mockReset()
  setUnauthorizedHandler(unauthorized)
  resetUnauthorizedThrottle()
})

describe('the Authorization header', () => {
  it('carries the current token', async () => {
    auth.getAccessToken.mockResolvedValue('tok-1')
    fetchMock.mockImplementation(async () => json([]))
    await createApi(fetchMock).GET('/api/v1/campaigns', {})
    expect(sentAuth(0)).toBe('Bearer tok-1')
  })

  it('is left off when nobody is signed in (the API then answers 401)', async () => {
    auth.getAccessToken.mockResolvedValue(null)
    fetchMock.mockImplementation(async () => json({ detail: 'x' }, 401))
    await createApi(fetchMock).GET('/api/v1/campaigns', {})
    expect(sentAuth(0)).toBeNull()
  })
})

describe('a 401', () => {
  it('on a GET fetches a fresh token and retries once, quietly succeeding if that works', async () => {
    auth.getAccessToken.mockResolvedValueOnce('old').mockResolvedValueOnce('new')
    fetchMock.mockResolvedValueOnce(json({ detail: 'expired' }, 401)).mockResolvedValueOnce(json([{ id: 'c1' }]))
    const { data, response } = await createApi(fetchMock).GET('/api/v1/campaigns', {})
    expect(response.status).toBe(200)
    expect(data).toEqual([{ id: 'c1' }])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sentAuth(0)).toBe('Bearer old')
    expect(sentAuth(1)).toBe('Bearer new')
    expect(auth.clearAccessToken).toHaveBeenCalled()
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('that persists after the retry raises the alarm once, and does not retry forever', async () => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockImplementation(async () => json({ detail: 'nope' }, 401))
    const { response } = await createApi(fetchMock).GET('/api/v1/campaigns', {})
    expect(response.status).toBe(401)
    expect(fetchMock).toHaveBeenCalledTimes(2) // the original and one retry, never a loop
    expect(unauthorized).toHaveBeenCalledTimes(1)
  })

  it('a burst of failures from several requests raises only one alarm', async () => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockImplementation(async () => json({ detail: 'nope' }, 401))
    const api = createApi(fetchMock)
    await Promise.all([api.GET('/api/v1/campaigns', {}), api.GET('/api/v1/workspaces', {}), api.GET('/api/v1/pipeline', {})])
    expect(unauthorized).toHaveBeenCalledTimes(1)
  })

  it('is not retried for a POST (its body is already sent), but still raises the alarm', async () => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockImplementation(async () => json({ detail: 'nope' }, 401))
    await createApi(fetchMock).POST('/api/v1/workspaces', { body: { name: 'a', company: 'b', industry: 'c' } })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(unauthorized).toHaveBeenCalledTimes(1)
  })

  it('with no token available skips the retry and raises the alarm', async () => {
    auth.getAccessToken.mockResolvedValue(null)
    fetchMock.mockImplementation(async () => json({ detail: 'nope' }, 401))
    await createApi(fetchMock).GET('/api/v1/campaigns', {})
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(unauthorized).toHaveBeenCalledTimes(1)
  })

  it.each([403, 404, 422, 429, 500, 502])('%i does not raise the alarm', async (status) => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockImplementation(async () => json({ detail: 'x' }, status))
    await createApi(fetchMock).GET('/api/v1/campaigns', {})
    expect(unauthorized).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('unwrap', () => {
  it('returns the data of a successful call', async () => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockImplementation(async () => json([{ id: 'c1' }]))
    expect(await unwrap(createApi(fetchMock).GET('/api/v1/campaigns', {}))).toEqual([{ id: 'c1' }])
  })

  it('throws an ApiError carrying the server message, status and wait for a 429', async () => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockImplementation(async () => json({ detail: 'Too many requests. Try again in 40 seconds.' }, 429, { 'retry-after': '40' }))
    const error: unknown = await unwrap(createApi(fetchMock).GET('/api/v1/campaigns', {})).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 429, retryAfter: 40, message: 'Too many requests. Try again in 40 seconds.' })
  })

  it('names the field in a validation error', async () => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockImplementation(async () => json({ detail: [{ loc: ['body', 'weight'], msg: 'Input should be greater than 0' }] }, 422))
    const error = await unwrap(createApi(fetchMock).GET('/api/v1/campaigns', {})).catch((e) => e)
    expect((error as Error).message).toBe('weight: Input should be greater than 0')
  })

  it('unwrapEmpty accepts a 204 and rejects a failure', async () => {
    auth.getAccessToken.mockResolvedValue('tok')
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(unwrapEmpty(createApi(fetchMock).DELETE('/api/v1/campaigns/{campaign_id}', { params: { path: { campaign_id: 'c' } } }))).resolves.toBeUndefined()
    fetchMock.mockResolvedValueOnce(json({ detail: 'Only an owner or PM can delete a campaign' }, 403))
    await expect(unwrapEmpty(createApi(fetchMock).DELETE('/api/v1/campaigns/{campaign_id}', { params: { path: { campaign_id: 'c' } } }))).rejects.toMatchObject({ status: 403 })
  })
})

describe('warmUpApi', () => {
  it('pings the health endpoint without credentials, so the sleeping API starts waking', () => {
    const ping = vi.fn().mockResolvedValue(new Response(null))
    warmUpApi(ping as unknown as typeof fetch)
    expect(ping).toHaveBeenCalledTimes(1)
    const [url, init] = ping.mock.calls[0]
    expect(url).toMatch(/\/health$/)
    expect(init).toMatchObject({ mode: 'no-cors', cache: 'no-store' })
    expect(init.headers).toBeUndefined()
  })

  it('never throws, even if the network is down', async () => {
    const ping = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    expect(() => warmUpApi(ping as unknown as typeof fetch)).not.toThrow()
    await Promise.resolve()
  })
})
