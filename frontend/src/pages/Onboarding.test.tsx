import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
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
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock('sonner', () => ({ toast }))

import { useCampaign } from '@/stores/campaign'
import Onboarding from './Onboarding'

const workspace = { id: 'w1', name: 'Acme', company: 'Acme', industry: 'SaaS', role: 'owner', campaigns: 1 }

function setup(workspaces: unknown[]) {
  http.GET.mockImplementation(async (path: string) => (path === '/api/v1/workspaces' ? { data: workspaces } : { data: [] }))
  http.POST.mockImplementation(async (path: string) => {
    if (path === '/api/v1/workspaces') return { data: { id: 'w-new' } }
    if (path === '/api/v1/campaigns') return { data: { id: 'c-new' } }
    return { data: { resources: 10, insights: 37, themes: 6, roadmap_items: 5 } }
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/dashboard" element={<p>Dashboard page</p>} />
          <Route path="/vault" element={<p>Vault page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const calls = (path: string) => http.POST.mock.calls.filter(([p]) => p === path)

beforeEach(() => {
  http.GET.mockReset()
  http.POST.mockReset()
  Object.values(toast).forEach((f) => f.mockReset())
  useCampaign.setState({ campaignId: null })
})

describe('first-time setup', () => {
  it('asks about the business first and will not continue without a company and industry', async () => {
    const user = setup([])
    expect(await screen.findByRole('heading', { name: 'Welcome to Synapsed' })).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Continue' }))
    expect(await screen.findByText('Enter your company name')).toBeInTheDocument()
    expect(screen.getByText('Enter your industry')).toBeInTheDocument()
    expect(screen.queryByLabelText('Campaign name')).not.toBeInTheDocument()
  })

  it('creates the workspace, the campaign with its weighted segments and the demo, then opens the dashboard', async () => {
    const user = setup([])
    await user.type(await screen.findByLabelText('Company'), 'Acme Inc.')
    await user.type(screen.getByLabelText('Industry'), 'B2B software')
    await user.type(screen.getByLabelText('Your role'), 'Head of Product')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    expect(await screen.findByLabelText('Segment 1 name')).toHaveValue('Enterprise')
    expect(screen.getByLabelText('Segment 1 weight')).toHaveValue(3)
    expect(screen.getByLabelText('Segment 3 name')).toHaveValue('Free')
    await user.type(screen.getByLabelText('Campaign name'), 'Q4 churn research')
    await user.click(screen.getByRole('button', { name: 'Continue' }))

    await user.click(await screen.findByRole('button', { name: /Explore the demo sandbox/ }))
    expect(await screen.findByText('Dashboard page')).toBeInTheDocument()

    expect(calls('/api/v1/workspaces')[0][1].body).toEqual({ name: 'Acme Inc.', company: 'Acme Inc.', industry: 'B2B software', domain: null, target_audience: null, owner_role: 'Head of Product' })
    expect(calls('/api/v1/campaigns')[0][1].body).toEqual({
      workspace_id: 'w-new', name: 'Q4 churn research', goal: null,
      segments: [{ name: 'Enterprise', tier: 'enterprise', weight: 3 }, { name: 'Mid-Market', tier: 'mid_market', weight: 2 }, { name: 'Free', tier: 'free', weight: 1 }],
    })
    expect(calls('/api/v1/campaigns/{campaign_id}/demo')[0][1].params.path.campaign_id).toBe('c-new')
    expect(useCampaign.getState().campaignId).toBe('c-new')
    expect(toast.success).toHaveBeenCalled()
  })

  it('goes back a step without losing what was typed', async () => {
    const user = setup([])
    await user.type(await screen.findByLabelText('Company'), 'Acme')
    await user.type(screen.getByLabelText('Industry'), 'SaaS')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: 'Back' }))
    expect(await screen.findByLabelText('Company')).toHaveValue('Acme')
  })
})

describe('a returning user adding a campaign', () => {
  it('skips the business step and does not create a second workspace', async () => {
    const user = setup([workspace])
    expect(await screen.findByRole('heading', { name: 'New campaign' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Campaign name')).toBeInTheDocument()
    expect(screen.queryByLabelText('Company')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Campaign name'), 'Onboarding research')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: /Upload my own data/ }))

    expect(await screen.findByText('Vault page')).toBeInTheDocument()
    expect(calls('/api/v1/workspaces')).toHaveLength(0)
    expect(calls('/api/v1/campaigns')[0][1].body.workspace_id).toBe('w1')
    expect(calls('/api/v1/campaigns/{campaign_id}/demo')).toHaveLength(0)
  })

  it('needs a campaign name and refuses duplicate segment names', async () => {
    const user = setup([workspace])
    await user.click(await screen.findByRole('button', { name: 'Continue' }))
    expect(await screen.findByText('Enter a campaign name')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Campaign name'), 'Research')
    await user.clear(screen.getByLabelText('Segment 2 name'))
    await user.type(screen.getByLabelText('Segment 2 name'), ' enterprise ')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByText('Segment names must be different')).toBeInTheDocument()
  })

  it('lets segments be added, removed and reset', async () => {
    const user = setup([workspace])
    await screen.findByLabelText('Campaign name')
    await user.click(screen.getByRole('button', { name: 'Remove segment 1' }))
    expect(screen.getByLabelText('Segment 1 name')).toHaveValue('Mid-Market')
    await user.click(screen.getByRole('button', { name: /Add segment/ }))
    expect(screen.getByLabelText('Segment 3 name')).toHaveValue('')
    await user.click(screen.getByRole('button', { name: 'Reset to defaults' }))
    expect(screen.getByLabelText('Segment 1 name')).toHaveValue('Enterprise')
    expect(screen.queryByLabelText('Segment 4 name')).not.toBeInTheDocument()
  })

  it('keeps the campaign and says so when only the demo fails', async () => {
    const user = setup([workspace])
    http.POST.mockImplementation(async (path: string) =>
      path === '/api/v1/campaigns' ? { data: { id: 'c-new' } } : { error: { detail: 'The demo can only be loaded into a campaign that has no sources yet' } },
    )
    await user.type(await screen.findByLabelText('Campaign name'), 'Research')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: /Explore the demo sandbox/ }))

    expect(await screen.findByText('Dashboard page')).toBeInTheDocument()
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Your campaign is ready, but the demo did not load')))
    expect(useCampaign.getState().campaignId).toBe('c-new')
  })

  it('stays on the page and reports it when the campaign cannot be created', async () => {
    const user = setup([workspace])
    http.POST.mockResolvedValue({ error: { detail: 'Workspace not found' } })
    await user.type(await screen.findByLabelText('Campaign name'), 'Research')
    await user.click(screen.getByRole('button', { name: 'Continue' }))
    await user.click(await screen.findByRole('button', { name: /Upload my own data/ }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Workspace not found'))
    expect(screen.queryByText('Vault page')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Upload my own data/ })).toBeEnabled()
  })
})
