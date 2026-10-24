import { API_URL } from './api'
import { getAccessToken } from './auth'
import { ApiError, messageFor, retryAfterSeconds } from './errors'

export type SseEvent = { event: string; data: unknown }

/** Parse a Server-Sent Events byte stream into events. Handles chunks that split lines or events, CRLF, and comments. */
export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let end: number
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        const event = parseBlock(block)
        if (event) yield event
      }
      if (done) {
        const event = parseBlock(buffer)
        if (event) yield event
        return
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith(':') || !line.trim()) continue // keep-alive comments
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }
  if (!data.length) return null
  const text = data.join('\n')
  try {
    return { event, data: JSON.parse(text) }
  } catch {
    return { event, data: text }
  }
}

/**
 * POST to a streaming endpoint and yield its events as they arrive. EventSource cannot send an Authorization
 * header, so this uses fetch. Throws an ApiError if the request itself is refused (for example 409 or 429).
 */
export async function* postStream(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<SseEvent> {
  const token = await getAccessToken()
  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    const retryAfter = retryAfterSeconds(response.headers.get('retry-after'))
    const error = await response.json().catch(() => null)
    throw new ApiError(response.status, messageFor(response.status, error, retryAfter), retryAfter)
  }
  yield* parseSse(response.body)
}
