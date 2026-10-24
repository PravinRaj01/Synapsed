import { DEFAULT_UPSTREAM, forward } from './_proxy.js'

// vercel.json rewrites /neon-auth/<anything> to /api/neon-auth?path=<anything>.
async function handler(request: Request): Promise<Response> {
  const path = new URL(request.url).searchParams.get('path') ?? ''
  return forward(request, path, process.env.NEON_AUTH_UPSTREAM || DEFAULT_UPSTREAM)
}

export const GET = handler
export const POST = handler
export const PUT = handler
export const PATCH = handler
export const DELETE = handler
export const OPTIONS = handler
export const HEAD = handler
