/** A failed API call, with a message that is safe to show the user. */
export class ApiError extends Error {
  readonly status: number
  /** Seconds to wait before retrying, from a 429's Retry-After header. */
  readonly retryAfter: number | null

  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.retryAfter = retryAfter
  }
}

/** The text the API put in its `detail` field: a string, or a list of validation problems. */
export function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string; loc?: unknown[] }
    const field = Array.isArray(first.loc) ? first.loc.filter((p) => p !== 'body' && p !== 'query').join('.') : ''
    return first.msg ? (field ? `${field}: ${first.msg}` : first.msg) : fallback
  }
  return fallback
}

export function retryAfterSeconds(header: string | null): number | null {
  if (!header) return null
  const n = Number(header)
  return Number.isFinite(n) && n > 0 ? Math.ceil(n) : null
}

const FALLBACK: Record<number, string> = {
  401: 'Please sign in again.',
  403: 'You do not have access to that.',
  404: 'That was not found, or you do not have access to it.',
  413: 'That file is too large.',
  429: 'Too many requests. Please wait a moment.',
  502: 'A service we depend on is unavailable. Try again shortly.',
  503: 'This feature is not available right now.',
}

export function messageFor(status: number, body: unknown, retryAfter: number | null): string {
  const base = detailMessage(body, FALLBACK[status] ?? 'Something went wrong. Please try again.')
  return status === 429 && retryAfter && !/\d+\s*second/i.test(base) ? `${base} Try again in ${retryAfter} seconds.` : base
}
