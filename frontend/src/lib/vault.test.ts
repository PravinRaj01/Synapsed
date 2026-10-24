import { describe, expect, it, vi } from 'vitest'
import { noteFile, putFile, uploadSource } from './upload'
import {
  applyTrace,
  awaitingAnalysis,
  checkFile,
  countByStatus,
  fileKind,
  filterSources,
  highlightPieces,
  formatBytes,
  ingestNote,
  NO_FILTER,
  shouldContinue,
  sourceTypeFor,
  stepLabel,
  totalSummaries,
  type RunSummary,
  type Source,
} from './vaultLogic'

const MB = 1024 * 1024
const src = (patch: Partial<Source> = {}): Source => ({
  id: 'r1', title: 'Interview: finance lead', source_type: 'transcript', source_url: null, language: 'en', status: 'staged',
  pii_redacted: true, pii_note: null, summary: 'Month-end takes three days', created_at: '2026-10-24T00:00:00Z', chars: 900,
  segment_id: null, segment: null, analyzed_at: null, chunk_count: 0, ...patch,
})
const run = (patch: Partial<RunSummary> = {}): RunSummary => ({ selected: 5, analysed: 5, insights: 12, themed: 12, new_themes: 2, roadmap_created: 2, roadmap_updated: 0, failed: 0, errors: [], remaining: 0, ...patch })

describe('files', () => {
  it('recognises supported types whatever the case', () => {
    expect(fileKind('Interview.TXT')).toBe('text')
    expect(fileKind('notes.md')).toBe('text')
    expect(fileKind('survey.xlsx')).toBe('table')
    expect(fileKind('call.M4A')).toBe('audio')
    expect(fileKind('scan.jpeg')).toBe('image')
    expect(fileKind('archive.zip')).toBeNull()
    expect(fileKind('README')).toBeNull()
  })

  it('accepts a normal file and explains each refusal', () => {
    expect(checkFile({ name: 'a.txt', size: 1200 })).toBeNull()
    expect(checkFile({ name: 'a.zip', size: 10 })).toMatch(/\.zip files are not supported/)
    expect(checkFile({ name: 'noext', size: 10 })).toBe('This type of file is not supported. Try text, PDF, image, audio, video, CSV or Excel.')
    expect(checkFile({ name: 'a.txt', size: 0 })).toBe('This file is empty.')
    expect(checkFile({ name: 'a.pdf', size: 51 * MB })).toBe('This file is 51 MB. The limit is 50 MB.')
  })

  it('keeps recordings under what speech-to-text accepts and says what to do', () => {
    expect(checkFile({ name: 'call.mp3', size: 24 * MB })).toBeNull()
    expect(checkFile({ name: 'call.mp3', size: 30 * MB })).toMatch(/up to 24 MB.*compress it or split it/)
    expect(checkFile({ name: 'big.csv', size: 30 * MB })).toBeNull() // only recordings have the smaller limit
  })

  it('formats sizes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(300 * 1024)).toBe('300 KB')
    expect(formatBytes(5 * MB)).toBe('5.0 MB')
    expect(formatBytes(30 * MB)).toBe('30 MB')
  })

  it('names a pasted note safely', () => {
    expect(noteFile('hello', 'Call: Acme / Q4?').name).toBe('Call Acme Q4.txt')
    expect(noteFile('hello', '   ').name).toBe('Pasted note.txt')
    expect(noteFile('hello', 'x'.repeat(200)).name.length).toBeLessThanOrEqual(84)
  })
})

describe('what to say about a staged source', () => {
  const base = { id: 'a', title: 't', status: 'staged', duplicate: false, chars: 10, language: 'en', redactions: {} }
  it('flags duplicates, possible names and hidden details', () => {
    expect(ingestNote({ ...base, duplicate: true })?.text).toMatch(/Already in this campaign/)
    expect(ingestNote({ ...base, pii_notice: 'Names may remain in Malay text.' })).toEqual({ tone: 'warning', text: 'Names may remain in Malay text.' })
    expect(ingestNote({ ...base, redactions: { email: 1 } })?.text).toBe('1 personal detail was hidden.')
    expect(ingestNote({ ...base, redactions: { email: 2, phone: 1 } })?.text).toBe('3 personal details were hidden.')
    expect(ingestNote(base)).toBeNull()
  })
})

describe('source list', () => {
  const list = [
    src({ id: '1', status: 'staged' }),
    src({ id: '2', status: 'approved', title: 'Support ticket 4821', source_type: 'ticket', segment: 'Free' }),
    src({ id: '3', status: 'approved', analyzed_at: '2026-10-24T01:00:00Z', source_type: 'survey' }),
    src({ id: '4', status: 'rejected' }),
  ]
  it('filters by status, type and a search over title, segment and summary', () => {
    expect(filterSources(list, NO_FILTER)).toHaveLength(4)
    expect(filterSources(list, { ...NO_FILTER, status: 'approved' }).map((s) => s.id)).toEqual(['2', '3'])
    expect(filterSources(list, { ...NO_FILTER, type: 'ticket' }).map((s) => s.id)).toEqual(['2'])
    expect(filterSources(list, { ...NO_FILTER, query: ' TICKET 48' }).map((s) => s.id)).toEqual(['2'])
    expect(filterSources(list, { ...NO_FILTER, query: 'free' }).map((s) => s.id)).toEqual(['2'])
    expect(filterSources(list, { ...NO_FILTER, query: 'three days' })).toHaveLength(4)
    expect(filterSources(list, { status: 'approved', type: 'survey', query: 'zzz' })).toEqual([])
  })
  it('counts by status and finds what waits for analysis', () => {
    expect(countByStatus(list)).toEqual({ all: 4, staged: 1, approved: 2, rejected: 1 })
    expect(awaitingAnalysis(list).map((s) => s.id)).toEqual(['2'])
  })
})

describe('analysis progress', () => {
  it('names steps in plain words and ignores bookkeeping events', () => {
    expect(stepLabel('extract')).toBe('Reading sources for pain points')
    expect(stepLabel('run')).toBeNull()
  })
  it('adds batches together and takes remaining from the last one', () => {
    const total = totalSummaries([run({ analysed: 5, insights: 12, remaining: 3 }), run({ analysed: 3, insights: 7, failed: 1, remaining: 0, errors: [{ resource_id: 'x', stage: 'embed', error: 'boom' }] })])
    expect(total).toMatchObject({ analysed: 8, insights: 19, failed: 1, remaining: 0 })
    expect(total.errors).toHaveLength(1)
    expect(totalSummaries([]).remaining).toBe(0)
  })
  it('asks for another batch only while sources remain and the last batch made progress', () => {
    expect(shouldContinue(run({ remaining: 3 }), 1)).toBe(true)
    expect(shouldContinue(run({ remaining: 0 }), 1)).toBe(false)
    expect(shouldContinue(run({ remaining: 3, analysed: 0, failed: 3 }), 1)).toBe(false) // stuck: do not loop
    expect(shouldContinue(run({ remaining: 3 }), 25)).toBe(false)
  })
})

describe('uploadSource', () => {
  const file = new File(['hello world'], 'call notes.txt', { type: 'text/plain' })
  const staged = { resources: [{ id: 'r', title: 't', status: 'staged', duplicate: false, chars: 11, language: 'en', redactions: {} }], duplicates: 0 }

  it('gets a ticket, sends the bytes, then stages the file with the chosen segment and columns', async () => {
    const calls: string[] = []
    const deps = {
      ticket: vi.fn(async () => (calls.push('ticket'), { key: 'c1/abc/call notes.txt', url: 'https://store/put' })),
      put: vi.fn(async (_u: string, _f: Blob, onProgress: (n: number) => void) => (calls.push('put'), onProgress(0.5), onProgress(1))),
      stage: vi.fn(async () => (calls.push('stage'), staged)),
    }
    const seen: number[] = []
    const result = await uploadSource(file, { campaignId: 'c1', segmentId: 's1', sourceType: 'ticket', textColumn: ' Feedback ', segmentColumn: '' }, (f) => seen.push(f), undefined, deps)
    expect(calls).toEqual(['ticket', 'put', 'stage'])
    expect(deps.ticket).toHaveBeenCalledWith({ campaign_id: 'c1', filename: 'call notes.txt', size: 11 })
    expect(deps.put.mock.calls[0][0]).toBe('https://store/put')
    expect(deps.stage).toHaveBeenCalledWith({ campaign_id: 'c1', key: 'c1/abc/call notes.txt', segment_id: 's1', source_type: 'ticket', text_column: 'Feedback', segment_column: null })
    expect(result).toBe(staged)
    expect(seen.at(-1)).toBe(1)
    expect(seen.every((n, i) => i === 0 || n >= seen[i - 1])).toBe(true) // never goes backwards
    expect(Math.max(...seen.slice(0, -1))).toBeLessThanOrEqual(0.9) // the last tenth is the API reading the file
  })

  it('stops at the first failure and does not stage a file that did not upload', async () => {
    const deps = { ticket: async () => ({ key: 'k', url: 'u' }), put: vi.fn(async () => { throw new Error('The upload did not finish.') }), stage: vi.fn() }
    await expect(uploadSource(file, { campaignId: 'c1' }, () => {}, undefined, deps)).rejects.toThrow('The upload did not finish.')
    expect(deps.stage).not.toHaveBeenCalled()
  })

  it('does not upload when the ticket is refused', async () => {
    const deps = { ticket: vi.fn(async () => { throw new Error('File is larger than 50 MB') }), put: vi.fn(), stage: vi.fn() }
    await expect(uploadSource(file, { campaignId: 'c1' }, () => {}, undefined, deps)).rejects.toThrow('larger than 50 MB')
    expect(deps.put).not.toHaveBeenCalled()
  })
})

describe('putFile', () => {
  class FakeXhr {
    static last: FakeXhr
    upload: { onprogress: ((e: { loaded: number; total: number; lengthComputable: boolean }) => void) | null } = { onprogress: null }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    onabort: (() => void) | null = null
    status = 0
    method = ''
    url = ''
    body: Blob | null = null
    aborted = false
    constructor() { FakeXhr.last = this }
    open(m: string, u: string) { this.method = m; this.url = u }
    send(b: Blob) { this.body = b }
    abort() { this.aborted = true; this.onabort?.() }
  }

  it('PUTs the file, reports progress and resolves on success', async () => {
    const progress: number[] = []
    const p = putFile('https://store/put', new Blob(['x']), (f) => progress.push(f), undefined, FakeXhr)
    const x = FakeXhr.last
    expect([x.method, x.url]).toEqual(['PUT', 'https://store/put'])
    x.upload.onprogress?.({ loaded: 25, total: 100, lengthComputable: true })
    x.upload.onprogress?.({ loaded: 5, total: 0, lengthComputable: false }) // ignored
    x.status = 200
    x.onload?.()
    await p
    expect(progress).toEqual([0.25, 1])
  })
  it('says what went wrong for a refusal, a network failure and a cancel', async () => {
    const refused = putFile('u', new Blob(['x']), () => {}, undefined, FakeXhr)
    FakeXhr.last.status = 403
    FakeXhr.last.onload?.()
    await expect(refused).rejects.toThrow('refused the upload')

    const dropped = putFile('u', new Blob(['x']), () => {}, undefined, FakeXhr)
    FakeXhr.last.onerror?.()
    await expect(dropped).rejects.toThrow('did not finish')

    const controller = new AbortController()
    const cancelled = putFile('u', new Blob(['x']), () => {}, controller.signal, FakeXhr)
    controller.abort()
    await expect(cancelled).rejects.toThrow('cancelled')
    expect(FakeXhr.last.aborted).toBe(true)
  })
})

describe('highlightPieces', () => {
  const text = 'Hello big world, how are you'
  const join = (p: { text: string }[]) => p.map((x) => x.text).join('')
  it('keeps every character once and in order', () => {
    const pieces = highlightPieces(text, [{ start_offset: 6, end_offset: 9 }, { start_offset: 17, end_offset: 20 }])
    expect(join(pieces)).toBe(text)
    expect(pieces.filter((p) => p.highlight).map((p) => p.text)).toEqual(['big', 'how'])
  })
  it('returns the whole text as one plain piece with no highlights', () => {
    expect(highlightPieces(text, [])).toEqual([{ text }])
  })
  it('lets the earlier of two overlapping quotes win and clamps to the text', () => {
    const pieces = highlightPieces(text, [{ start_offset: 8, end_offset: 14, theme: 'later' }, { start_offset: 6, end_offset: 11, theme: 'earlier' }, { start_offset: 25, end_offset: 999 }])
    expect(join(pieces)).toBe(text)
    expect(pieces.filter((p) => p.highlight).map((p) => [p.text, p.highlight?.theme])).toEqual([['big w', 'earlier'], ['you', undefined]])
  })
  it('skips empty and inverted ranges', () => {
    expect(highlightPieces(text, [{ start_offset: 4, end_offset: 4 }, { start_offset: 9, end_offset: 2 }, { start_offset: -5, end_offset: 0 }])).toEqual([{ text }])
  })
  it('handles a highlight at the very start and end', () => {
    const pieces = highlightPieces('abc', [{ start_offset: 0, end_offset: 3 }])
    expect(pieces).toHaveLength(1)
    expect(pieces[0].highlight).toBeDefined()
  })
})

describe('applyTrace', () => {
  it('adds a row for each named step and ignores bookkeeping events', () => {
    let steps = applyTrace([], { node: 'run', status: 'running' })
    expect(steps).toEqual([])
    steps = applyTrace(steps, { node: 'extract', status: 'running' })
    steps = applyTrace(steps, { node: 'embed', status: 'running' })
    expect(steps.map((s) => [s.label, s.status])).toEqual([['Reading sources for pain points', 'running'], ['Saving what was found', 'running']])
  })
  it('updates a step in place, and a step that is done stays done when it reports running again', () => {
    let steps = applyTrace([], { node: 'extract', status: 'running' })
    steps = applyTrace(steps, { node: 'extract', status: 'done' })
    steps = applyTrace(steps, { node: 'extract', status: 'running' })
    expect(steps).toHaveLength(1)
    expect(steps[0].status).toBe('done')
    steps = applyTrace(steps, { node: 'extract', status: 'error' })
    expect(steps[0].status).toBe('error')
  })
})

describe('sourceTypeFor', () => {
  it('sends the chosen type only where the file can take it', () => {
    expect(sourceTypeFor('notes.txt', 'ticket')).toBe('ticket')
    expect(sourceTypeFor('chat.json', 'survey')).toBe('survey')
    expect(sourceTypeFor('answers.csv', 'survey')).toBe('survey')
    expect(sourceTypeFor('answers.csv', 'transcript')).toBeNull() // a spreadsheet is never an interview
    expect(sourceTypeFor('scan.pdf', 'ticket')).toBeNull()
    expect(sourceTypeFor('call.mp3', 'transcript')).toBeNull()
    expect(sourceTypeFor('notes.txt', '')).toBeNull()
  })
})
