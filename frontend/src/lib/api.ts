import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from '@/api/schema'
import { clearAccessToken, getAccessToken } from './auth'
import { ApiError, messageFor, retryAfterSeconds } from './errors'

export const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

/** Called when the API says the session is no longer valid (the app sends the user to sign in). */
let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

const auth: Middleware = {
  async onRequest({ request }) {
    const token = await getAccessToken()
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  async onResponse({ response }) {
    if (response.status === 401) {
      clearAccessToken()
      onUnauthorized()
    }
    return response
  },
}

export const api = createClient<paths>({ baseUrl: API_URL })
api.use(auth)

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
