import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }))
vi.mock('@/lib/api', () => ({
  api: http,
  unwrap: async (call: Promise<{ data?: unknown; error?: { detail?: string } }>) => {
    const r = await call
    if (r.error) throw new Error(r.error.detail ?? 'failed')
    return r.data
  },
}))
const auth = vi.hoisted(() => ({ getSession: vi.fn() }))
vi.mock('@/lib/auth', () => ({ authClient: auth, getAccessToken: vi.fn(), clearAccessToken: vi.fn() }))
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

import { useCampaign } from '@/stores/campaign'
import Dashboard from './Dashboard'

const workspace = { id: 'w1', name: 'Acme', company: 'Acme', industry: 'SaaS', role: 'owner', campaigns: 2 }
const campaign = (id: string, name: string) => ({ id, workspace_id: 'w1', name, goal: null, created_at: '2026-10-01T00:00:00Z', resources: 10, staged: 0, insights: 37, themes: 6 })

const overview = {
  resources: { total: 10, staged: 2, approved: 8, rejected: 0, waiting_for_analysis: 3 },
  insights: 37,
  themes: 6,
  roadmap_items: 5,
  segments: 3,
  sentiment: { positive: 6, neutral: 5, negative: 26 },
  trend: { days: 7, resources: { current: 6, previous: 5 }, insights: { current: 17, previous: 20 }, themes: { current: 6, previous: 0 } },
  top_themes: [
    { id: 't1', label: 'Report exports time out', color: '#ec4899', frequency: 7, business_impact: 100 },
    { id: 't2', label: 'Bank matching is unreliable', color: '#6366f1', frequency: 7, business_impact: 93.1 },
  ],
  recent_resources: [
    { id: 'r1', title: 'Interview: finance lead', source_type: 'transcript', status: 'approved', language: 'en', created_at: new Date().toISOString() },
    { id: 'r2', title: 'Tiket sokongan', source_type: 'ticket', status: 'staged', language: 'ms', created_at: new Date().toISOString() },
  ],
  last_run: null,
  telemetry: { calls: 12, tokens: 3400, fallbacks: 1, by_model: [] },
}
const emptyOverview = { ...overview, resources: { total: 0, staged: 0, approved: 0, rejected: 0, waiting_for_analysis: 0 }, insights: 0, themes: 0, roadmap_items: 0, top_themes: [], recent_resources: [], sentiment: {} }

type World = { workspaces?: unknown; campaigns?: unknown; overview?: unknown }

function render_(world: World = {}) {
  const data = { workspaces: [workspace], campaigns: [campaign('c1', 'Enterprise churn'), campaign('c2', 'Onboarding')], overview, ...world }
  http.GET.mockImplementation(async (path: string) => {
    if (path === '/api/v1/workspaces') return data.workspaces instanceof Error ? { error: { detail: data.workspaces.message } } : { data: data.workspaces }
    if (path === '/api/v1/campaigns') return { data: data.campaigns }
    return data.overview instanceof Error ? { error: { detail: data.overview.message } } : { data: data.overview }
  })
  auth.getSession.mockResolvedValue({ data: { user: { id: 'u1', name: 'Maya Tan', email: 'maya@acme.io' } } })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/onboarding" element={<p>Onboarding page</p>} />
          <Route path="/vault" element={<p>Vault page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

beforeEach(() => {
  http.GET.mockReset()
  http.POST.mockReset()
  Object.values(toast).forEach((f) => f.mockReset())
  useCampaign.setState({ campaignId: null })
})

describe('dashboard', () => {
  it('sends a user with no workspace to set one up', async () => {
    render_({ workspaces: [], campaigns: [] })
    expect(await screen.findByText('Onboarding page')).toBeInTheDocument()
  })

  it('shows a loading state, not the empty state, while the data is on its way', async () => {
    http.GET.mockReturnValue(new Promise(() => {}))
    auth.getSession.mockResolvedValue({ data: null })
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('status', { name: 'Loading your dashboard' })).toBeInTheDocument()
    expect(screen.queryByText(/set up a campaign/)).not.toBeInTheDocument()
  })

  it('greets the user and shows the numbers, with change against the previous week', async () => {
    render_()
    expect(await screen.findByRole('heading', { name: /^Good (morning|afternoon|evening), Maya$/ })).toBeInTheDocument()
    expect(await screen.findByText('Insights found')).toBeInTheDocument()
    expect(await screen.findByText('37')).toBeInTheDocument() // counts up to the value
    expect(screen.getByText('15%')).toBeInTheDocument() // 17 vs 20 insights
    expect(screen.getByText('20%')).toBeInTheDocument() // 6 vs 5 sources
    expect(screen.getByText('Sources indexed')).toBeInTheDocument()
    expect(screen.getByText('3 customer segments')).toBeInTheDocument()
    expect(http.GET.mock.calls.find(([p]) => p === '/api/v1/campaigns/{campaign_id}/overview')?.[1].params.path.campaign_id).toBe('c1')
  })

  it('shows themes ranked with their impact and mentions', async () => {
    render_()
    expect(await screen.findByText('Report exports time out')).toBeInTheDocument()
    expect(screen.getByText('Bank matching is unreliable')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Impact 100 out of 100' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Impact 93 out of 100' })).toBeInTheDocument()
  })

  it('shows sentiment shares that add up, with names and counts', async () => {
    render_()
    const bar = await screen.findByRole('img', { name: 'Positive 16%, Neutral 14%, Negative 70%' })
    expect(bar).toBeInTheDocument()
    expect(screen.getByText('Negative')).toBeInTheDocument()
    expect(screen.getByText('26')).toBeInTheDocument()
  })

  it('suggests what to do next and links to the right page', async () => {
    const user = render_()
    expect(await screen.findByText('Review 2 sources waiting for approval')).toBeInTheDocument()
    expect(screen.getByText('Analyse 3 approved sources')).toBeInTheDocument()
    await user.click(screen.getByText('Review 2 sources waiting for approval'))
    expect(await screen.findByText('Vault page')).toBeInTheDocument()
  })

  it('lists recent sources with their status in words', async () => {
    render_()
    const row = (await screen.findByText('Tiket sokongan')).closest('li')!
    expect(within(row).getByText('Awaiting approval')).toBeInTheDocument()
    expect(within(row).getByText(/MS/)).toBeInTheDocument()
    expect(within(row.parentElement!.firstElementChild as HTMLElement).getByText('Approved')).toBeInTheDocument()
  })

  it('follows the campaign chosen in the scope menu', async () => {
    useCampaign.setState({ campaignId: 'c2' })
    render_()
    await screen.findByText('Insights found')
    expect(http.GET.mock.calls.some(([p, o]) => p.endsWith('/overview') && o.params.path.campaign_id === 'c2')).toBe(true)
  })

  it('offers the demo for an empty campaign and loads it', async () => {
    http.POST.mockResolvedValue({ data: { resources: 10, insights: 37, themes: 6, roadmap_items: 5 } })
    const user = render_({ overview: emptyOverview })
    await user.click(await screen.findByRole('button', { name: /Load the demo sandbox/ }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Demo sandbox loaded.'))
    expect(http.POST.mock.calls[0][0]).toBe('/api/v1/campaigns/{campaign_id}/demo')
    expect(http.POST.mock.calls[0][1].params.path.campaign_id).toBe('c1')
  })

  it('says so, and can retry, when the data cannot be loaded', async () => {
    const user = render_({ overview: new Error('The server is waking up') })
    expect(await screen.findByText('We could not load your dashboard')).toBeInTheDocument()
    expect(screen.getByText('The server is waking up')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(http.GET.mock.calls.filter(([p]) => p.endsWith('/overview')).length).toBeGreaterThan(1)
  })

  it('offers to create a campaign when there is a workspace but no campaign', async () => {
    render_({ campaigns: [] })
    expect(await screen.findByText("Let's set up a campaign")).toBeInTheDocument()
  })
})

describe('quick chat', () => {
  const answer = {
    refused: false, reason: null, message: null, model: 'groq:x', tokens: 100, retrieved: [],
    answer: 'Exports time out for large accounts [1].',
    citations: [{ n: 1, resource_id: 'r1', resource_title: 'Interview: finance lead', chunk_id: 'k1', start_offset: 0, end_offset: 10, snippet: 'it times out for our biggest entity', verified: true }],
  }

  async function openChat(reply: unknown) {
    http.POST.mockResolvedValue(reply)
    const user = render_()
    await user.click(await screen.findByRole('button', { name: /Ask your data/ }))
    return user
  }

  it('answers with the quote behind each footnote', async () => {
    const user = await openChat({ data: answer })
    await user.type(await screen.findByLabelText('Your question'), 'What breaks for big accounts?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Exports time out for large accounts [1].')).toBeInTheDocument()
    expect(screen.getByText('[1] Interview: finance lead')).toBeInTheDocument()
    expect(screen.getByText(/it times out for our biggest entity/)).toBeInTheDocument()
    const call = http.POST.mock.calls[0]
    expect(call[0]).toBe('/api/v1/chat')
    expect(call[1].body).toEqual({ campaign_id: 'c1', question: 'What breaks for big accounts?', history: [] })
  })

  it('sends a suggestion as a question and sends earlier turns as history', async () => {
    const user = await openChat({ data: answer })
    await user.click(await screen.findByRole('button', { name: 'What are customers struggling with most?' }))
    await screen.findByText('Exports time out for large accounts [1].')
    await user.type(screen.getByLabelText('Your question'), 'And for free users?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(http.POST).toHaveBeenCalledTimes(2))
    expect(http.POST.mock.calls[1][1].body.history).toEqual([
      { role: 'user', content: 'What are customers struggling with most?' },
      { role: 'assistant', content: 'Exports time out for large accounts [1].' },
    ])
  })

  it('shows a refusal plainly, with no invented citations, and keeps it out of the history', async () => {
    const user = await openChat({ data: { ...answer, answer: null, refused: true, reason: 'not_in_sources', message: 'I could not find that in your sources.', citations: [] } })
    await user.type(await screen.findByLabelText('Your question'), 'What is the weather in Paris?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('I could not find that in your sources.')).toBeInTheDocument()
    expect(screen.getByText('Not in your sources')).toBeInTheDocument()
    http.POST.mockResolvedValue({ data: answer })
    await user.type(screen.getByLabelText('Your question'), 'What about exports?')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(http.POST).toHaveBeenCalledTimes(2))
    expect(http.POST.mock.calls[1][1].body.history).toEqual([{ role: 'user', content: 'What is the weather in Paris?' }])
  })

  it('shows the error message, such as a rate limit, in the conversation', async () => {
    const user = await openChat({ error: { detail: 'You are asking too quickly. Try again in 30 seconds.' } })
    await user.type(await screen.findByLabelText('Your question'), 'Anything at all')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Try again in 30 seconds.')
  })

  it('does not send a question that is too short', async () => {
    const user = await openChat({ data: answer })
    await user.type(await screen.findByLabelText('Your question'), 'hi')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})
