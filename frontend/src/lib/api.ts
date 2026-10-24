import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from '@/api/schema'
import { clearAccessToken, getAccessToken } from './auth'
import { ApiError, messageFor, retryAfterSeconds } from './errors'

export const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

/**
 * Called when the API still refuses us after a fresh token, meaning the session may be over. The handler must
 * check the session itself before signing anyone out: a refused request alone is not proof (the API might be wrong
 * or misconfigured), and acting on it blindly can bounce a signed-in user between pages.
 */
let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

const RETRY_MARKER = 'x-synapsed-retried'
const QUIET_MS = 2000 // a burst of 401s (several queries at once) raises one alarm, not one per request
let lastAlarm = 0

function bearer(request: Request, token: string): Request {
  const headers = new Headers(request.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return new Request(request, { headers })
}

export function createAuthMiddleware(fetchImpl: typeof fetch = (...args) => fetch(...args)): Middleware {
  return {
    async onRequest({ request }) {
      const token = await getAccessToken()
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
    async onResponse({ request, response }) {
      if (response.status !== 401) return response

      // Our token may simply have expired. For a GET (safe to repeat) get a fresh one and try once more.
      if (request.method === 'GET' && !request.headers.has(RETRY_MARKER)) {
        clearAccessToken()
        const token = await getAccessToken()
        if (token) {
          const retry = bearer(request, token)
          retry.headers.set(RETRY_MARKER, '1')
          const second = await fetchImpl(retry)
          if (second.status !== 401) return second
          response = second
        }
      }
      clearAccessToken()
      if (Date.now() - lastAlarm > QUIET_MS) {
        lastAlarm = Date.now()
        onUnauthorized()
      }
      return response
    },
  }
}

/**
 * Wake the API. It scales to zero when idle and its first request takes several seconds, so the sign-in page calls
 * this while the user types. Fire and forget: a failure here changes nothing (no-cors, so no preflight and no body read).
 */
export function warmUpApi(fetchImpl: typeof fetch = (...args) => fetch(...args)) {
  fetchImpl(`${API_URL}/health`, { mode: 'no-cors', cache: 'no-store' }).catch(() => {})
}

/** Reset the alarm throttle (tests). */
export function resetUnauthorizedThrottle() {
  lastAlarm = 0
}

export function createApi(fetchImpl?: typeof fetch) {
  const client = createClient<paths>({ baseUrl: API_URL, ...(fetchImpl ? { fetch: fetchImpl } : {}) })
  client.use(createAuthMiddleware(fetchImpl))
  return client
}

export const api = createApi()

type Result<T> = { data?: T; error?: unknown; response: Response }

function failure(response: Response, error: unknown): ApiError {
  const retryAfter = retryAfterSeconds(response.headers.get('retry-after'))
  return new ApiError(response.status, messageFor(response.status, error, retryAfter), retryAfter)
}

/** Return the data of an openapi-fetch call, or throw an ApiError with a readable message. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call
  if (response.ok && error === undefined) return data as T
  throw failure(response, error)
}

/** Like unwrap for calls that return no body (204). */
export async function unwrapEmpty(call: Promise<Result<unknown>>): Promise<void> {
  const { error, response } = await call
  if (!response.ok) throw failure(response, error)
}
