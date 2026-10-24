import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SEGMENTS,
  EMPTY_SETUP,
  greeting,
  percentChange,
  sentimentShares,
  setupSchema,
  suggestedActions,
  type Overview,
} from './onboarding'

const overview = (patch: Partial<Overview> = {}): Overview => ({
  resources: { total: 10, staged: 0, approved: 10, rejected: 0, waiting_for_analysis: 0 },
  insights: 37,
  themes: 6,
  roadmap_items: 5,
  segments: 3,
  sentiment: { positive: 6, neutral: 5, negative: 26 },
  trend: { days: 7, resources: { current: 5, previous: 5 }, insights: { current: 17, previous: 20 }, themes: { current: 6, previous: 0 } },
  top_themes: [],
  recent_resources: [],
  last_run: null,
  telemetry: { calls: 0, tokens: 0, fallbacks: 0, by_model: [] },
  ...patch,
})

describe('percentChange', () => {
  it('rounds the change from the previous period', () => {
    expect(percentChange(17, 20)).toBe(-15)
    expect(percentChange(12, 10)).toBe(20)
    expect(percentChange(5, 5)).toBe(0)
  })
  it('has nothing to say when there was nothing before', () => {
    expect(percentChange(6, 0)).toBeNull()
    expect(percentChange(0, 0)).toBeNull()
  })
})

describe('sentimentShares', () => {
  it('adds up to exactly 100 whatever the rounding', () => {
    for (const s of [{ positive: 1, neutral: 1, negative: 1 }, { positive: 6, neutral: 5, negative: 26 }, { positive: 2, neutral: 0, negative: 1 }]) {
      expect(sentimentShares(s).reduce((a, b) => a + b.percent, 0)).toBe(100)
    }
  })
  it('keeps the counts and the order', () => {
    expect(sentimentShares({ positive: 6, neutral: 5, negative: 26 })).toEqual([
      { key: 'positive', count: 6, percent: 16 },
      { key: 'neutral', count: 5, percent: 14 },
      { key: 'negative', count: 26, percent: 70 },
    ])
  })
  it('is all zero with no insights', () => {
    expect(sentimentShares({}).map((s) => s.percent)).toEqual([0, 0, 0])
  })
})

describe('suggestedActions', () => {
  it('asks for the first sources when there are none', () => {
    const a = suggestedActions(overview({ resources: { total: 0, staged: 0, approved: 0, rejected: 0, waiting_for_analysis: 0 }, themes: 0, roadmap_items: 0 }))
    expect(a.map((x) => x.id)).toEqual(['add'])
  })
  it('lists staged and unanalysed sources before the roadmap, with singular and plural wording', () => {
    const a = suggestedActions(overview({ resources: { total: 4, staged: 1, approved: 3, rejected: 0, waiting_for_analysis: 3 } }))
    expect(a.map((x) => x.id)).toEqual(['review', 'analyse', 'roadmap'])
    expect(a[0].title).toBe('Review 1 source waiting for approval')
    expect(a[1].title).toBe('Analyse 3 approved sources')
  })
  it('flags a run that did not finish', () => {
    const run = { run_id: 'r', started_at: '2026-10-24T00:00:00Z' }
    expect(suggestedActions(overview({ last_run: { ...run, status: 'stale' } })).map((x) => x.id)).toContain('rerun')
    expect(suggestedActions(overview({ last_run: { ...run, status: 'done' } })).map((x) => x.id)).not.toContain('rerun')
  })
  it('has nothing to suggest for a campaign that is all caught up and empty of themes', () => {
    expect(suggestedActions(overview({ themes: 0, roadmap_items: 0 }))).toEqual([])
  })
})

describe('setupSchema', () => {
  const valid = {
    profile: { company: 'Acme', industry: 'SaaS', domain: '', targetAudience: '', ownerRole: '' },
    campaign: { name: 'Q4 research', goal: '', segments: DEFAULT_SEGMENTS },
  }
  it('accepts a complete setup', () => {
    expect(setupSchema(true).safeParse(valid).success).toBe(true)
  })
  it('requires the business profile only for a first workspace', () => {
    expect(setupSchema(true).safeParse(EMPTY_SETUP).success).toBe(false)
    expect(setupSchema(false).safeParse({ ...EMPTY_SETUP, campaign: valid.campaign }).success).toBe(true)
  })
  it('rejects duplicate segment names regardless of case or spacing', () => {
    const dup = { ...valid, campaign: { ...valid.campaign, segments: [DEFAULT_SEGMENTS[0], { ...DEFAULT_SEGMENTS[1], name: ' enterprise ' }] } }
    const result = setupSchema(true).safeParse(dup)
    expect(result.success).toBe(false)
    expect(result.error?.issues[0].message).toBe('Segment names must be different')
  })
  it('keeps segment weights within the range the API accepts', () => {
    for (const weight of [0, 0.05, 21, Number.NaN]) {
      const bad = { ...valid, campaign: { ...valid.campaign, segments: [{ ...DEFAULT_SEGMENTS[0], weight }] } }
      expect(setupSchema(true).safeParse(bad).success, String(weight)).toBe(false)
    }
  })
})

describe('greeting', () => {
  it('follows the time of day', () => {
    expect(greeting(new Date(2026, 9, 24, 8))).toBe('Good morning')
    expect(greeting(new Date(2026, 9, 24, 13))).toBe('Good afternoon')
    expect(greeting(new Date(2026, 9, 24, 21))).toBe('Good evening')
  })
})
