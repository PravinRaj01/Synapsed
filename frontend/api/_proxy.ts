// Forward a request to the Neon Auth service. The browser talks to /neon-auth on our own origin so the session cookie
// is first-party (Safari blocks third-party cookies). A plain Vercel rewrite cannot do this job: it forwards our
// hostname, and Neon rejects any request whose Host header is not its own (INVALID_HOSTNAME). Calling it from a
// function lets fetch send the right Host.

export const DEFAULT_UPSTREAM = 'https://ep-flat-glade-ao11yi0v.neonauth.c-2.ap-southeast-1.aws.neon.tech/neondb/auth'

// Headers that describe one connection, not the message, or that fetch must set itself.
const DROP_REQUEST = new Set(['host', 'connection', 'content-length', 'accept-encoding', 'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto', 'x-real-ip', 'x-vercel-id', 'x-vercel-forwarded-for', 'x-vercel-deployment-url', 'x-vercel-ip-city', 'x-vercel-ip-country', 'x-vercel-ip-country-region', 'x-vercel-ip-latitude', 'x-vercel-ip-longitude', 'x-vercel-ip-timezone', 'x-vercel-proxied-for', 'x-vercel-sc-headers', 'forwarded'])
const DROP_RESPONSE = new Set(['content-encoding', 'content-length', 'transfer-encoding', 'connection', 'keep-alive'])

/** The upstream URL for a path from the browser, or null if the path could escape the auth service's own routes. */
export function upstreamUrl(path: string, search: URLSearchParams, upstream = DEFAULT_UPSTREAM): URL | null {
  const clean = path.replace(/^\/+/, '')
  if (clean.split('/').some((segment) => segment === '..' || segment === '.' || segment.includes('\\')) || /^[a-z][a-z0-9+.-]*:/i.test(clean)) return null
  const base = upstream.replace(/\/$/, '')
  const url = new URL(`${base}/${clean}`)
  if (!url.href.startsWith(`${base}/`) && url.href !== base) return null // never leave the auth service
  for (const [key, value] of search) url.searchParams.append(key, value)
  return url
}

export async function forward(request: Request, path: string, upstream = DEFAULT_UPSTREAM, fetchImpl: typeof fetch = fetch): Promise<Response> {
  const incoming = new URL(request.url)
  incoming.searchParams.delete('path') // the rewrite adds this; it is not part of the original query
  const target = upstreamUrl(path, incoming.searchParams, upstream)
  if (!target) return Response.json({ error: 'Not found' }, { status: 404 })

  const headers = new Headers()
  request.headers.forEach((value, key) => {
    if (!DROP_REQUEST.has(key.toLowerCase())) headers.set(key, value)
  })
  const hasBody = request.method !== 'GET' && request.method !== 'HEAD'
  let upstreamResponse: Response
  try {
    upstreamResponse = await fetchImpl(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: 'manual', // pass redirects (for example to Google) on to the browser untouched
    })
  } catch {
    return Response.json({ error: 'The sign-in service is unreachable. Try again shortly.' }, { status: 502 })
  }

  const out = new Headers()
  upstreamResponse.headers.forEach((value, key) => {
    const lower = key.toLowerCase()
    if (!DROP_RESPONSE.has(lower) && lower !== 'set-cookie') out.append(key, value)
  })
  for (const cookie of upstreamResponse.headers.getSetCookie()) out.append('set-cookie', cookie) // several cookies must stay separate
  return new Response(upstreamResponse.status === 204 || upstreamResponse.status === 304 ? null : upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: out,
  })
}
