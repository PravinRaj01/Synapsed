import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router'
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

import { useCampaign } from '@/stores/campaign'
import Roadmap from './Roadmap'

const campaign = { id: 'c1', workspace_id: 'w1', name: 'Month-end research', goal: null, created_at: '2026-10-01T00:00:00Z', resources: 3, staged: 0, insights: 9, themes: 2 }
const theme = (id: string, label: string) => ({
  id, label, description: null, color: '#ec4899', frequency: 5, business_impact: 50, sentiment: 'negative', sentiment_counts: { positive: 0, neutral: 0, negative: 5 }, sentiment_net: -1,
  average_severity: 3, kinds: { pain_point: 5 }, sources: 3, segments: [], use_cases: [],
})
const spec = (patch: Record<string, unknown> = {}) => ({ type: 'bar', x: 'theme', y: 'impact', split_by: null, filters: [], limit: 12, title: null, ...patch })
const matrix = {
  impact_line: 50, frequency_line: 3,
  points: [
    { theme_id: 't1', label: 'Report exports time out', color: '#ec4899', frequency: 7, business_impact: 100, ice_score: 480, horizon: 'now', quadrant: 'priority', quadrant_label: 'Frequent and high impact' },
    { theme_id: 't2', label: 'Approvals are opaque', color: '#6366f1', frequency: 2, business_impact: 66, ice_score: 280, horizon: 'next', quadrant: 'high_stakes', quadrant_label: 'High impact, mentioned less often' },
  ],
  quadrants: [{ key: 'priority', label: 'Frequent and high impact' }, { key: 'high_stakes', label: 'High impact, mentioned less often' }, { key: 'common_annoyance', label: 'Frequent, lower impact' }, { key: 'monitor', label: 'Lower impact, less frequent' }],
}
const presets = [
  { key: 'top_themes', title: 'Themes by Business Impact', spec: spec(), result: { x: ['Report exports time out', 'Approvals are opaque'], series: [{ name: 'Business impact', values: [100, 66] }], measure: 'Business impact' } },
  { key: 'sentiment_by_segment', title: 'Sentiment by customer segment', spec: spec({ type: 'stacked_bar', x: 'segment', split_by: 'sentiment' }), result: { x: ['Enterprise', 'Free'], series: [{ name: 'negative', values: [8, 3] }, { name: 'positive', values: [1, 2] }], measure: 'Insights' } },
  { key: 'severity', title: 'How severe are the problems?', spec: spec({ x: 'severity' }), result: { x: ['1', '2', '3'], series: [{ name: 'Insights', values: [0, 0, 0] }], measure: 'Insights' } },
]
const made = { spec: spec({ type: 'stacked_bar', x: 'segment', split_by: 'sentiment', title: 'Negative by segment' }), title: 'Negative by segment', model: 'groq:gpt-oss', tokens: 300, result: { x: ['Enterprise', 'Free'], series: [{ name: 'negative', values: [8, 3] }], measure: 'Insights' } }

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function setup(over: { presetsFail?: boolean; start?: string } = {}) {
  http.GET.mockImplementation(async (path: string) => {
    if (path === '/api/v1/campaigns') return { data: [campaign] }
    if (path === '/api/v1/campaigns/{campaign_id}/themes') return { data: [theme('t1', 'Report exports time out'), theme('t2', 'Approvals are opaque')] }
    if (path === '/api/v1/campaigns/{campaign_id}/segments') return { data: [] }
    if (path === '/api/v1/campaigns/{campaign_id}/opportunity-matrix') return { data: matrix }
    if (path === '/api/v1/campaigns/{campaign_id}/charts/presets') return over.presetsFail ? { error: { detail: 'The charts could not be built' } } : { data: presets }
    return { data: {} }
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[over.start ?? '/roadmap?tab=insights']}>
        <Roadmap />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const chartPosts = () => http.POST.mock.calls.filter(([p]) => p === '/api/v1/campaigns/{campaign_id}/charts')

beforeEach(() => {
  http.GET.mockReset()
  http.POST.mockReset()
  useCampaign.setState({ campaignId: 'c1' })
})

describe('the tabs', () => {
  it('opens on the report, switches to the studio, and keeps the choice in the address', async () => {
    const user = setup({ start: '/roadmap' })
    expect(await screen.findByText(/themes?, ranked by/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /CSV/ })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Insights Studio' }))
    expect(await screen.findByText('Opportunity matrix')).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/roadmap?tab=insights')
    expect(screen.queryByRole('button', { name: /CSV/ })).not.toBeInTheDocument() // exports belong to the report
    await user.click(screen.getByRole('tab', { name: 'Problem space' }))
    expect(await screen.findByText(/themes?, ranked by/)).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/roadmap$/)
  })

  it('opens straight on the studio from the address', async () => {
    setup()
    expect(await screen.findByText('Opportunity matrix')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Insights Studio' })).toHaveAttribute('aria-selected', 'true')
  })
})

describe('the opportunity matrix', () => {
  it('lists every theme with its quadrant in the table view, highest impact first', async () => {
    const user = setup()
    const card = (await screen.findByText('Opportunity matrix', { selector: 'h3' })).closest('div[class*=rounded-card]') as HTMLElement
    await user.click(within(card).getByRole('tab', { name: 'Table' }))
    const table = await screen.findByRole('table', { name: 'Opportunity matrix' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell').map((c) => c.textContent))).toEqual([
      ['Frequent and high impact', '7', '100', '480', 'now'],
      ['High impact, mentioned less often', '2', '66', '280', 'next'],
    ])
    expect(within(rows[0]).getByRole('rowheader')).toHaveTextContent('Report exports time out')
  })
})

describe('the standard dashboard', () => {
  it('shows each preset with what it counts, and a legend where there is more than one series', async () => {
    setup()
    expect(await screen.findByText('Themes by Business Impact')).toBeInTheDocument()
    expect(screen.getByText('Business impact by theme')).toBeInTheDocument()
    expect(screen.getByText('Insights by segment, split by sentiment')).toBeInTheDocument()
    const stacked = screen.getByText('Sentiment by customer segment').closest('div[class*=rounded-card]') as HTMLElement
    const legend = within(stacked).getByRole('list', { name: 'Legend' })
    expect(within(legend).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['negative', 'positive'])
    const single = screen.getByText('Themes by Business Impact').closest('div[class*=rounded-card]') as HTMLElement
    expect(within(single).queryByRole('list', { name: 'Legend' })).not.toBeInTheDocument() // one series: the title says what it is
  })

  it('offers the same numbers as a table, with a total for a stacked chart', async () => {
    const user = setup()
    const card = (await screen.findByText('Sentiment by customer segment')).closest('div[class*=rounded-card]') as HTMLElement
    await user.click(within(card).getByRole('tab', { name: 'Table' }))
    const table = within(card).getByRole('table', { name: 'Sentiment by customer segment' })
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Segment', 'negative', 'positive', 'Total'])
    expect(within(table).getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell').map((c) => c.textContent))).toEqual([['8', '1', '9'], ['3', '2', '5']])
  })

  it('says so when a chart has nothing to show, rather than drawing an empty frame', async () => {
    setup()
    const card = (await screen.findByText('How severe are the problems?')).closest('div[class*=rounded-card]') as HTMLElement
    expect(within(card).getByText('Nothing to chart yet for this view.')).toBeInTheDocument()
  })

  it('says so, and can retry, when the charts cannot be built', async () => {
    const user = setup({ presetsFail: true })
    expect(await screen.findByText('The charts could not be built')).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Try again' })[0])
    expect(http.GET.mock.calls.filter(([p]) => p.endsWith('/charts/presets')).length).toBeGreaterThan(1)
  })
})

describe('asking for a chart', () => {
  it('sends the request, shows the chart with what was asked, and lets it be removed', async () => {
    http.POST.mockResolvedValue({ data: made })
    const user = setup()
    await user.type(await screen.findByLabelText('Describe the chart you want'), 'negative sentiment by segment as a stacked bar')
    await user.click(screen.getByRole('button', { name: 'Make chart' }))
    expect(await screen.findByText('Negative by segment')).toBeInTheDocument()
    expect(chartPosts()[0][1].body).toEqual({ prompt: 'negative sentiment by segment as a stacked bar' })
    expect(chartPosts()[0][1].params.path.campaign_id).toBe('c1')
    expect(screen.getByText(/You asked: “negative sentiment by segment as a stacked bar”/)).toBeInTheDocument()
    expect(screen.getByLabelText('Describe the chart you want')).toHaveValue('') // ready for the next one
    await user.click(screen.getByRole('button', { name: 'Remove Negative by segment' }))
    expect(screen.queryByText('Negative by segment')).not.toBeInTheDocument()
  })

  it('shows the newest chart first', async () => {
    http.POST.mockResolvedValueOnce({ data: { ...made, title: 'First chart' } }).mockResolvedValueOnce({ data: { ...made, title: 'Second chart' } })
    const user = setup()
    const box = await screen.findByLabelText('Describe the chart you want')
    await user.type(box, 'one')
    await user.click(screen.getByRole('button', { name: 'Make chart' }))
    await screen.findByText('First chart')
    await user.type(box, 'two')
    await user.click(screen.getByRole('button', { name: 'Make chart' }))
    await screen.findByText('Second chart')
    const titles = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(titles.indexOf('Second chart')).toBeLessThan(titles.indexOf('First chart'))
  })

  it('runs a suggestion as written', async () => {
    http.POST.mockResolvedValue({ data: made })
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Sentiment by segment as a stacked bar' }))
    await waitFor(() => expect(chartPosts()).toHaveLength(1))
    expect(chartPosts()[0][1].body.prompt).toBe('Sentiment by segment as a stacked bar')
  })

  it('shows the reason when the data cannot answer, and keeps what was typed', async () => {
    http.POST.mockResolvedValue({ error: { detail: 'That cannot be answered from this data: there is no pricing information.' } })
    const user = setup()
    const box = await screen.findByLabelText('Describe the chart you want')
    await user.type(box, 'revenue by plan')
    await user.click(screen.getByRole('button', { name: 'Make chart' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('no pricing information')
    expect(box).toHaveValue('revenue by plan')
  })

  it('will not send a request that is too short', async () => {
    const user = setup()
    await user.type(await screen.findByLabelText('Describe the chart you want'), 'hi')
    expect(screen.getByRole('button', { name: 'Make chart' })).toBeDisabled()
  })
})
