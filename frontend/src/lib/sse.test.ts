import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseSse, postStream, type SseEvent } from './sse'

vi.mock('./auth', () => ({ getAccessToken: vi.fn(async () => 'tok'), clearAccessToken: vi.fn() }))

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const out: SseEvent[] = []
  for await (const e of parseSse(stream)) out.push(e)
  return out
}

describe('parseSse', () => {
  it('reads events with a name and JSON data', async () => {
    const events = await collect(streamOf(['event: run\ndata: {"run_id":"r1"}\n\nevent: trace\ndata: {"node":"select","status":"running"}\n\n']))
    expect(events).toEqual([
      { event: 'run', data: { run_id: 'r1' } },
      { event: 'trace', data: { node: 'select', status: 'running' } },
    ])
  })

  it('copes with a chunk that ends in the middle of a line, an event, or a multi-byte character', async () => {
    const whole = 'event: trace\ndata: {"text":"café ☕"}\n\nevent: summary\ndata: {"remaining":0}\n\n'
    const bytes = new TextEncoder().encode(whole)
    const encoder = new TextDecoder()
    for (const cut of [5, 20, 31, 33, 40]) {
      const stream = new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(bytes.slice(0, cut))
          c.enqueue(bytes.slice(cut))
          c.close()
        },
      })
      const events = await collect(stream)
      expect(events.map((e) => e.event), `cut at ${cut}: ${encoder.decode(bytes.slice(0, cut))}`).toEqual(['trace', 'summary'])
      expect(events[0].data).toEqual({ text: 'café ☕' })
    }
  })

  it('handles CRLF line endings and ignores keep-alive comments', async () => {
    const events = await collect(streamOf([': keep-alive\r\n\r\nevent: summary\r\ndata: {"ok":true}\r\n\r\n: keep-alive\n\n']))
    expect(events).toEqual([{ event: 'summary', data: { ok: true } }])
  })

  it('defaults the event name, keeps non-JSON data as text, and joins multi-line data', async () => {
    const events = await collect(streamOf(['data: hello\n\nevent: note\ndata: line one\ndata: line two\n\n']))
    expect(events).toEqual([
      { event: 'message', data: 'hello' },
      { event: 'note', data: 'line one\nline two' },
    ])
  })

  it('delivers a final event the server did not terminate with a blank line', async () => {
    expect(await collect(streamOf(['event: summary\ndata: {"remaining":2}']))).toEqual([{ event: 'summary', data: { remaining: 2 } }])
  })

  it('yields nothing for an empty stream', async () => {
    expect(await collect(streamOf([]))).toEqual([])
  })
})

describe('postStream', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends the bearer token and streams the events back', async () => {
    const fetchMock = vi.fn(async () => new Response(streamOf(['event: run\ndata: {"run_id":"r"}\n\n']), { status: 200, headers: { 'content-type': 'text/event-stream' } }))
    vi.stubGlobal('fetch', fetchMock)
    const got: SseEvent[] = []
    for await (const e of postStream('/api/v1/analyze', { campaign_id: 'c' })) got.push(e)
    expect(got).toEqual([{ event: 'run', data: { run_id: 'r' } }])
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toMatch(/\/api\/v1\/analyze$/)
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
    expect(JSON.parse(init.body as string)).toEqual({ campaign_id: 'c' })
  })

  it('turns a refused request into an error with the server message and the wait', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Too many requests. Try again in 40 seconds.' }), { status: 429, headers: { 'retry-after': '40' } })))
    await expect(postStream('/api/v1/analyze', {}).next()).rejects.toMatchObject({ status: 429, retryAfter: 40, message: 'Too many requests. Try again in 40 seconds.' })
  })

  it('reports an analysis that is already running (409)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'An analysis is already running for this campaign' }), { status: 409 })))
    await expect(postStream('/api/v1/analyze', {}).next()).rejects.toMatchObject({ status: 409, message: 'An analysis is already running for this campaign' })
  })
})
