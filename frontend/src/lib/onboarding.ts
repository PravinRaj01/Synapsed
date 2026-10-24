import { z } from 'zod'
import type { components } from '@/api/schema'

export type Overview = components['schemas']['OverviewOut']
export type Tier = components['schemas']['SegmentIn']['tier']

export const MAX_SEGMENTS = 20
export const MAX_WEIGHT = 20

export const TIERS: { value: NonNullable<Tier>; label: string }[] = [
  { value: 'enterprise', label: 'Enterprise' },
  { value: 'mid_market', label: 'Mid-market' },
  { value: 'free', label: 'Free' },
  { value: 'other', label: 'Other' },
]

/** The starting customer groups: bigger customers count for more when problems are ranked. */
export const DEFAULT_SEGMENTS = [
  { name: 'Enterprise', tier: 'enterprise' as const, weight: 3 },
  { name: 'Mid-Market', tier: 'mid_market' as const, weight: 2 },
  { name: 'Free', tier: 'free' as const, weight: 1 },
]

const text = (what: string, max: number) => z.string().trim().min(1, `Enter ${what}`).max(max, `Use at most ${max} characters`)
const optionalText = (max: number) => z.string().trim().max(max, `Use at most ${max} characters`)

export const profileSchema = z.object({
  company: text('your company name', 120),
  industry: text('your industry', 120),
  domain: optionalText(300),
  targetAudience: optionalText(300),
  ownerRole: optionalText(120),
})

export type ProfileValues = z.infer<typeof profileSchema>

export const segmentSchema = z.object({
  name: text('a segment name', 80),
  tier: z.enum(['enterprise', 'mid_market', 'free', 'other']),
  weight: z
    .number('Enter a weight')
    .min(0.1, 'At least 0.1')
    .max(MAX_WEIGHT, `At most ${MAX_WEIGHT}`),
})

export const campaignSchema = z.object({
  name: text('a campaign name', 120),
  goal: optionalText(500),
  segments: z
    .array(segmentSchema)
    .max(MAX_SEGMENTS, `At most ${MAX_SEGMENTS} segments`)
    .refine((list) => new Set(list.map((s) => s.name.trim().toLowerCase())).size === list.length, 'Segment names must be different'),
})

/** The whole wizard. The business profile is only asked for when the user has no workspace yet. */
export function setupSchema(needsProfile: boolean) {
  return z.object({
    profile: needsProfile ? profileSchema : z.custom<ProfileValues>(), // a returning user is not asked again
    campaign: campaignSchema,
  })
}
export type SetupValues = z.infer<ReturnType<typeof setupSchema>>

export const EMPTY_SETUP: SetupValues = {
  profile: { company: '', industry: '', domain: '', targetAudience: '', ownerRole: '' },
  campaign: { name: '', goal: '', segments: DEFAULT_SEGMENTS },
}

/** Percent change from the previous period to the current one, rounded; null when there is nothing to compare with. */
export function percentChange(current: number, previous: number): number | null {
  if (previous <= 0) return null
  return Math.round(((current - previous) / previous) * 100)
}

export type SuggestedAction = {
  id: string
  tone: 'accent' | 'warning' | 'negative' | 'positive'
  title: string
  detail: string
  to: string
  cta: string
}

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`

/** What the dashboard tells the user to do next, most urgent first. */
export function suggestedActions(o: Overview): SuggestedAction[] {
  const actions: SuggestedAction[] = []
  const status = o.last_run?.status
  if (o.resources.total === 0) {
    actions.push({ id: 'add', tone: 'accent', title: 'Add your first sources', detail: 'Upload interviews, tickets or surveys, or try the demo sandbox.', to: '/vault', cta: 'Open the vault' })
  }
  if (o.resources.staged > 0) {
    actions.push({ id: 'review', tone: 'warning', title: `Review ${plural(o.resources.staged, 'source')} waiting for approval`, detail: 'Nothing is analysed until you approve it.', to: '/vault', cta: 'Review' })
  }
  if (o.resources.waiting_for_analysis > 0) {
    actions.push({ id: 'analyse', tone: 'accent', title: `Analyse ${plural(o.resources.waiting_for_analysis, 'approved source')}`, detail: 'They have not been turned into insights yet.', to: '/vault', cta: 'Run analysis' })
  }
  if (status === 'error' || status === 'stale') {
    actions.push({ id: 'rerun', tone: 'negative', title: 'The last analysis did not finish', detail: 'Start it again; sources already analysed are skipped.', to: '/vault', cta: 'Try again' })
  }
  if (o.themes > 0 && o.roadmap_items > 0) {
    actions.push({ id: 'roadmap', tone: 'positive', title: `Review your ${plural(o.roadmap_items, 'roadmap item')}`, detail: 'Ranked by impact, confidence and ease.', to: '/roadmap', cta: 'Open roadmap' })
  }
  return actions
}

export type SentimentShare = { key: 'positive' | 'neutral' | 'negative'; count: number; percent: number }

/** Each sentiment's count and whole-number share; shares add up to 100 (the largest remainder absorbs rounding). */
export function sentimentShares(sentiment: Record<string, number>): SentimentShare[] {
  const keys = ['positive', 'neutral', 'negative'] as const
  const total = keys.reduce((sum, k) => sum + (sentiment[k] ?? 0), 0)
  if (total === 0) return keys.map((key) => ({ key, count: 0, percent: 0 }))
  const raw = keys.map((key) => ({ key, count: sentiment[key] ?? 0, exact: ((sentiment[key] ?? 0) / total) * 100 }))
  const floors = raw.map((r) => Math.floor(r.exact))
  let left = 100 - floors.reduce((a, b) => a + b, 0)
  const order = raw.map((r, i) => ({ i, rest: r.exact - floors[i] })).sort((a, b) => b.rest - a.rest)
  for (const { i } of order) {
    if (left <= 0) break
    floors[i] += 1
    left -= 1
  }
  return raw.map((r, i) => ({ key: r.key, count: r.count, percent: floors[i] }))
}

/** "Good morning" / "Good afternoon" / "Good evening" for a local time. */
export function greeting(date = new Date()): string {
  const h = date.getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}
