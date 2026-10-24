import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }))
vi.mock('@/lib/api', () => ({
  api: http,
  unwrap: async (call: Promise<{ data?: unknown; error?: { detail?: string; status?: number } }>) => {
    const r = await call
    if (r.error) {
      const { ApiError } = await import('@/lib/errors')
      throw new ApiError(r.error.status ?? 400, r.error.detail ?? 'failed')
    }
    return r.data
  },
}))
const stream = vi.hoisted(() => ({ postStream: vi.fn() }))
vi.mock('@/lib/sse', () => stream)
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

import { runForEach } from '@/lib/vault'
import { useCampaign } from '@/stores/campaign'
import Vault from './Vault'

const campaign = { id: 'c1', workspace_id: 'w1', name: 'Enterprise churn', goal: null, created_at: '2026-10-01T00:00:00Z', resources: 4, staged: 2, insights: 0, themes: 0 }
const source = (id: string, patch: Record<string, unknown> = {}) => ({
  id, title: `Source ${id}`, source_type: 'transcript', source_url: null, language: 'en', status: 'staged', pii_redacted: true, pii_note: null,
  summary: `Summary of ${id}`, created_at: new Date().toISOString(), chars: 1200, segment_id: null, segment: null, analyzed_at: null, chunk_count: 0, ...patch,
})
const segments = [{ id: 's1', campaign_id: 'c1', name: 'Enterprise', tier: 'enterprise', weight: 3, description: null, resources: 0, insights: 0 }]

let sources: ReturnType<typeof source>[]

function setup(list = sources) {
  sources = list
  http.GET.mockImplementation(async (path: string) => {
    if (path === '/api/v1/campaigns') return { data: [campaign] }
    if (path === '/api/v1/resources') return { data: sources }
    if (path === '/api/v1/campaigns/{campaign_id}/segments') return { data: segments }
    if (path === '/api/v1/campaigns/{campaign_id}/themes') return { data: [] }
    return { data: {} }
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Vault />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const posts = (path: string) => http.POST.mock.calls.filter(([p]) => p === path)

beforeEach(() => {
  http.GET.mockReset()
  http.POST.mockReset()
  http.PATCH.mockReset()
  stream.postStream.mockReset()
  Object.values(toast).forEach((f) => f.mockReset())
  useCampaign.setState({ campaignId: 'c1' })
})

describe('the source list', () => {
  const mixed = () => [
    source('a', { status: 'staged', title: 'Interview: finance lead' }),
    source('b', { status: 'approved', title: 'Support ticket 4821', source_type: 'ticket', segment: 'Free', analyzed_at: '2026-10-24T00:00:00Z' }),
    source('c', { status: 'approved', title: 'NPS comments', source_type: 'survey' }),
    source('d', { status: 'rejected', title: 'Spam page', source_type: 'web_scrape' }),
  ]

  it('says it is loading, then lists sources with their status in words', async () => {
    setup(mixed())
    expect(await screen.findByText('Interview: finance lead')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Sources (4)' })).toBeInTheDocument()
    const row = screen.getByText('Support ticket 4821').closest('tr')!
    expect(within(row).getByText('Approved')).toBeInTheDocument()
    expect(within(row).getByText('Analysed')).toBeInTheDocument()
    expect(within(row).getByText('Free')).toBeInTheDocument()
    expect(within(screen.getByText('NPS comments').closest('tr')!).getByText('Not analysed yet')).toBeInTheDocument()
  })

  it('filters by status and by a search, and offers to clear when nothing matches', async () => {
    const user = setup(mixed())
    await screen.findByText('Interview: finance lead')
    await user.click(screen.getByRole('tab', { name: /^Approved 2/ }))
    expect(screen.queryByText('Interview: finance lead')).not.toBeInTheDocument()
    expect(screen.getByText('NPS comments')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Search sources'), 'zzz')
    expect(screen.getByText(/No sources match/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByText('Interview: finance lead')).toBeInTheDocument()
  })

  it('shows a first-time empty state with a way to add sources', async () => {
    setup([])
    expect(await screen.findByRole('heading', { name: 'No sources yet' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Add sources' }).length).toBeGreaterThan(0)
  })

  it('says so, and can retry, when the list cannot be loaded', async () => {
    http.GET.mockImplementation(async (path: string) => (path === '/api/v1/campaigns' ? { data: [campaign] } : path === '/api/v1/resources' ? { error: { detail: 'The server is waking up' } } : { data: [] }))
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <Vault />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('The server is waking up')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(http.GET.mock.calls.filter(([p]) => p === '/api/v1/resources').length).toBeGreaterThan(1)
  })
})

describe('approving and rejecting', () => {
  it('approves one source from its row', async () => {
    http.POST.mockResolvedValue({ data: { id: 'a', status: 'approved', chunks: 2 } })
    const user = setup([source('a')])
    await user.click(await screen.findByRole('button', { name: 'Approve Source a' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Approved and ready to analyse.'))
    expect(http.POST.mock.calls[0][0]).toBe('/api/v1/resources/{resource_id}/approve')
    expect(http.POST.mock.calls[0][1].params.path.resource_id).toBe('a')
  })

  it('rejects one source, and shows the reason when the API refuses', async () => {
    http.POST.mockResolvedValue({ error: { detail: 'No staged resource with that id' } })
    const user = setup([source('a')])
    await user.click(await screen.findByRole('button', { name: 'Reject Source a' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('No staged resource with that id'))
  })

  it('approves every ticked source that is waiting, one after another, and counts them', async () => {
    http.POST.mockResolvedValue({ data: {} })
    const user = setup([source('a'), source('b'), source('c', { status: 'approved' })])
    await screen.findByText('Source a')
    await user.click(screen.getByLabelText('Select all sources'))
    expect(screen.getByText('3 selected')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Approve 2/ })) // the approved one is not touched
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Approved 2 sources.'))
    expect(posts('/api/v1/resources/{resource_id}/approve').map(([, o]) => o.params.path.resource_id)).toEqual(['a', 'b'])
  })

  it('stops at a rate limit and says how many were not done', async () => {
    http.POST.mockResolvedValueOnce({ data: {} }).mockResolvedValueOnce({ error: { detail: 'Too many approvals. Try again in 20 seconds.', status: 429 } })
    const user = setup([source('a'), source('b'), source('c')])
    await screen.findByText('Source a')
    await user.click(screen.getByLabelText('Select all sources'))
    await user.click(screen.getByRole('button', { name: /Approve 3/ }))
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(toast.error.mock.calls[0][0]).toBe('Too many approvals. Try again in 20 seconds. 2 sources were not done.')
    expect(toast.success).toHaveBeenCalledWith('Approved 1 source.')
    expect(http.POST).toHaveBeenCalledTimes(2) // c was never tried
  })

  it('sets a segment on the ticked sources and tells you when scores were recalculated', async () => {
    http.POST.mockResolvedValue({ data: { updated: 2, segment_id: 's1', rescored: true } })
    const user = setup([source('a'), source('b')])
    await screen.findByText('Source a')
    await user.click(screen.getByLabelText('Select all sources'))
    await user.selectOptions(screen.getByLabelText('Set segment for selected'), 's1')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Segment set on 2 sources. Impact scores were recalculated.'))
    expect(http.POST.mock.calls[0][1].body).toEqual({ resource_ids: ['a', 'b'], segment_id: 's1' })
  })
})

describe('runForEach', () => {
  it('records successes and failures and keeps going after an ordinary failure', async () => {
    const r = await runForEach(['a', 'b', 'c'], async (id) => { if (id === 'b') throw new Error('boom') })
    expect(r.done).toEqual(['a', 'c'])
    expect(r.failed).toEqual([{ id: 'b', message: 'boom' }])
    expect(r.stoppedEarly).toBe(false)
  })
})

describe('analysis', () => {
  const ready = () => [source('a', { status: 'approved' }), source('b', { status: 'approved' })]
  async function* events() {
    yield { event: 'run', data: { run_id: 'r1' } }
    yield { event: 'trace', data: { node: 'extract', status: 'running' } }
    yield { event: 'trace', data: { node: 'extract', status: 'done' } }
    yield { event: 'trace', data: { node: 'cluster', status: 'running' } }
    yield { event: 'summary', data: { selected: 2, analysed: 2, insights: 9, themed: 9, new_themes: 3, roadmap_created: 3, roadmap_updated: 0, failed: 0, errors: [], remaining: 0 } }
  }

  it('offers to analyse what is waiting, shows the steps, then what was found', async () => {
    stream.postStream.mockImplementation(events)
    const user = setup(ready())
    expect(await screen.findByText('2 approved sources are ready to be analysed.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Run analysis' }))
    expect(await screen.findByText('2 sources analysed')).toBeInTheDocument()
    expect(screen.getByText('9 pain points')).toBeInTheDocument()
    expect(screen.getByText('3 new themes')).toBeInTheDocument()
    expect(screen.getByText('Reading sources for pain points')).toBeInTheDocument()
    expect(screen.getByText('Grouping into themes')).toBeInTheDocument()
    expect(stream.postStream.mock.calls[0].slice(0, 2)).toEqual(['/api/v1/analyze', { campaign_id: 'c1' }])
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Found 9 pain points.'))
  })

  it('shows the server message when the run cannot start', async () => {
    stream.postStream.mockImplementation(() => ({ [Symbol.asyncIterator]: () => ({ next: () => Promise.reject(new Error('An analysis is already running for this campaign')) }) }))
    const user = setup(ready())
    await user.click(await screen.findByRole('button', { name: 'Run analysis' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('already running')
    expect(screen.getByRole('button', { name: 'Run analysis' })).toBeEnabled() // can try again
  })

  it('has nothing to run when everything approved is analysed', async () => {
    setup([source('a', { status: 'approved', analyzed_at: '2026-10-24T00:00:00Z' })])
    expect(await screen.findByText('Everything approved has been analysed.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run analysis' })).toBeDisabled()
  })
})

describe('adding sources', () => {
  it('refuses an unsupported file right away, with the reason, and offers nothing to send', async () => {
    setup([source('a')])
    const user = userEvent.setup({ applyAccept: false }) // a dropped file skips the picker's filter
    await user.click(await screen.findByRole('button', { name: 'Add sources' }))
    const input = await screen.findByLabelText('Choose files')
    await user.upload(input, new File(['PK'], 'archive.zip', { type: 'application/zip' }))
    expect(await screen.findByText(/\.zip files are not supported/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add file' })).toBeDisabled()
  })

  it('uploads a valid file through a presigned URL and then stages it', async () => {
    const put = vi.fn()
    class FakeXhr {
      upload = { onprogress: null as null | ((e: { loaded: number; total: number; lengthComputable: boolean }) => void) }
      onload: null | (() => void) = null
      onerror: null | (() => void) = null
      onabort: null | (() => void) = null
      status = 200
      open(m: string, u: string) { put('open', m, u) }
      send() { queueMicrotask(() => this.onload?.()) }
      abort() {}
    }
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    http.POST.mockImplementation(async (path: string) =>
      path === '/api/v1/uploads'
        ? { data: { key: 'c1/abc/notes.txt', url: 'https://store/put', expires_in: 900, max_bytes: 52428800 } }
        : { data: { duplicates: 0, resources: [{ id: 'n1', title: 'notes.txt', status: 'staged', duplicate: false, chars: 40, language: 'en', redactions: { email: 1 } }] } },
    )
    const user = setup([source('a')])
    await user.click(await screen.findByRole('button', { name: 'Add sources' }))
    await user.upload(await screen.findByLabelText('Choose files'), new File(['hello customers, exports are slow'], 'notes.txt', { type: 'text/plain' }))
    await user.selectOptions(screen.getAllByLabelText('Customer segment')[0], 's1') // the Files tab's; the other tabs stay mounted but hidden
    await user.selectOptions(screen.getAllByLabelText('What kind of source is it?')[0], 'ticket')
    await user.click(screen.getByRole('button', { name: 'Add file' }))
    expect(await screen.findByText('1 personal detail was hidden.')).toBeInTheDocument()
    expect(put).toHaveBeenCalledWith('open', 'PUT', 'https://store/put')
    expect(posts('/api/v1/uploads')[0][1].body).toMatchObject({ campaign_id: 'c1', filename: 'notes.txt' })
    expect(posts('/api/v1/ingest/stored')[0][1].body).toEqual({ campaign_id: 'c1', key: 'c1/abc/notes.txt', segment_id: 's1', source_type: 'ticket', text_column: null, segment_column: null })
    vi.unstubAllGlobals()
  })

  it('does not stage a file whose upload failed, and says what happened', async () => {
    class FailingXhr {
      upload = { onprogress: null }
      onload: null | (() => void) = null
      onerror: null | (() => void) = null
      onabort: null | (() => void) = null
      status = 0
      open() {}
      send() { queueMicrotask(() => this.onerror?.()) }
      abort() {}
    }
    vi.stubGlobal('XMLHttpRequest', FailingXhr)
    http.POST.mockResolvedValue({ data: { key: 'k', url: 'https://store/put', expires_in: 900, max_bytes: 1 } })
    const user = setup([source('a')])
    await user.click(await screen.findByRole('button', { name: 'Add sources' }))
    await user.upload(await screen.findByLabelText('Choose files'), new File(['hello customers'], 'notes.txt', { type: 'text/plain' }))
    await user.click(screen.getByRole('button', { name: 'Add file' }))
    expect(await screen.findByText(/The upload did not finish/)).toBeInTheDocument()
    expect(posts('/api/v1/ingest/stored')).toHaveLength(0)
    vi.unstubAllGlobals()
  })
})

describe('on a phone', () => {
  it('shows each source as a card with its actions, not a table that scrolls sideways', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} }))
    http.POST.mockResolvedValue({ data: {} })
    const user = setup([source('a', { segment: 'Free' }), source('b', { status: 'approved' })])
    expect(await screen.findByText('Source a')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByText(/Interview · Free/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve Source b' })).not.toBeInTheDocument() // already approved
    await user.click(screen.getByRole('button', { name: 'Approve Source a' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Approved and ready to analyse.'))
    vi.unstubAllGlobals()
  })
})
