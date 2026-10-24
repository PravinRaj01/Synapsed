import type { Tone } from '@/components/ui/Chip'
import type { ThemeRow } from './vault'

export type SortKey = 'impact' | 'mentions' | 'severity'

export const SORT_LABEL: Record<SortKey, string> = { impact: 'Business impact', mentions: 'Mentions', severity: 'Severity' }

/** Themes ordered by the chosen measure, highest first; ties fall back to impact, then name, so the order never jumps about. */
export function sortThemes(themes: ThemeRow[], key: SortKey): ThemeRow[] {
  const measure = (t: ThemeRow) => (key === 'impact' ? t.business_impact : key === 'mentions' ? t.frequency : (t.average_severity ?? 0))
  return [...themes].sort((a, b) => measure(b) - measure(a) || b.business_impact - a.business_impact || a.label.localeCompare(b.label))
}

export const NO_SEGMENT = 'none'

export type Heatmap = {
  columns: { key: string; name: string; total: number }[]
  rows: { theme: ThemeRow; cells: number[]; total: number }[]
  max: number
}

/**
 * Themes (rows) against customer segments (columns), each cell the number of pain points. Columns run from the
 * segment with the most pain points to the least, with "No segment" last; rows keep the order they come in.
 */
export function buildHeatmap(themes: ThemeRow[]): Heatmap {
  const totals = new Map<string, { name: string; total: number }>()
  for (const t of themes) {
    for (const s of t.segments) {
      const key = s.segment_id ?? NO_SEGMENT
      const entry = totals.get(key) ?? { name: s.segment_id ? s.name : 'No segment', total: 0 }
      entry.total += s.insights
      totals.set(key, entry)
    }
  }
  const columns = [...totals.entries()]
    .map(([key, v]) => ({ key, name: v.name, total: v.total }))
    .sort((a, b) => (a.key === NO_SEGMENT ? 1 : b.key === NO_SEGMENT ? -1 : b.total - a.total || a.name.localeCompare(b.name)))
  const rows = themes.map((theme) => {
    const cells = columns.map((c) => theme.segments.filter((s) => (s.segment_id ?? NO_SEGMENT) === c.key).reduce((n, s) => n + s.insights, 0))
    return { theme, cells, total: cells.reduce((a, b) => a + b, 0) }
  })
  return { columns, rows, max: Math.max(0, ...rows.flatMap((r) => r.cells)) }
}

/** A segment name short enough for a narrow column: "No segment" is "None", a long name keeps its first four letters. */
export function shortSegment(name: string): string {
  if (name === 'No segment') return 'None'
  return name.length > 5 ? `${name.slice(0, 4)}.` : name
}

/** How strongly to colour a cell, 0 to 1. Empty cells get none; the rest start visible and grow with the count. */
export function cellStrength(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0
  return 0.15 + 0.85 * Math.sqrt(count / max)
}

// ---------------------------------------------------------------- export

/** A CSV cell. Quoted when needed, and neutralised when it starts like a spreadsheet formula (= + - @), because customer words end up in these files. */
export function csvCell(value: string | number | null | undefined): string {
  let text = value == null ? '' : String(value)
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

const topSegments = (t: ThemeRow) => t.segments.map((s) => `${s.name} (${s.insights})`).join('; ')
const kind = (t: ThemeRow, k: 'pain_point' | 'feature_request') => t.kinds[k] ?? 0

export function reportCsv(themes: ThemeRow[]): string {
  const header = ['Rank', 'Theme', 'Description', 'Business impact', 'Mentions', 'Sources', 'Average severity', 'Sentiment', 'Pain points', 'Feature requests', 'Segments']
  const rows = themes.map((t, i) => [i + 1, t.label, t.description, Math.round(t.business_impact), t.frequency, t.sources, t.average_severity, t.sentiment, kind(t, 'pain_point'), kind(t, 'feature_request'), topSegments(t)])
  return [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n'
}

const mdCell = (text: string | null | undefined) => (text ?? '').replace(/\|/g, '\\|').replace(/\s+/g, ' ').trim()

export function reportMarkdown(campaign: string, themes: ThemeRow[], date = new Date()): string {
  const lines = [`# Problem space report: ${campaign}`, '', `Generated ${date.toISOString().slice(0, 10)}. Business impact is customer weight × severity, scaled so the strongest theme is 100.`, '']
  if (themes.length === 0) return lines.concat('No themes yet.', '').join('\n')
  lines.push('| # | Theme | Impact | Mentions | Sources | Severity | Sentiment |', '| --- | --- | ---: | ---: | ---: | ---: | --- |')
  themes.forEach((t, i) => lines.push(`| ${i + 1} | ${mdCell(t.label)} | ${Math.round(t.business_impact)} | ${t.frequency} | ${t.sources} | ${t.average_severity ?? '–'} | ${t.sentiment} |`))
  for (const [i, t] of themes.entries()) {
    lines.push('', `## ${i + 1}. ${mdCell(t.label)}`, '')
    if (t.description) lines.push(t.description, '')
    lines.push(`- Business impact ${Math.round(t.business_impact)} of 100, ${t.frequency} ${t.frequency === 1 ? 'mention' : 'mentions'} across ${t.sources} ${t.sources === 1 ? 'source' : 'sources'}`)
    lines.push(`- ${kind(t, 'pain_point')} pain ${kind(t, 'pain_point') === 1 ? 'point' : 'points'}, ${kind(t, 'feature_request')} feature ${kind(t, 'feature_request') === 1 ? 'request' : 'requests'}; overall tone ${t.sentiment}`)
    if (t.segments.length) lines.push(`- Segments: ${topSegments(t)}`)
    if (t.use_cases.length) lines.push(`- Use cases: ${t.use_cases.map((u) => `${u.use_case} (${u.insights})`).join('; ')}`)
  }
  return lines.join('\n') + '\n'
}

/** A file name from a campaign name: letters and digits, dashes between, never empty. */
export function fileSlug(name: string, fallback = 'report'): string {
  return name.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || fallback
}

/** How a theme's overall tone reads, in words and in a colour (the words are the primary cue). */
export const SENTIMENT: Record<ThemeRow['sentiment'], { label: string; tone: Tone }> = {
  positive: { label: 'Positive', tone: 'positive' },
  negative: { label: 'Negative', tone: 'negative' },
  neutral: { label: 'Neutral', tone: 'neutral' },
  mixed: { label: 'Mixed', tone: 'warning' },
}
