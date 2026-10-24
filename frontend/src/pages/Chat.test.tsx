import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }))
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

import { splitFootnotes, useChatStore, withFocus } from '@/lib/chat'
import { useCampaign } from '@/stores/campaign'
import Chat from './Chat'

const campaign = { id: 'c1', workspace_id: 'w1', name: 'Enterprise churn', goal: null, created_at: '2026-10-01T00:00:00Z', resources: 3, staged: 1, insights: 0, themes: 0 }
const source = (id: string, patch: Record<string, unknown> = {}) => ({
  id, title: `Source ${id}`, source_type: 'transcript', source_url: null, language: 'en', status: 'approved', pii_redacted: true, pii_note: null,
  summary: null, created_at: new Date().toISOString(), chars: 100, segment_id: null, segment: null, analyzed_at: null, chunk_count: 1, ...patch,
})
const TEXT = 'Maya: Every month I export four CSV files and stitch them together. The export also times out for big accounts. We love the invoice template.'
const detail = {
  id: 'a', campaign_id: 'c1', title: 'Source a', source_type: 'transcript', source_url: null, language: 'en', status: 'approved', content: TEXT, summary: null,
  pii_redacted: true, pii_note: null, segment_id: null, segment: null, analyzed_at: null, created_at: '2026-10-24T00:00:00Z',
  highlights: [{ citation_id: 'h1', insight_id: 'i1', start_offset: 6, end_offset: 41, text_snippet: 'Every month I export four CSV files', insight: 'Stitching files', theme_id: 't', theme: 'Exports', color: '#ec4899' }],
}
const quote = 'The export also times out for big accounts.'
const citation = (patch: Record<string, unknown> = {}) => ({
  n: 1, resource_id: 'a', resource_title: 'Source a', chunk_id: 'k1', start_offset: TEXT.indexOf(quote), end_offset: TEXT.indexOf(quote) + quote.length, snippet: quote, verified: true, ...patch,
})
const answer = (patch: Record<string, unknown> = {}) => ({
  answer: 'Exports time out for big accounts [1].', refused: false, reason: null, message: null, model: 'groq:gpt-oss', tokens: 412,
  retrieved: [{ n: 1 }, { n: 2 }, { n: 3 }], citations: [citation()], ...patch,
})

let sources: ReturnType<typeof source>[]

function setup(list = [source('a'), source('b'), source('c', { status: 'staged' })]) {
  sources = list
  http.GET.mockImplementation(async (path: string) => {
    if (path === '/api/v1/campaigns') return { data: [campaign] }
    if (path === '/api/v1/resources') return { data: sources }
    if (path === '/api/v1/resources/{resource_id}') return { data: detail }
    return { data: {} }
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Chat />
      </MemoryRouter>
    </QueryClientProvider>
  )
  const view = render(ui)
  return { user: userEvent.setup(), view, ui }
}

const chatCalls = () => http.POST.mock.calls.filter(([p]) => p === '/api/v1/chat')
async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(await screen.findByLabelText('Your question'), text)
  await user.click(screen.getByRole('button', { name: 'Send' }))
}

beforeEach(() => {
  http.GET.mockReset()
  http.POST.mockReset()
  useCampaign.setState({ campaignId: 'c1' })
  useChatStore.setState({ byCampaign: {} })
})

describe('reading an answer', () => {
  it('splits footnote markers from the text', () => {
    expect(splitFootnotes('Exports fail [1][2]. Also login [10].')).toEqual([
      { type: 'text', text: 'Exports fail ' }, { type: 'ref', n: 1 }, { type: 'ref', n: 2 }, { type: 'text', text: '. Also login ' }, { type: 'ref', n: 10 }, { type: 'text', text: '.' },
    ])
    expect(splitFootnotes('No markers here')).toEqual([{ type: 'text', text: 'No markers here' }])
    expect(splitFootnotes('[1]')).toEqual([{ type: 'ref', n: 1 }])
    expect(splitFootnotes('')).toEqual([])
    expect(splitFootnotes('array[x] and [1234]')).toEqual([{ type: 'text', text: 'array[x] and [1234]' }]) // only 1-3 digits are footnotes
  })

  it('lets the focused quote take the place of any highlight it overlaps', () => {
    const h = [{ start_offset: 0, end_offset: 10 }, { start_offset: 20, end_offset: 30 }, { start_offset: 50, end_offset: 60 }]
    expect(withFocus(h, null)).toBe(h)
    const out = withFocus(h, { start: 25, end: 55 })
    expect(out.filter((x) => x.focus)).toEqual([{ start_offset: 25, end_offset: 55, focus: true }])
    expect(out.filter((x) => !x.focus)).toEqual([{ start_offset: 0, end_offset: 10 }]) // both overlapping ones made way
  })
})

describe('the workspace', () => {
  it('lists only approved sources and says when there is nothing to ask', async () => {
    setup([source('c', { status: 'staged' })])
    expect(await screen.findByText('Nothing to ask yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Knowledge Vault' })).toBeInTheDocument()
  })

  it('shows the approved sources ticked, and a placeholder where the document will be', async () => {
    setup()
    expect(await screen.findByLabelText('Use Source a')).toBeChecked()
    expect(screen.getByLabelText('Use Source b')).toBeChecked()
    expect(screen.queryByLabelText('Use Source c')).not.toBeInTheDocument() // awaiting approval
    expect(screen.getByText('2 of 2 ticked')).toBeInTheDocument()
    expect(screen.getByText('Read the evidence')).toBeInTheDocument()
    expect(screen.getByText('All 2 approved sources')).toBeInTheDocument()
  })

  it('says so, and can retry, when sources cannot be loaded', async () => {
    http.GET.mockImplementation(async (path: string) => (path === '/api/v1/campaigns' ? { data: [campaign] } : { error: { detail: 'The server is waking up' } }))
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <Chat />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('The server is waking up')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(http.GET.mock.calls.filter(([p]) => p === '/api/v1/resources').length).toBeGreaterThan(1)
  })
})

describe('asking', () => {
  it('sends the question for the whole campaign, then shows a cited answer with a telemetry line', async () => {
    http.POST.mockResolvedValue({ data: answer() })
    const { user } = setup()
    await ask(user, 'What breaks for big accounts?')
    expect(await screen.findByRole('button', { name: 'Show source 1: Source a' })).toBeInTheDocument()
    expect(chatCalls()[0][1].body).toEqual({ campaign_id: 'c1', question: 'What breaks for big accounts?', history: [], source_ids: null })
    expect(screen.getByTestId('telemetry')).toHaveTextContent('groq:gpt-oss · 412 tokens · 3 passages read')
    expect(screen.getByText(/“The export also times out/)).toBeInTheDocument()
  })

  it('uses only the ticked sources, and asks for one to be ticked when none are', async () => {
    http.POST.mockResolvedValue({ data: answer() })
    const { user } = setup()
    await user.click(await screen.findByLabelText('Use Source b'))
    expect(screen.getByText('1 of 2 ticked')).toBeInTheDocument()
    await ask(user, 'What breaks?')
    await waitFor(() => expect(chatCalls()).toHaveLength(1))
    expect(chatCalls()[0][1].body.source_ids).toEqual(['a'])

    await user.click(screen.getByRole('button', { name: 'None' }))
    expect(screen.getByText('Tick at least one source to ask a question.')).toBeInTheDocument()
    expect(screen.getByLabelText('Your question')).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getByLabelText('Your question')).toBeEnabled()
  })

  it('shows a refusal plainly and keeps it out of the history sent next time', async () => {
    http.POST.mockResolvedValueOnce({ data: answer({ answer: null, refused: true, reason: 'not_in_sources', message: 'I could not find this in your approved sources.', citations: [], retrieved: [], model: null, tokens: 0 }) })
    const { user } = setup()
    await ask(user, 'What is the weather?')
    expect(await screen.findByText('Not in your sources')).toBeInTheDocument()
    expect(screen.getByText('I could not find this in your approved sources.')).toBeInTheDocument()
    http.POST.mockResolvedValueOnce({ data: answer() })
    await ask(user, 'And exports?')
    await waitFor(() => expect(chatCalls()).toHaveLength(2))
    expect(chatCalls()[1][1].body.history).toEqual([{ role: 'user', content: 'What is the weather?' }])
  })

  it('shows a rate limit message in the conversation', async () => {
    http.POST.mockResolvedValue({ error: { detail: 'You are asking too quickly. Try again in 30 seconds.', status: 429 } })
    const { user } = setup()
    await ask(user, 'Anything at all')
    expect(await screen.findByRole('alert')).toHaveTextContent('Try again in 30 seconds.')
  })

  it('keeps the conversation when you leave the page and come back, and clears it on request', async () => {
    http.POST.mockResolvedValue({ data: answer() })
    const { user, view, ui } = setup()
    await ask(user, 'What breaks for big accounts?')
    await screen.findByRole('button', { name: 'Show source 1: Source a' })
    view.unmount()
    render(ui)
    expect(await screen.findByText('What breaks for big accounts?')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: /Clear/ }))
    expect(screen.queryByText('What breaks for big accounts?')).not.toBeInTheDocument()
    expect(screen.getByText(/Try asking|Every answer comes with/)).toBeInTheDocument()
  })
})

describe('footnotes', () => {
  it('opens the source and flashes the exact quote, with the theme highlight still there', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll as unknown as typeof Element.prototype.scrollIntoView
    http.POST.mockResolvedValue({ data: answer() })
    const { user } = setup()
    await ask(user, 'What breaks for big accounts?')
    await user.click(await screen.findByRole('button', { name: 'Show source 1: Source a' }))
    const text = await screen.findByTestId('source-text')
    const flashed = within(text).getByText(quote)
    expect(flashed).toHaveAttribute('data-focus')
    expect(flashed.className).toContain('focus-flash')
    expect(within(text).getByText('Every month I export four CSV files')).toBeInTheDocument() // the other highlight remains
    expect(http.GET.mock.calls.find(([p]) => p === '/api/v1/resources/{resource_id}')?.[1].params.path.resource_id).toBe('a')
    await waitFor(() => expect(scroll).toHaveBeenCalledWith({ block: 'center', behavior: 'smooth' }))
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
  })

  it('opens the source without a flash when the exact words could not be located, and says so', async () => {
    http.POST.mockResolvedValue({ data: answer({ citations: [citation({ verified: false, start_offset: 0, end_offset: TEXT.length })] }) })
    const { user } = setup()
    await ask(user, 'What breaks for big accounts?')
    expect(await screen.findByText(/exact words could not be located/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show source 1: Source a' }))
    const text = await screen.findByTestId('source-text')
    expect(text.querySelector('[data-focus]')).toBeNull()
  })

  it('shows a marker as plain text when it points at a source that was not returned', async () => {
    http.POST.mockResolvedValue({ data: answer({ answer: 'Exports fail [1] and login fails [7].' }) })
    const { user } = setup()
    await ask(user, 'What breaks?')
    await screen.findByRole('button', { name: 'Show source 1: Source a' })
    expect(screen.queryByRole('button', { name: /Show source 7/ })).not.toBeInTheDocument()
    expect(screen.getByText('[7]')).toBeInTheDocument()
  })

  it('opens a source from the checklist without a flash', async () => {
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Source b' }))
    expect(await screen.findByTestId('source-text')).toBeInTheDocument()
  })
})

describe('on a phone', () => {
  it('shows one pane at a time and jumps to the document when a footnote is clicked', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} }))
    http.POST.mockResolvedValue({ data: answer() })
    const { user } = setup()
    expect(await screen.findByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByLabelText('Use Source a')).not.toBeInTheDocument()
    await ask(user, 'What breaks for big accounts?')
    await user.click(await screen.findByRole('button', { name: 'Show source 1: Source a' }))
    expect(await screen.findByTestId('source-text')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Document' })).toHaveAttribute('aria-selected', 'true')
    await user.click(screen.getByRole('tab', { name: /Sources/ }))
    expect(await screen.findByLabelText('Use Source a')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
