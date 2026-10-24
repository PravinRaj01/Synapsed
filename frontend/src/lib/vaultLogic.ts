import type { components } from '@/api/schema'

export type Source = components['schemas']['ResourceListItem']
export type SourceStatus = Source['status']
export type Ingested = components['schemas']['IngestedResource']

export const MAX_UPLOAD_MB = 50
export const MAX_MEDIA_MB = 24 // the speech-to-text service takes at most 25 MB in one file

export type FileKind = 'text' | 'json' | 'pdf' | 'image' | 'audio' | 'video' | 'table'

const EXTENSIONS: Record<FileKind, string[]> = {
  text: ['.txt', '.md', '.markdown'],
  json: ['.json'],
  pdf: ['.pdf'],
  image: ['.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp'],
  audio: ['.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac'],
  video: ['.mp4', '.mov', '.mkv', '.webm', '.avi'],
  table: ['.csv', '.xlsx'],
}

/** For the file picker's accept attribute. */
export const ACCEPT = Object.values(EXTENSIONS).flat().join(',')

export function fileKind(filename: string): FileKind | null {
  const dot = filename.lastIndexOf('.')
  const ext = dot === -1 ? '' : filename.slice(dot).toLowerCase()
  for (const [kind, list] of Object.entries(EXTENSIONS)) if (list.includes(ext)) return kind as FileKind
  return null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`
}

/** Why a file cannot be added, in words a person can act on; null when it is fine to send. */
export function checkFile(file: { name: string; size: number }): string | null {
  const kind = fileKind(file.name)
  if (!kind) {
    const dot = file.name.lastIndexOf('.')
    return `${dot === -1 ? 'This type of file is' : `${file.name.slice(dot)} files are`} not supported. Try text, PDF, image, audio, video, CSV or Excel.`
  }
  if (file.size === 0) return 'This file is empty.'
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `This file is ${formatBytes(file.size)}. The limit is ${MAX_UPLOAD_MB} MB.`
  if ((kind === 'audio' || kind === 'video') && file.size > MAX_MEDIA_MB * 1024 * 1024) {
    return `This recording is ${formatBytes(file.size)}. Speech-to-text takes up to ${MAX_MEDIA_MB} MB in one file, so compress it or split it into parts first.`
  }
  return null
}

export const isTable = (filename: string) => fileKind(filename) === 'table'

/** What to tell the user about one staged source: duplicates and names that may remain are worth a line. */
export function ingestNote(r: Ingested): { tone: 'neutral' | 'warning'; text: string } | null {
  if (r.duplicate) return { tone: 'neutral', text: 'Already in this campaign, so it was not added again.' }
  if (r.pii_notice) return { tone: 'warning', text: r.pii_notice }
  const hidden = Object.values(r.redactions ?? {}).reduce((a, b) => a + b, 0)
  return hidden > 0 ? { tone: 'neutral', text: `${hidden} personal ${hidden === 1 ? 'detail was' : 'details were'} hidden.` } : null
}

export type SourceFilter = { status: SourceStatus | 'all'; type: string; query: string }
export const NO_FILTER: SourceFilter = { status: 'all', type: 'all', query: '' }

export function filterSources(sources: Source[], f: SourceFilter): Source[] {
  const q = f.query.trim().toLowerCase()
  return sources.filter(
    (s) =>
      (f.status === 'all' || s.status === f.status) &&
      (f.type === 'all' || s.source_type === f.type) &&
      (!q || s.title.toLowerCase().includes(q) || (s.segment ?? '').toLowerCase().includes(q) || (s.summary ?? '').toLowerCase().includes(q)),
  )
}

export function countByStatus(sources: Source[]): Record<SourceStatus | 'all', number> {
  const c = { all: sources.length, staged: 0, approved: 0, rejected: 0 }
  for (const s of sources) c[s.status] += 1
  return c
}

/** Approved sources that have not been analysed yet. */
export const awaitingAnalysis = (sources: Source[]) => sources.filter((s) => s.status === 'approved' && !s.analyzed_at)

export const SOURCE_TYPE_LABEL: Record<string, string> = {
  transcript: 'Interview',
  ticket: 'Ticket',
  survey: 'Survey',
  audio: 'Audio',
  video: 'Video',
  ocr: 'Image',
  pdf: 'PDF',
  web_scrape: 'Web page',
}

// ---------------------------------------------------------------- analysis progress

export type TraceEvent = { node: string; status: 'running' | 'done' | 'error'; model_used?: string; tokens?: number; latency_ms?: number; output?: unknown }
export type RunSummary = {
  selected: number
  analysed: number
  insights: number
  themed: number
  new_themes: number
  roadmap_created: number
  roadmap_updated: number
  failed: number
  errors: { resource_id: string | null; stage: string; error: string }[]
  remaining: number
}

const STEP_LABEL: Record<string, string> = {
  select: 'Choosing sources',
  extract: 'Reading sources for pain points',
  embed: 'Saving what was found',
  cluster: 'Grouping into themes',
  decide: 'Settling close calls',
  name_themes: 'Naming themes',
  score: 'Scoring impact',
  roadmap: 'Drafting the roadmap',
}

/** The step a trace event belongs to, in plain words; null for bookkeeping events. */
export function stepLabel(node: string): string | null {
  return STEP_LABEL[node] ?? null
}

/** Combine the summaries of repeated batches into one. `remaining` comes from the last batch. */
export function totalSummaries(list: RunSummary[]): RunSummary {
  const sum = (pick: (s: RunSummary) => number) => list.reduce((n, s) => n + pick(s), 0)
  return {
    selected: sum((s) => s.selected),
    analysed: sum((s) => s.analysed),
    insights: sum((s) => s.insights),
    themed: sum((s) => s.themed),
    new_themes: sum((s) => s.new_themes),
    roadmap_created: sum((s) => s.roadmap_created),
    roadmap_updated: sum((s) => s.roadmap_updated),
    failed: sum((s) => s.failed),
    errors: list.flatMap((s) => s.errors).slice(0, 10),
    remaining: list.at(-1)?.remaining ?? 0,
  }
}

export const MAX_BATCHES = 25

/** Whether to ask for another batch: sources remain, the last batch got somewhere, and we are not looping forever. */
export function shouldContinue(last: RunSummary, batchesDone: number): boolean {
  return last.remaining > 0 && last.analysed > 0 && batchesDone < MAX_BATCHES
}

// ---------------------------------------------------------------- highlighting quotes in a source

export type Highlight = { start_offset: number; end_offset: number; color?: string | null; theme?: string | null; insight?: string }
export type Piece = { text: string; highlight?: Highlight }

/**
 * Cut a source's text into plain and highlighted pieces. Offsets are clamped to the text, empty ranges are skipped,
 * and where two quotes overlap the earlier one wins, so every character appears exactly once and in order.
 */
export function highlightPieces(text: string, highlights: Highlight[]): Piece[] {
  const sorted = highlights
    .map((h) => ({ ...h, start_offset: Math.max(0, h.start_offset), end_offset: Math.min(text.length, h.end_offset) }))
    .filter((h) => h.end_offset > h.start_offset)
    .sort((a, b) => a.start_offset - b.start_offset || b.end_offset - a.end_offset)
  const pieces: Piece[] = []
  let at = 0
  for (const h of sorted) {
    if (h.start_offset < at) continue
    if (h.start_offset > at) pieces.push({ text: text.slice(at, h.start_offset) })
    pieces.push({ text: text.slice(h.start_offset, h.end_offset), highlight: h })
    at = h.end_offset
  }
  if (at < text.length) pieces.push({ text: text.slice(at) })
  return pieces
}

export type Step = { node: string; label: string; status: TraceEvent['status'] }

/** Fold a trace event into the list of steps shown to the user: one row per step, and a step that is done stays done. */
export function applyTrace(steps: Step[], event: TraceEvent): Step[] {
  const label = stepLabel(event.node)
  if (!label) return steps
  const i = steps.findIndex((s) => s.node === event.node)
  if (i === -1) return [...steps, { node: event.node, label, status: event.status }]
  return steps.map((s, k) => (k === i ? { ...s, status: event.status === 'running' && s.status === 'done' ? s.status : event.status } : s))
}

// ---------------------------------------------------------------- what kind of source a file is

export type ChosenType = '' | 'transcript' | 'ticket' | 'survey'
export const CHOSEN_TYPES: { value: ChosenType; label: string }[] = [
  { value: '', label: 'Detect automatically' },
  { value: 'transcript', label: 'Interview or call' },
  { value: 'ticket', label: 'Support ticket' },
  { value: 'survey', label: 'Survey answers' },
]

/** The type to send for a file: only text, JSON and spreadsheets can be relabelled, and a spreadsheet only as a survey or ticket. */
export function sourceTypeFor(filename: string, chosen: ChosenType): ChosenType | null {
  if (!chosen) return null
  const kind = fileKind(filename)
  if (kind === 'text' || kind === 'json') return chosen
  if (kind === 'table') return chosen === 'ticket' || chosen === 'survey' ? chosen : null
  return null
}
