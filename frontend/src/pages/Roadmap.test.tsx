import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
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
const dl = vi.hoisted(() => ({ downloadText: vi.fn() }))
vi.mock('@/lib/download', () => dl)

import { useCampaign } from '@/stores/campaign'
import Roadmap from './Roadmap'

const campaign = { id: 'c1', workspace_id: 'w1', name: 'Month-end research', goal: null, created_at: '2026-10-01T00:00:00Z', resources: 3, staged: 0, insights: 9, themes: 3 }
const theme = (id: string, label: string, patch: Record<string, unknown> = {}) => ({
  id, label, description: `About ${label}`, color: '#ec4899', frequency: 5, business_impact: 50, sentiment: 'negative',
  sentiment_counts: { positive: 0, neutral: 0, negative: 5 }, sentiment_net: -1, average_severity: 3, kinds: { pain_point: 4, feature_request: 1 }, sources: 3,
  segments: [{ segment_id: 's1', name: 'Enterprise', tier: 'enterprise', insights: 3 }, { segment_id: 's2', name: 'Free', tier: 'free', insights: 2 }],
  use_cases: [{ use_case: 'Monthly reporting', insights: 3 }], ...patch,
})
const themes = [
  theme('t1', 'Report exports time out', { business_impact: 100, frequency: 7, average_severity: 3.6 }),
  theme('t2', 'Bank matching is unreliable', { business_impact: 93, frequency: 9, average_severity: 4.2, segments: [{ segment_id: 's1', name: 'Enterprise', tier: 'enterprise', insights: 9 }] }),
  theme('t3', 'Approvals are opaque', { business_impact: 40, frequency: 3, average_severity: 2, sentiment: 'mixed' }),
]
const detail = {
  id: 't1', campaign_id: 'c1', label: 'Report exports time out', description: null, color: '#ec4899', frequency: 7, business_impact: 100,
  insights: [{ id: 'i1', summary_text: 'The ledger export times out for the largest entity.', use_case: 'Monthly reporting', severity: 4, sentiment: 'negative', kind: 'pain_point', confidence_score: 0.9, segment_id: 's1', segment: 'Enterprise', created_at: '2026-10-24T00:00:00Z',
    citations: [{ resource_id: 'r1', resource_title: 'Interview: finance lead', chunk_id: 'k1', text_snippet: 'it times out for our biggest entity', start_offset: 0, end_offset: 10 }] }],
}

function setup(over: { themes?: unknown; fail?: boolean } = {}) {
  http.GET.mockImplementation(async (path: string) => {
    if (path === '/api/v1/campaigns') return { data: [campaign] }
    if (path === '/api/v1/campaigns/{campaign_id}/themes') return over.fail ? { error: { detail: 'The server is waking up' } } : { data: over.themes ?? themes }
    if (path === '/api/v1/themes/{theme_id}') return { data: detail }
    if (path === '/api/v1/campaigns/{campaign_id}/segments') return { data: [] }
    if (path === '/api/v1/resources/{resource_id}') return { data: { id: 'r1', campaign_id: 'c1', title: 'Interview: finance lead', source_type: 'transcript', source_url: null, language: 'en', status: 'approved', content: 'it times out for our biggest entity', summary: null, pii_redacted: true, pii_note: null, segment_id: null, segment: null, analyzed_at: null, created_at: '2026-10-24T00:00:00Z', highlights: [] } }
    return { data: {} }
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Roadmap />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

// A theme's name is in the list and in the heatmap, so find the one inside an expandable row.
const themeButton = (label: string) => screen.getAllByText(label).map((e) => e.closest('button')).find(Boolean) as HTMLElement
const ready = () => screen.findByText(/themes?, ranked by/)

const order = () => screen.getAllByRole('button', { expanded: false }).map((b) => b.textContent ?? '').filter((t) => /time out|Bank matching|Approvals/.test(t))

beforeEach(() => {
  http.GET.mockReset()
  dl.downloadText.mockReset()
  useCampaign.setState({ campaignId: 'c1' })
})

describe('the problem space report', () => {
  it('ranks themes by business impact with their numbers', async () => {
    setup()
    await ready()
    const names = order()
    expect(names[0]).toContain('Report exports time out')
    expect(names[1]).toContain('Bank matching is unreliable')
    expect(names[2]).toContain('Approvals are opaque')
    const first = themeButton('Report exports time out')
    expect(within(first).getByText('100')).toBeInTheDocument()
    expect(within(first).getByText('3.6')).toBeInTheDocument()
    expect(within(first).getByText('Negative')).toBeInTheDocument()
    expect(within(themeButton('Approvals are opaque')).getByText('Mixed')).toBeInTheDocument()
    expect(screen.getByText('3 themes, ranked by')).toBeInTheDocument()
  })

  it('re-ranks by mentions and by severity', async () => {
    const user = setup()
    await ready()
    await user.click(screen.getByRole('tab', { name: 'Mentions' }))
    expect(order()[0]).toContain('Bank matching is unreliable') // 9 mentions
    await user.click(screen.getByRole('tab', { name: 'Severity' }))
    expect(order()[0]).toContain('Bank matching is unreliable') // 4.2
    expect(order()[2]).toContain('Approvals are opaque')
  })

  it('opens a theme to show what customers were doing and their own words, and opens the source from a quote', async () => {
    const user = setup()
    await ready()
    await user.click(themeButton('Report exports time out'))
    expect(await screen.findByText('Monthly reporting', { selector: 'li' })).toBeInTheDocument()
    expect(screen.getByText('4 pain points')).toBeInTheDocument()
    expect(screen.getByText('1 feature request')).toBeInTheDocument()
    expect(await screen.findByText(/it times out for our biggest entity/)).toBeInTheDocument()
    expect(http.GET.mock.calls.find(([p]) => p === '/api/v1/themes/{theme_id}')?.[1].params.path.theme_id).toBe('t1')
    await user.click(screen.getByRole('button', { name: 'Interview: finance lead' }))
    await waitFor(() => expect(http.GET.mock.calls.some(([p]) => p === '/api/v1/resources/{resource_id}')).toBe(true))
    expect(await screen.findByTestId('source-text')).toHaveTextContent('it times out for our biggest entity')
  })

  it('shows the who-raises-what heatmap with every count written out', async () => {
    setup()
    const table = await screen.findByRole('table', { name: 'Pain points by theme and customer segment' })
    // On a phone the heading shows a short form for the eye, but the full name is what is read out.
    const names = ['Theme', 'Enterprise', 'Free', 'Total'].map((n) => within(table).getByRole('columnheader', { name: n }))
    expect(names.map((h) => h.compareDocumentPosition(names[names.indexOf(h) + 1] ?? h))).toEqual([4, 4, 4, 0]) // in that order: Enterprise 3+9+3 = 15 is busiest
    const row = within(table).getByText('Bank matching is unreliable').closest('tr')!
    expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual(['9', '–', '9'])
    expect(within(table).getByTitle('Report exports time out, Free: 2 pain points')).toHaveTextContent('2')
  })
})

describe('exporting', () => {
  it('saves the ranked themes as CSV and as Markdown, named after the campaign', async () => {
    const user = setup()
    await ready()
    await user.click(screen.getByRole('button', { name: /CSV/ }))
    expect(dl.downloadText).toHaveBeenCalledWith('month-end-research-themes.csv', expect.stringContaining('1,Report exports time out'), 'text/csv')
    await user.click(screen.getByRole('button', { name: /Markdown/ }))
    expect(dl.downloadText).toHaveBeenLastCalledWith('month-end-research-problem-space.md', expect.stringContaining('# Problem space report: Month-end research'), 'text/markdown')
  })

  it('exports in the order on screen', async () => {
    const user = setup()
    await ready()
    await user.click(screen.getByRole('tab', { name: 'Mentions' }))
    await user.click(screen.getByRole('button', { name: /CSV/ }))
    const csv = dl.downloadText.mock.calls[0][1] as string
    expect(csv.split('\r\n')[1].startsWith('1,Bank matching is unreliable')).toBe(true)
  })

  it('opens the print dialog', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => {})
    const user = setup()
    await ready()
    await user.click(screen.getByRole('button', { name: /Print or PDF/ }))
    expect(print).toHaveBeenCalledTimes(1)
    print.mockRestore()
  })
})

describe('states', () => {
  it('explains an empty report and points to the vault', async () => {
    setup({ themes: [] })
    expect(await screen.findByText('No themes yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Knowledge Vault' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /CSV/ })).not.toBeInTheDocument()
  })

  it('says so, and can retry, when the report cannot be loaded', async () => {
    const user = setup({ fail: true })
    expect(await screen.findByText('The server is waking up')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(http.GET.mock.calls.filter(([p]) => p === '/api/v1/campaigns/{campaign_id}/themes').length).toBeGreaterThan(1)
  })

  it('shows each theme as a card on a phone, with its numbers under the name', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener: () => {}, removeEventListener: () => {} }))
    setup()
    await ready()
    const row = themeButton('Report exports time out')
    expect(within(row).getByText('7 mentions')).toBeInTheDocument()
    expect(within(row).getByText('3 sources')).toBeInTheDocument()
    expect(within(row).getByText('severity 3.6')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
