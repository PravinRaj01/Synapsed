import { describe, expect, it, vi } from 'vitest'
import { forward, upstreamUrl } from './_proxy.js'

const UP = 'https://auth.example.neon.tech/neondb/auth'

describe('upstreamUrl', () => {
  it('joins the path to the auth service and keeps the original query', () => {
    expect(upstreamUrl('sign-in/email', new URLSearchParams('a=1&b=2'), UP)?.href).toBe(`${UP}/sign-in/email?a=1&b=2`)
    expect(upstreamUrl('/get-session', new URLSearchParams(), UP)?.href).toBe(`${UP}/get-session`)
  })

  it.each(['../secrets', 'a/../../b', 'a/./b', '..', 'https://evil.example/x', 'javascript:alert(1)', 'a\\..\\b'])('refuses %j', (path) => {
    expect(upstreamUrl(path, new URLSearchParams(), UP)).toBeNull()
  })
})

function request(path: string, init: RequestInit = {}, query = '') {
  return new Request(`https://synapsed-web.vercel.app/api/neon-auth?path=${encodeURIComponent(path)}${query}`, init)
}

it('keeps a path with leading slashes inside the auth service (it is just a route there)', () => {
  const url = upstreamUrl('//evil.example/x', new URLSearchParams(), UP)
  expect(url?.host).toBe('auth.example.neon.tech')
  expect(url?.href.startsWith(`${UP}/`)).toBe(true)
})

describe('forward', () => {
  it('sends the request to the auth service with its own host, the cookie and the body, dropping per-connection headers', async () => {
    const upstream = vi.fn(async () => new Response('{"ok":true}', { status: 200, headers: { 'content-type': 'application/json' } }))
    const res = await forward(
      request('sign-in/email', { method: 'POST', headers: { 'content-type': 'application/json', cookie: 'sid=abc', origin: 'https://synapsed-web.vercel.app', host: 'synapsed-web.vercel.app', 'x-forwarded-for': '1.2.3.4', 'accept-encoding': 'br' }, body: '{"email":"a@b.co"}' }, '&x=1'),
      'sign-in/email', UP, upstream as unknown as typeof fetch,
    )
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ok: true })
    const [target, init] = upstream.mock.calls[0] as unknown as [URL, RequestInit]
    expect(target.href).toBe(`${UP}/sign-in/email?x=1`) // the rewrite's "path" parameter is not forwarded
    expect(init.method).toBe('POST')
    const sent = init.headers as Headers
    expect(sent.get('cookie')).toBe('sid=abc')
    expect(sent.get('origin')).toBe('https://synapsed-web.vercel.app')
    expect(sent.get('content-type')).toBe('application/json')
    for (const dropped of ['host', 'x-forwarded-for', 'accept-encoding']) expect(sent.has(dropped)).toBe(false)
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe('{"email":"a@b.co"}')
  })

  it('keeps several Set-Cookie headers separate and drops headers that no longer describe the body', async () => {
    const headers = new Headers({ 'content-type': 'application/json', 'content-encoding': 'gzip', 'content-length': '999', 'set-auth-jwt': 'tok' })
    headers.append('set-cookie', '__Secure-neon-auth.session_token=a; Path=/; Secure; HttpOnly; SameSite=None')
    headers.append('set-cookie', 'other=b; Path=/')
    const res = await forward(request('get-session'), 'get-session', UP, (async () => new Response('{}', { status: 200, headers })) as unknown as typeof fetch)
    expect(res.headers.getSetCookie()).toEqual(['__Secure-neon-auth.session_token=a; Path=/; Secure; HttpOnly; SameSite=None', 'other=b; Path=/'])
    expect(res.headers.get('set-auth-jwt')).toBe('tok') // the JWT header the SDK reads must survive
    expect(res.headers.has('content-encoding')).toBe(false)
    expect(res.headers.has('content-length')).toBe(false)
  })

  it('passes redirects (Google sign-in) to the browser instead of following them', async () => {
    const upstream = vi.fn(async () => new Response(null, { status: 302, headers: { location: 'https://accounts.google.com/o/oauth2/v2/auth?x=1' } }))
    const res = await forward(request('sign-in/social', { method: 'POST', body: '{}' }), 'sign-in/social', UP, upstream as unknown as typeof fetch)
    expect(res.status).toBe(302)
    expect(res.headers.get('location')).toBe('https://accounts.google.com/o/oauth2/v2/auth?x=1')
    expect((upstream.mock.calls[0] as unknown as [URL, RequestInit])[1].redirect).toBe('manual')
  })

  it('passes errors through with their status and body', async () => {
    const res = await forward(request('sign-in/email', { method: 'POST', body: '{}' }), 'sign-in/email', UP, (async () => new Response('{"code":"EMAIL_NOT_VERIFIED"}', { status: 403 })) as unknown as typeof fetch)
    expect(res.status).toBe(403)
    expect(await res.json()).toEqual({ code: 'EMAIL_NOT_VERIFIED' })
  })

  it('sends no body for a GET', async () => {
    const upstream = vi.fn(async () => new Response('{}'))
    await forward(request('get-session'), 'get-session', UP, upstream as unknown as typeof fetch)
    expect((upstream.mock.calls[0] as unknown as [URL, RequestInit])[1].body).toBeUndefined()
  })

  it('answers 502 with a readable message when the service is unreachable', async () => {
    const res = await forward(request('get-session'), 'get-session', UP, (async () => { throw new TypeError('fetch failed') }) as unknown as typeof fetch)
    expect(res.status).toBe(502)
    expect((await res.json()).error).toMatch(/unreachable/)
  })

  it('answers 404 and never calls out for a path that tries to leave the service', async () => {
    const upstream = vi.fn()
    const res = await forward(request('../../admin'), '../../admin', UP, upstream as unknown as typeof fetch)
    expect(res.status).toBe(404)
    expect(upstream).not.toHaveBeenCalled()
  })

  it('does not put a body on a 204', async () => {
    const res = await forward(request('sign-out', { method: 'POST', body: '{}' }), 'sign-out', UP, (async () => new Response(null, { status: 204 })) as unknown as typeof fetch)
    expect(res.status).toBe(204)
    expect(res.body).toBeNull()
  })
})
