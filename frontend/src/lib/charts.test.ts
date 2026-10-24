import { describe, expect, it } from 'vitest'
import { axisLabel, clip, colorsFor, describeSpec, foldSlices, formatValue, hasData, isHorizontal, plotPoints, quadrantCorners, shortWeek, toRows, toTable, type ChartResult, type ChartSpec, type MatrixPoint, type OpportunityMatrix } from './charts'

const result: ChartResult = {
  x: ['Enterprise', 'Free', 'Mid-Market'],
  series: [{ name: 'negative', values: [8, 3, 5] }, { name: 'positive', values: [1, 2, 0] }],
  measure: 'Insights',
}

describe('colorsFor', () => {
  it('gives sentiment its status colours and the rest the palette, in order', () => {
    expect(colorsFor(['Enterprise', 'Free'])).toEqual(['var(--series-1)', 'var(--series-2)'])
    expect(colorsFor(['negative', 'positive', 'neutral'])).toEqual(['var(--negative)', 'var(--positive)', 'var(--muted)'])
  })
  it('does not use up a palette slot on a status colour', () => {
    expect(colorsFor(['Enterprise', 'negative', 'Free'])).toEqual(['var(--series-1)', 'var(--negative)', 'var(--series-2)'])
  })
  it('is case-insensitive for sentiment and starts over after the palette runs out', () => {
    expect(colorsFor(['Negative'])).toEqual(['var(--negative)'])
    const many = colorsFor(Array.from({ length: 8 }, (_, i) => `s${i}`))
    expect(many[6]).toBe(many[0])
  })
  it('gives the same colour to the same entity however many others are around', () => {
    expect(colorsFor(['Enterprise', 'Free'])[0]).toBe(colorsFor(['Enterprise'])[0])
  })
})

describe('toRows and toTable', () => {
  it('makes a row per x value with a column per series', () => {
    expect(toRows(result)).toEqual([
      { x: 'Enterprise', negative: 8, positive: 1 }, { x: 'Free', negative: 3, positive: 2 }, { x: 'Mid-Market', negative: 5, positive: 0 },
    ])
  })
  it('fills a missing value with zero', () => {
    expect(toRows({ x: ['a', 'b'], series: [{ name: 's', values: [4] }], measure: 'm' })).toEqual([{ x: 'a', s: 4 }, { x: 'b', s: 0 }])
  })
  it('writes a table, with a total column only when asked', () => {
    expect(toTable(result, 'Segment')).toEqual({ head: ['Segment', 'negative', 'positive'], body: [['Enterprise', '8', '1'], ['Free', '3', '2'], ['Mid-Market', '5', '0']] })
    const withTotal = toTable(result, 'Segment', true)
    expect(withTotal.head.at(-1)).toBe('Total')
    expect(withTotal.body.map((r) => r.at(-1))).toEqual(['9', '5', '5'])
  })
})

describe('hasData and formatValue', () => {
  it('has data only when something is above zero', () => {
    expect(hasData(result)).toBe(true)
    expect(hasData({ x: ['a'], series: [{ name: 's', values: [0] }], measure: 'm' })).toBe(false)
    expect(hasData({ x: [], series: [], measure: 'm' })).toBe(false)
  })
  it('keeps whole numbers whole and rounds the rest to one decimal', () => {
    expect(formatValue(1200)).toBe((1200).toLocaleString())
    expect(formatValue(3.456)).toBe('3.5')
    expect(formatValue(0)).toBe('0')
  })
})

describe('describeSpec', () => {
  const spec = (patch: Partial<ChartSpec> = {}): ChartSpec => ({ type: 'bar', x: 'theme', y: 'impact', split_by: null, filters: [], limit: 12, title: null, ...patch }) as ChartSpec
  it('says what is measured and how it is grouped', () => {
    expect(describeSpec(spec(), 'Business impact')).toBe('Business impact by theme')
    expect(describeSpec(spec({ x: 'segment', split_by: 'sentiment' }), 'Insights')).toBe('Insights by segment, split by sentiment')
  })
  it('names the filters', () => {
    expect(describeSpec(spec({ filters: [{ field: 'segment', values: ['Enterprise', 'Free'] }, { field: 'sentiment', values: ['negative'] }] }), 'Insights')).toBe('Insights by theme, only segment Enterprise or Free and sentiment negative')
  })
  it('passes an unknown dimension through', () => {
    expect(axisLabel('theme')).toBe('Theme')
    expect(axisLabel('mystery')).toBe('mystery')
  })
})

describe('labels', () => {
  it('shortens an ISO week and leaves other labels alone', () => {
    expect(shortWeek('2026-10-19')).toBe(new Date(2026, 9, 19).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }))
    expect(shortWeek('Enterprise')).toBe('Enterprise')
    expect(shortWeek('2026-10')).toBe('2026-10')
  })
  it('clips only what is too long', () => {
    expect(clip('Short')).toBe('Short')
    expect(clip('Missing accounting and payroll integrations', 16)).toBe('Missing account…')
    expect(clip('Missing accounting and payroll integrations', 16)).toHaveLength(16)
  })
})

describe('quadrantCorners', () => {
  const matrix = { impact_line: 50, frequency_line: 3, points: [], quadrants: [
    { key: 'priority', label: 'Frequent and high impact' }, { key: 'high_stakes', label: 'High impact, mentioned less often' },
    { key: 'common_annoyance', label: 'Frequent, lower impact' }, { key: 'monitor', label: 'Lower impact, less frequent' }, { key: 'mystery', label: 'Unknown' },
  ] } as OpportunityMatrix
  it('places each named quadrant in its corner and ignores one it does not know', () => {
    const corners = quadrantCorners(matrix)
    expect(Object.fromEntries(corners.map((c) => [c.key, c.corner]))).toEqual({ priority: 'tr', high_stakes: 'tl', common_annoyance: 'br', monitor: 'bl' })
  })
})

describe('foldSlices', () => {
  const big: ChartResult = { x: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'], series: [{ name: 'Insights', values: [1, 8, 3, 2, 9, 4, 1, 2] }], measure: 'Insights' }
  it('keeps the biggest slices and folds the rest into Other, without losing any of the total', () => {
    const folded = foldSlices(big)
    expect(folded.x).toEqual(['e', 'b', 'f', 'c', 'd', 'Other']) // six slices at most: five kept, then Other
    expect(folded.series[0].values).toEqual([9, 8, 4, 3, 2, 1 + 1 + 2])
    expect(folded.series[0].values.reduce((a, b) => a + b, 0)).toBe(30)
  })
  it('leaves a short list, and a chart with no series, alone', () => {
    const small: ChartResult = { x: ['a', 'b'], series: [{ name: 'n', values: [1, 2] }], measure: 'm' }
    expect(foldSlices(small)).toBe(small)
    const none: ChartResult = { x: ['a', 'b', 'c', 'd', 'e', 'f', 'g'], series: [], measure: 'm' }
    expect(foldSlices(none)).toBe(none)
  })
})

describe('isHorizontal', () => {
  const r = (x: string[]): ChartResult => ({ x, series: [], measure: 'm' })
  it('uses columns for time and ordinal axes and short lists, bars for long names or many categories', () => {
    expect(isHorizontal(r(['Report exports time out']), 'theme')).toBe(true)
    expect(isHorizontal(r(['Free', 'Pro']), 'segment')).toBe(false)
    expect(isHorizontal(r(['2026-10-12', '2026-10-19']), 'week')).toBe(false)
    expect(isHorizontal(r(['1', '2', '3', '4', '5']), 'severity')).toBe(false)
    expect(isHorizontal(r(['a', 'b', 'c', 'd', 'e', 'f', 'g']), 'segment')).toBe(true)
  })
})

describe('plotPoints', () => {
  const pt = (label: string, frequency: number, business_impact: number) => ({ theme_id: label, label, color: '#000', frequency, business_impact, ice_score: null, horizon: null, quadrant: 'monitor', quadrant_label: 'x' }) as MatrixPoint
  it('numbers the themes by impact, highest first', () => {
    const out = plotPoints([pt('low', 2, 20), pt('high', 7, 100), pt('mid', 4, 60)])
    expect(out.map((p) => [p.rank, p.label])).toEqual([[1, 'high'], [2, 'mid'], [3, 'low']])
  })
  it('nudges themes on exactly the same spot apart but keeps their true values', () => {
    const out = plotPoints([pt('a', 6, 65.6), pt('b', 6, 66.2), pt('c', 5, 66)])
    const a = out.find((p) => p.label === 'a')!
    const b = out.find((p) => p.label === 'b')!
    const c = out.find((p) => p.label === 'c')!
    expect(a.y).toBe(66)
    expect(b.y).toBe(66)
    expect(new Set([a.shownX, b.shownX]).size).toBe(2) // both visible
    expect(a.x).toBe(6)
    expect(b.x).toBe(6)
    expect(c.shownX).toBe(5) // alone, so untouched
  })
  it('copes with no themes', () => {
    expect(plotPoints([])).toEqual([])
  })
})
