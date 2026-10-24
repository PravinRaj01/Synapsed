import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const http = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }))
vi.mock('@/lib/api', () => ({
  api: http,
  unwrap: async (call: Promise<{ data?: unknown; error?: { detail?: string } }>) => {
    const r = await call
    if (r.error) throw new Error(r.error.detail ?? 'failed')
    return r.data
  },
  unwrapEmpty: async (call: Promise<{ error?: { detail?: string } }>) => {
    const r = await call
    if (r.error) throw new Error(r.error.detail ?? 'failed')
  },
}))
const dl = vi.hoisted(() => ({ downloadText: vi.fn() }))
vi.mock('@/lib/download', () => dl)
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

import { useCampaign } from '@/stores/campaign'
import Roadmap from './Roadmap'

const campaign = { id: 'c1', workspace_id: 'w1', name: 'Month-end research', goal: null, created_at: '2026-10-01T00:00:00Z', resources: 3, staged: 0, insights: 9, themes: 3 }
const theme = (id: string, label: string) => ({
  id, label, description: null, color: '#ec4899', frequency: 5, business_impact: 50, sentiment: 'negative', sentiment_counts: { positive: 0, neutral: 0, negative: 5 }, sentiment_net: -1,
  average_severity: 3, kinds: { pain_point: 5 }, sources: 3, segments: [], use_cases: [],
})
const item = (id: string, title: string, horizon: string, ice: number, patch: Record<string, unknown> = {}) => ({
  id, campaign_id: 'c1', theme_id: `t-${id}`, theme: `Theme ${id}`, color: '#6366f1', insight_id: null, title, description: `About ${title}`, horizon,
  impact_score: 8, confidence_score: 6, ease_score: 5, ice_score: ice, created_at: '2026-10-24T00:00:00Z', ...patch,
})
const initial = () => [item('a', 'Fix large report exports', 'now', 480), item('b', 'Make bank matching reliable', 'now', 288), item('c', 'Show approval status', 'next', 280), item('d', 'Ship payroll integrations', 'later', 168)]

const prdBody = (title = 'Reliable report exports') => ({
  id: 'p1', roadmap_item_id: 'a', markdown: '# Reliable report exports\n', jira_issue_key: null, created_at: '2026-10-25T00:00:00Z',
  content: {
    prd: {
      title, context: 'Finance teams export large ledgers every month.', problem: 'Large exports time out, so people split and stitch files by hand.', goals: ['Exports of any size finish'], user_stories: [{ as_a: 'finance lead', i_want: 'to export the whole ledger', so_that: 'I do not stitch files', evidence: [1, 9] }],
      acceptance_criteria: ['A 10,000-row export completes'], out_of_scope: ['PDF styling'], success_metrics: ['Export failures under 1%'],
    },
    evidence: [{ n: 1, insight_id: 'i1', summary: 'Export times out', severity: 4, sentiment: 'negative', segment: 'Enterprise', quote: 'it times out for our biggest entity', resource_id: 'r1', resource_title: 'Interview: finance lead', start_offset: 0, end_offset: 10 }],
  },
})

type World = { items?: ReturnType<typeof initial>; versions?: { id: string; title: string; jira_issue_key: string | null; created_at: string }[]; jira?: boolean; fail?: boolean }
let state: World & { items: ReturnType<typeof initial> }

function setup(over: World = {}) {
  state = { items: initial(), versions: [], jira: false, ...over } as never
  http.GET.mockImplementation(async (path: string) => {
    if (path === '/api/v1/campaigns') return { data: [campaign] }
    if (path === '/api/v1/campaigns/{campaign_id}/themes') return { data: [theme('t1', 'Exports')] }
    if (path === '/api/v1/campaigns/{campaign_id}/segments') return { data: [] }
    if (path === '/api/v1/campaigns/{campaign_id}/roadmap') return state.fail ? { error: { detail: 'The server is waking up' } } : { data: state.items }
    if (path === '/api/v1/roadmap/{item_id}/prds') return { data: state.versions }
    if (path === '/api/v1/prds/{prd_id}') return { data: { ...prdBody(), id: 'p1' } }
    if (path === '/api/v1/integrations') return { data: { jira: { configured: !!state.jira, project_key: state.jira ? 'PROJ' : null } } }
    return { data: [] }
  })
  http.PATCH.mockImplementation(async (_p: string, o: { params: { path: { item_id: string } }; body: Record<string, unknown> }) => {
    const found = state.items.find((i) => i.id === o.params.path.item_id)!
    const saved = { ...found, ...o.body } as typeof found
    if ('impact_score' in o.body || 'confidence_score' in o.body || 'ease_score' in o.body) saved.ice_score = saved.impact_score * saved.confidence_score * saved.ease_score
    state.items = state.items.map((i) => (i.id === saved.id ? saved : i))
    return { data: saved }
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/roadmap?tab=board']}>
        <Roadmap />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const column = (name: string) => screen.getByRole('region', { name: new RegExp(`^${name}:`) })
const titlesIn = (name: string) => within(column(name)).queryAllByRole('button', { name: /^Open / }).map((b) => b.getAttribute('aria-label')!.replace('Open ', ''))

beforeEach(() => {
  for (const m of Object.values(http)) m.mockReset()
  dl.downloadText.mockReset()
  Object.values(toast).forEach((f) => f.mockReset())
  useCampaign.setState({ campaignId: 'c1' })
})

describe('the board', () => {
  it('shows the cards in their columns, highest ICE first, with their scores', async () => {
    setup()
    await screen.findByRole('region', { name: /^Now:/ })
    expect(titlesIn('Now')).toEqual(['Fix large report exports', 'Make bank matching reliable'])
    expect(titlesIn('Next')).toEqual(['Show approval status'])
    expect(titlesIn('Later')).toEqual(['Ship payroll integrations'])
    const card = screen.getByRole('button', { name: 'Open Fix large report exports' })
    expect(within(card).getByText('ICE 480')).toBeInTheDocument()
    expect(within(card).getByText('I 8')).toBeInTheDocument()
    expect(within(card).getByText('Theme a')).toBeInTheDocument()
    expect(column('Now')).toHaveAccessibleName('Now: 2 items')
  })

  it('moves a card with its menu at once, and saves the new column', async () => {
    let finish: (v: unknown) => void = () => {}
    const user = setup()
    await screen.findByRole('region', { name: /^Now:/ })
    http.PATCH.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    await user.click(screen.getByRole('button', { name: 'Move Fix large report exports' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Later' }))
    await waitFor(() => expect(titlesIn('Later')).toContain('Fix large report exports')) // before the server has answered
    expect(titlesIn('Now')).toEqual(['Make bank matching reliable'])
    expect(http.PATCH.mock.calls[0][1].body).toEqual({ horizon: 'later' })
    await act(async () => finish({ data: { ...state.items[0], horizon: 'later' } }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Moved to Later.'))
  })

  it('puts a card back and says why when the server refuses the move', async () => {
    const user = setup()
    await screen.findByRole('region', { name: /^Now:/ })
    http.PATCH.mockResolvedValueOnce({ error: { detail: 'Roadmap item not found' } })
    await user.click(screen.getByRole('button', { name: 'Move Show approval status' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Now' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('"Show approval status" stayed in Next. Roadmap item not found'))
    await waitFor(() => expect(titlesIn('Next')).toEqual(['Show approval status']))
    expect(titlesIn('Now')).toHaveLength(2)
  })

  it('offers only the other columns in the Move to menu', async () => {
    const user = setup()
    await screen.findByRole('region', { name: /^Now:/ })
    await user.click(screen.getByRole('button', { name: 'Move Fix large report exports' }))
    expect((await screen.findAllByRole('menuitem')).map((m) => m.textContent)).toEqual(['Next', 'Later'])
  })

  it('says so when a column is empty, and when there is no roadmap at all', async () => {
    setup({ items: [item('a', 'Only one', 'now', 100)] as never })
    await screen.findByRole('region', { name: /^Now:/ })
    expect(within(column('Next')).getByText('Drop a card here')).toBeInTheDocument()
  })

  it('explains an empty roadmap, and offers a retry when it cannot be loaded', async () => {
    setup({ items: [] as never })
    expect(await screen.findByText('No roadmap items yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Knowledge Vault' })).toBeInTheDocument()
  })

  it('shows the error and retries', async () => {
    const user = setup({ fail: true })
    expect(await screen.findByText('The server is waking up')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(http.GET.mock.calls.filter(([p]) => p === '/api/v1/campaigns/{campaign_id}/roadmap').length).toBeGreaterThan(1)
  })

  it('shows a card menu instead of dragging on a phone', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} }))
    setup()
    await screen.findByRole('region', { name: /^Now:/ })
    expect(screen.getByText(/use its menu to move it/)).toBeInTheDocument()
    expect(within(column('Next')).queryByText('Drop a card here')).not.toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})

describe('editing a card', () => {
  async function openCard(user: ReturnType<typeof userEvent.setup>, title = 'Fix large report exports') {
    await user.click(await screen.findByRole('button', { name: `Open ${title}` }))
    return screen.findByRole('dialog')
  }

  it('saves only what changed, and the card and its ICE update', async () => {
    const user = setup()
    const dialog = await openCard(user)
    const save = within(dialog).getByRole('button', { name: 'Save changes' })
    expect(save).toBeDisabled() // nothing changed yet
    fireEvent.change(within(dialog).getByRole('slider', { name: 'Ease' }), { target: { value: '9' } })
    expect(within(dialog).getByText('432')).toBeInTheDocument() // 8 × 6 × 9, previewed before saving
    await user.click(save)
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Saved.'))
    expect(http.PATCH.mock.calls[0][1].body).toEqual({ ease_score: 9 })
    // the card behind the open panel (the page is hidden from the accessibility tree while a dialog is open)
    expect(within(screen.getByRole('button', { name: 'Open Fix large report exports', hidden: true })).getByText('ICE 432')).toBeInTheDocument()
  })

  it('tidies the title, refuses an empty one, and can undo', async () => {
    const user = setup()
    const dialog = await openCard(user)
    const title = within(dialog).getByLabelText('Title')
    await user.clear(title)
    expect(within(dialog).getByText('A title is needed')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Save changes' })).toBeDisabled()
    await user.type(title, '  Exports   that finish  ')
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(http.PATCH).toHaveBeenCalled())
    expect(http.PATCH.mock.calls[0][1].body).toEqual({ title: 'Exports that finish' })
  })

  it('offers to undo changes before saving', async () => {
    const user = setup()
    const dialog = await openCard(user)
    await user.type(within(dialog).getByLabelText('Description'), ' more')
    await user.click(within(dialog).getByRole('button', { name: 'Undo changes' }))
    expect(within(dialog).getByLabelText('Description')).toHaveValue('About Fix large report exports')
  })

  it('shows the error when saving fails', async () => {
    const user = setup()
    const dialog = await openCard(user)
    http.PATCH.mockResolvedValueOnce({ error: { detail: 'Scores must be between 1 and 10' } })
    fireEvent.change(within(dialog).getByRole('slider', { name: 'Impact' }), { target: { value: '3' } })
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Scores must be between 1 and 10'))
  })
})

describe('PRD studio', () => {
  async function openCard(user: ReturnType<typeof userEvent.setup>, title = 'Fix large report exports') {
    await user.click(await screen.findByRole('button', { name: `Open ${title}` }))
    return screen.findByRole('dialog')
  }
  const version = (id: string, jira: string | null = null) => ({ id, title: 'Reliable report exports', jira_issue_key: jira, created_at: '2026-10-25T00:00:00Z' })

  it('says there is no PRD yet, writes one with a visible wait, and shows it with its evidence', async () => {
    let finish: (v: unknown) => void = () => {}
    http.POST.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    const user = setup()
    const dialog = await openCard(user)
    expect(await within(dialog).findByText(/No PRD yet/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Write a PRD' }))
    expect(await within(dialog).findByText(/Reading the evidence and writing the PRD/)).toBeInTheDocument()
    expect(http.POST.mock.calls[0][0]).toBe('/api/v1/roadmap/{item_id}/prd')
    state.versions = [version('p1')]
    await act(async () => finish({ data: prdBody() }))
    expect(await within(dialog).findByText('Reliable report exports', { selector: 'h2' })).toBeInTheDocument()
    expect(within(dialog).getByText('Large exports time out, so people split and stitch files by hand.')).toBeInTheDocument()
    expect(within(dialog).getByText('A 10,000-row export completes')).toBeInTheDocument()
    expect(within(dialog).getAllByText(/it times out for our biggest entity/).length).toBeGreaterThanOrEqual(1)
    expect(toast.success).toHaveBeenCalledWith('PRD written.')
  })

  it('shows the reason when a PRD cannot be written', async () => {
    http.POST.mockResolvedValue({ error: { detail: 'This item has no cited evidence yet. Run an analysis first.' } })
    const user = setup()
    const dialog = await openCard(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Write a PRD' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('no cited evidence yet')
  })

  it('cannot write a PRD for an item that has no theme', async () => {
    const user = setup({ items: [item('a', 'Orphan', 'now', 100, { theme_id: null, theme: null })] as never })
    const dialog = await openCard(user, 'Orphan')
    expect(await within(dialog).findByText(/no theme, so there is no customer evidence/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Write a PRD' })).toBeDisabled()
  })

  it('lists versions, newest first, and downloads the one on screen as Markdown', async () => {
    const user = setup({ versions: [version('p2'), version('p1')] })
    const dialog = await openCard(user)
    const select = await within(dialog).findByLabelText('PRD version')
    expect(within(select).getAllByRole('option').map((o) => o.textContent?.split(' · ')[0])).toEqual(['Version 2', 'Version 1'])
    await user.click(await within(dialog).findByRole('button', { name: 'Markdown' }))
    expect(dl.downloadText).toHaveBeenCalledWith('reliable-report-exports-prd.md', '# Reliable report exports\n', 'text/markdown')
  })

  it('prints only the PRD: marks the page while printing and clears it afterwards', async () => {
    const seen: (string | undefined)[] = []
    const print = vi.spyOn(window, 'print').mockImplementation(() => { seen.push(document.body.dataset.printing) })
    const user = setup({ versions: [version('p1')] })
    const dialog = await openCard(user)
    await user.click(await within(dialog).findByRole('button', { name: /Print or PDF/ }))
    expect(seen).toEqual(['prd'])
    expect(document.getElementById('prd-print')).not.toBeNull() // the copy the print stylesheet shows
    expect(within(document.getElementById('prd-print')!).getByText('Reliable report exports')).toBeInTheDocument()
    window.dispatchEvent(new Event('afterprint'))
    expect(document.body.dataset.printing).toBeUndefined()
    print.mockRestore()
  })

  it('deletes a version only after asking', async () => {
    http.DELETE.mockResolvedValue({ response: { ok: true } })
    const user = setup({ versions: [version('p1')] })
    const dialog = await openCard(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Delete this version' }))
    expect(http.DELETE).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Keep' }))
    await user.click(within(dialog).getByRole('button', { name: 'Delete this version' }))
    await user.click(within(dialog).getByRole('button', { name: 'Yes, delete' }))
    await waitFor(() => expect(http.DELETE).toHaveBeenCalledTimes(1))
    expect(http.DELETE.mock.calls[0][1].params.path.prd_id).toBe('p1')
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Version deleted.'))
  })

  it('shows the Jira button only when Jira is set up, and says where the issue went', async () => {
    http.POST.mockResolvedValue({ data: { jira_issue_key: 'PROJ-7', url: 'https://acme.atlassian.net/browse/PROJ-7' } })
    const user = setup({ versions: [version('p1')], jira: true })
    const dialog = await openCard(user)
    await user.click(await within(dialog).findByRole('button', { name: 'Create Jira issue' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Created PROJ-7 in Jira.'))
    expect(http.POST.mock.calls[0][0]).toBe('/api/v1/prds/{prd_id}/jira')
  })

  it('has no Jira button when Jira is not set up', async () => {
    const user = setup({ versions: [version('p1')], jira: false })
    const dialog = await openCard(user)
    await within(dialog).findByRole('button', { name: 'Markdown' })
    expect(within(dialog).queryByRole('button', { name: 'Create Jira issue' })).not.toBeInTheDocument()
  })
})
