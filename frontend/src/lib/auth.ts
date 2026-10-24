import { createAuthClient } from '@neondatabase/neon-js/auth'

// The auth service is reached through this app's own origin (a proxy in dev, a rewrite in production), so its
// session cookie is first-party. Safari blocks third-party cookies, which would otherwise break sign-in there.
const AUTH_PATH = import.meta.env.VITE_NEON_AUTH_PATH ?? '/neon-auth'

export const authClient = createAuthClient(`${window.location.origin}${AUTH_PATH}`)

type Cached = { token: string; expiresAt: number }
let cached: Cached | null = null
let inflight: Promise<string | null> | null = null

const REFRESH_MARGIN_MS = 60_000 // tokens last 15 minutes; renew a minute early

/** The expiry (ms since epoch) in a JWT's payload, or null when it cannot be read. */
export function tokenExpiry(token: string): number | null {
  try {
    const payload = token.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    const exp = JSON.parse(json).exp
    return typeof exp === 'number' ? exp * 1000 : null
  } catch {
    return null
  }
}

/** A JWT for the signed-in user to send to the API, or null when nobody is signed in. Cached until it nears expiry. */
export function getAccessToken(now: () => number = Date.now): Promise<string | null> {
  if (cached && cached.expiresAt - now() > REFRESH_MARGIN_MS) return Promise.resolve(cached.token)
  inflight ??= (async () => {
    try {
      const { data } = await authClient.token()
      const token = data?.token ?? null
      cached = token ? { token, expiresAt: tokenExpiry(token) ?? now() + 5 * 60_000 } : null
      return token
    } finally {
      inflight = null
    }
  })()
  return inflight
}

export function clearAccessToken() {
  cached = null
}
