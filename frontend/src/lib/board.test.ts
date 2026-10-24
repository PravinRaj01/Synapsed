import { describe, expect, it } from 'vitest'
import { editOf, elapsed, evidenceByNumber, groupByHorizon, horizonLabel, iceScore, patchFor, prdFilename, storyEvidence, versionLabel, withHorizon, type Evidence, type Prd, type PrdVersion, type RoadmapItem, type UserStory } from './board'

const item = (id: string, patch: Partial<RoadmapItem> = {}): RoadmapItem => ({
  id, campaign_id: 'c', theme_id: 't', theme: 'Exports', color: '#ec4899', insight_id: null, title: `Item ${id}`, description: `About ${id}`, horizon: 'now',
  impact_score: 8, confidence_score: 6, ease_score: 5, ice_score: 240, created_at: '2026-10-24T00:00:00Z', ...patch,
})

describe('groupByHorizon', () => {
  const items = [item('a', { ice_score: 100, horizon: 'next' }), item('b', { ice_score: 480 }), item('c', { ice_score: 240 }), item('d', { ice_score: 240, title: 'Alpha' }), item('e', { ice_score: 50, horizon: 'later' })]
  it('puts each card in its column, highest ICE first, ties by title', () => {
    const g = groupByHorizon(items)
    expect(g.now.map((i) => i.id)).toEqual(['b', 'd', 'c']) // 480, then the two 240s: "Alpha" before "Item c"
    expect(g.next.map((i) => i.id)).toEqual(['a'])
    expect(g.later.map((i) => i.id)).toEqual(['e'])
  })
  it('does not reorder the list it was given, and copes with nothing', () => {
    const before = items.map((i) => i.id)
    groupByHorizon(items)
    expect(items.map((i) => i.id)).toEqual(before)
    expect(groupByHorizon([])).toEqual({ now: [], next: [], later: [] })
  })
})

describe('withHorizon', () => {
  const items = [item('a'), item('b')]
  it('moves one card and keeps the others as they were', () => {
    const out = withHorizon(items, 'a', 'later')
    expect(out[0].horizon).toBe('later')
    expect(out[1]).toBe(items[1])
    expect(items[0].horizon).toBe('now') // the original is untouched
  })
  it('changes nothing when the card is already there or does not exist', () => {
    expect(withHorizon(items, 'a', 'now')[0]).toBe(items[0])
    expect(withHorizon(items, 'zzz', 'next')).toEqual(items)
  })
})

describe('scores and edits', () => {
  it('multiplies impact, confidence and ease', () => {
    expect(iceScore(8, 6, 5)).toBe(240)
    expect(iceScore(10, 10, 10)).toBe(1000)
  })
  it('sends only what changed', () => {
    const i = item('a')
    expect(patchFor(i, editOf(i))).toBeNull()
    expect(patchFor(i, { ...editOf(i), ease_score: 9 })).toEqual({ ease_score: 9 })
    expect(patchFor(i, { ...editOf(i), title: '  Item   a  ', description: 'About a ' })).toBeNull() // whitespace is not a change
    expect(patchFor(i, { ...editOf(i), title: 'Better   title' })).toEqual({ title: 'Better title' })
  })
  it('keeps scores inside 1 to 10 and whole', () => {
    const i = item('a')
    expect(patchFor(i, { ...editOf(i), impact_score: 14 })).toEqual({ impact_score: 10 })
    expect(patchFor(i, { ...editOf(i), impact_score: -3, confidence_score: 2.4 })).toEqual({ impact_score: 1, confidence_score: 2 })
  })
  it('refuses an empty title or description', () => {
    const i = item('a')
    expect(patchFor(i, { ...editOf(i), title: '   ' })).toBeNull()
    expect(patchFor(i, { ...editOf(i), description: '' })).toBeNull()
  })
  it('names the columns', () => {
    expect(horizonLabel('now')).toBe('Now')
    expect(horizonLabel('later')).toBe('Later')
  })
})

describe('PRD helpers', () => {
  const ev = (n: number): Evidence => ({ n, insight_id: `i${n}`, summary: `s${n}`, severity: 3, sentiment: 'negative', segment: null, quote: `quote ${n}`, resource_id: 'r', resource_title: 'Interview', start_offset: 0, end_offset: 5 })
  const prd = { id: 'p', roadmap_item_id: 'a', markdown: '# x', jira_issue_key: null, created_at: '2026-10-24T00:00:00Z', content: { prd: { title: 'T', context: '', problem: '', goals: [], user_stories: [], acceptance_criteria: [], out_of_scope: [], success_metrics: [] }, evidence: [ev(1), ev(2), ev(3)] } } as Prd
  const story = (evidence: number[]): UserStory => ({ as_a: 'a', i_want: 'b', so_that: 'c', evidence })

  it('finds the evidence for a story by number and skips a number it does not have', () => {
    const map = evidenceByNumber(prd)
    expect(storyEvidence(story([3, 1]), map).map((e) => e.quote)).toEqual(['quote 3', 'quote 1'])
    expect(storyEvidence(story([2, 9]), map).map((e) => e.n)).toEqual([2])
    expect(storyEvidence(story([]), map)).toEqual([])
  })
  it('makes a safe Markdown file name', () => {
    expect(prdFilename('Make bank matching suggestions reliable')).toBe('make-bank-matching-suggestions-reliable-prd.md')
    expect(prdFilename('Pelanggan: Cabaran / Utama?')).toBe('pelanggan-cabaran-utama-prd.md')
    expect(prdFilename('???')).toBe('prd-prd.md')
  })
  it('numbers versions from the oldest, newest first in the list', () => {
    const v = (key: string | null): PrdVersion => ({ id: 'x', roadmap_item_id: 'a', title: 'T', jira_issue_key: key, created_at: '2026-10-24T00:00:00Z' })
    expect(versionLabel(v(null), 0, 3)).toBe('Version 3')
    expect(versionLabel(v('PROJ-12'), 2, 3)).toBe('Version 1 · PROJ-12')
  })
  it('writes the wait as seconds, then minutes', () => {
    expect(elapsed(0)).toBe('0s')
    expect(elapsed(12.9)).toBe('12s')
    expect(elapsed(65)).toBe('1m 05s')
    expect(elapsed(-4)).toBe('0s')
  })
})
