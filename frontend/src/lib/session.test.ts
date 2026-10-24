import { describe, expect, it } from 'vitest'
import { firstName, initials } from './session'
import { zodResolver } from './zodResolver'
import { z } from 'zod'

describe('initials and firstName', () => {
  it.each([
    [{ name: 'Maya Tan', email: 'm@x.io' }, 'MT', 'Maya'],
    [{ name: 'Pravin', email: 'p@x.io' }, 'P', 'Pravin'],
    [{ name: '', email: 'maya.tan@x.io' }, 'MT', 'maya'],
    [{ name: '  ', email: 'solo@x.io' }, 'S', 'solo'],
  ])('%j', (user, initial, first) => {
    expect(initials(user)).toBe(initial)
    expect(firstName(user)).toBe(first)
  })
})

describe('zodResolver', () => {
  const schema = z.object({ email: z.email('Enter a valid email address'), password: z.string().min(8, 'Use at least 8 characters') })
  const resolve = zodResolver(schema)
  const run = (values: unknown) => resolve(values as never, undefined, { fields: {}, shouldUseNativeValidation: false } as never)

  it('passes valid values through', async () => {
    expect(await run({ email: 'a@b.co', password: 'longenough' })).toEqual({ values: { email: 'a@b.co', password: 'longenough' }, errors: {} })
  })

  it('reports the first problem per field with its message', async () => {
    const result = await run({ email: 'nope', password: 'short' })
    expect(result.values).toEqual({})
    expect(result.errors).toMatchObject({ email: { message: 'Enter a valid email address' }, password: { message: 'Use at least 8 characters' } })
  })
})
