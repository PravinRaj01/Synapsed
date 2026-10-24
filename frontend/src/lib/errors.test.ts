import { describe, expect, it } from 'vitest'
import { detailMessage, messageFor, retryAfterSeconds } from './errors'

describe('detailMessage', () => {
  it('uses a string detail', () => expect(detailMessage({ detail: 'Campaign not found' }, 'x')).toBe('Campaign not found'))

  it('names the field in a validation problem and hides the body/query prefix', () => {
    const body = { detail: [{ loc: ['body', 'weight'], msg: 'Input should be greater than 0' }] }
    expect(detailMessage(body, 'x')).toBe('weight: Input should be greater than 0')
    expect(detailMessage({ detail: [{ loc: ['query', 'q'], msg: 'String should have at least 2 characters' }] }, 'x')).toBe('q: String should have at least 2 characters')
  })

  it.each([null, undefined, {}, { detail: '' }, { detail: [] }, { detail: 5 }, 'text'])('falls back for %j', (body) => {
    expect(detailMessage(body, 'fallback')).toBe('fallback')
  })
})

describe('retryAfterSeconds', () => {
  it.each([
    ['40', 40],
    ['1.2', 2],
    ['0', null],
    ['-3', null],
    ['soon', null],
    [null, null],
  ])('%j -> %j', (header, expected) => expect(retryAfterSeconds(header)).toBe(expected))
})

describe('messageFor', () => {
  it('adds the wait to a 429 that does not already state it', () => {
    expect(messageFor(429, null, 30)).toBe('Too many requests. Please wait a moment. Try again in 30 seconds.')
  })

  it('does not repeat the wait when the server already said it', () => {
    expect(messageFor(429, { detail: 'Too many requests. Try again in 40 seconds.' }, 40)).toBe('Too many requests. Try again in 40 seconds.')
  })

  it('prefers the server message, then a plain fallback per status', () => {
    expect(messageFor(422, { detail: 'That segment is not part of this campaign' }, null)).toBe('That segment is not part of this campaign')
    expect(messageFor(404, null, null)).toMatch(/not found/i)
    expect(messageFor(502, null, null)).toMatch(/unavailable/i)
    expect(messageFor(418, null, null)).toBe('Something went wrong. Please try again.')
  })
})
