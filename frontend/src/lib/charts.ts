import type { components } from '@/api/schema'

export type ChartSpec = components['schemas']['ChartSpec']
export type ChartResult = components['schemas']['ChartResultOut']
export type PresetChart = components['schemas']['PresetChartOut']
export type PromptChart = components['schemas']['PromptChartOut']
export type OpportunityMatrix = components['schemas']['OpportunityMatrixOut']
export type MatrixPoint = components['schemas']['MatrixPointOut']

/**
 * Categorical colours, in a fixed order (never reshuffled when a series is filtered away). Defined as CSS variables in
 * index.css, with separate steps for the dark theme; both sets were checked for colour-blind separation.
 */
export const SERIES_COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)']
export const MAX_SERIES = SERIES_COLORS.length

/** Sentiment is a status, not a category: the same colour wherever it appears. */
const SEMANTIC: Record<string, string> = { positive: 'var(--positive)', neutral: 'var(--muted)', negative: 'var(--negative)' }

/** The colour for each series. Sentiment names keep their status colours; the rest take the palette in order. */
export function colorsFor(names: string[]): string[] {
  let next = 0
  return names.map((n) => SEMANTIC[n.toLowerCase()] ?? SERIES_COLORS[next++ % MAX_SERIES])
}

export type Row = { x: string } & Record<string, string | number>

/** The result as one row per x value, with a column per series, the shape the chart library wants. */
export function toRows(result: ChartResult): Row[] {
  return result.x.map((x, i) => {
    const row: Row = { x }
    for (const s of result.series) row[s.name] = s.values[i] ?? 0
    return row
  })
}

/** A chart has something to show when at least one value is above zero. */
export function hasData(result: ChartResult): boolean {
  return result.series.some((s) => s.values.some((v) => v > 0))
}

/** Rounded for reading: whole numbers stay whole, others get at most one decimal. */
export function formatValue(value: number): string {
  return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 1 })
}

export type Table = { head: string[]; body: string[][] }

/** The same data as a table, for people who prefer numbers and for screen readers. A stacked chart gets a total column. */
export function toTable(result: ChartResult, axisLabel: string, withTotal = false): Table {
  const head = [axisLabel, ...result.series.map((s) => s.name)]
  if (withTotal) head.push('Total')
  const body = result.x.map((x, i) => {
    const values = result.series.map((s) => s.values[i] ?? 0)
    const cells = [x, ...values.map(formatValue)]
    if (withTotal) cells.push(formatValue(values.reduce((a, b) => a + b, 0)))
    return cells
  })
  return { head, body }
}

const AXIS_LABEL: Record<string, string> = {
  theme: 'Theme', segment: 'Segment', sentiment: 'Sentiment', use_case: 'Use case', kind: 'Kind', severity: 'Severity', source_type: 'Source type', language: 'Language', week: 'Week',
}
export const axisLabel = (x: string): string => AXIS_LABEL[x] ?? x

/** A readable line under the title: what is counted and how it is grouped. */
export function describeSpec(spec: ChartSpec, measure: string): string {
  const by = axisLabel(spec.x).toLowerCase()
  const split = spec.split_by ? `, split by ${axisLabel(spec.split_by).toLowerCase()}` : ''
  const list = spec.filters ?? []
  const filters = list.length ? `, only ${list.map((f) => `${axisLabel(f.field).toLowerCase()} ${f.values.join(' or ')}`).join(' and ')}` : ''
  return `${measure} by ${by}${split}${filters}`
}

/** A week label such as "2026-10-19" as "19 Oct"; anything else is left alone. */
export function shortWeek(label: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(label)
  if (!m) return label
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** Cut a long label for an axis, keeping the whole thing for the tooltip. */
export function clip(label: string, max = 16): string {
  return label.length > max ? `${label.slice(0, max - 1).trimEnd()}…` : label
}

export const SUGGESTED_PROMPTS = [
  'Sentiment by segment as a stacked bar',
  'New pain points per week as a line',
  'Which themes affect Enterprise customers most?',
  'Share of pain points vs feature requests as a pie',
]

/** Quadrant names to show in the matrix corners. The server names them; this orders them as drawn (top-left first). */
export function quadrantCorners(matrix: OpportunityMatrix): { key: string; label: string; corner: 'tl' | 'tr' | 'bl' | 'br' }[] {
  const place: Record<string, 'tl' | 'tr' | 'bl' | 'br'> = { high_stakes: 'tl', priority: 'tr', monitor: 'bl', common_annoyance: 'br' }
  return matrix.quadrants.flatMap((q) => (place[q.key] ? [{ key: q.key, label: q.label, corner: place[q.key] }] : []))
}

export const MAX_SLICES = 6

/** For a pie: keep the biggest slices and fold the rest into "Other", so the slices stay few enough to tell apart. */
export function foldSlices(result: ChartResult, max = MAX_SLICES): ChartResult {
  const first = result.series[0]
  if (!first || result.x.length <= max) return result
  const ranked = result.x.map((x, i) => ({ x, v: first.values[i] ?? 0 })).sort((a, b) => b.v - a.v)
  const keep = ranked.slice(0, max - 1)
  const rest = ranked.slice(max - 1).reduce((n, r) => n + r.v, 0)
  return { ...result, x: [...keep.map((k) => k.x), 'Other'], series: [{ ...first, values: [...keep.map((k) => k.v), rest] }] }
}

/** Long category names read better as horizontal bars; short ones and time or ordinal axes as columns. */
export function isHorizontal(result: ChartResult, x: string): boolean {
  if (x === 'week' || x === 'severity') return false
  return result.x.length > 6 || result.x.some((label) => label.length > 9)
}

export type PlotPoint = MatrixPoint & { x: number; y: number; rank: number; shownX: number }

/**
 * The matrix's points ranked by impact (1 is the highest, the number drawn in the dot) with their positions. Themes that
 * land on exactly the same spot are nudged sideways so each stays visible; the tooltip and table keep the true values.
 */
export function plotPoints(points: MatrixPoint[]): PlotPoint[] {
  const ranked = [...points].sort((a, b) => b.business_impact - a.business_impact || b.frequency - a.frequency || a.label.localeCompare(b.label))
  const seen = new Map<string, number>()
  return ranked.map((p, i) => {
    const y = Math.round(p.business_impact)
    const key = `${p.frequency}:${y}`
    const copies = seen.get(key) ?? 0
    seen.set(key, copies + 1)
    return { ...p, x: p.frequency, y, rank: i + 1, shownX: p.frequency + copies * 0.28 }
  })
}
