import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const campaigns = vi.hoisted(() => ({ result: {} as Record<string, unknown> }))
vi.mock('@/lib/campaigns', () => ({ useCampaigns: () => campaigns.result }))

import { useCampaign } from '@/stores/campaign'
import { CampaignScope } from './CampaignScope'

const two = [
  { id: 'c1', name: 'Enterprise churn' },
  { id: 'c2', name: 'Onboarding' },
]

function show() {
  return render(
    <MemoryRouter>
      <CampaignScope />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  useCampaign.setState({ campaignId: null })
})

describe('campaign scope', () => {
  it('does not crash or forget the saved campaign when the list fails to load', () => {
    // Every render of the old code made a fresh empty list, so its effect ran, set state and rendered again, forever.
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    useCampaign.setState({ campaignId: 'c2' })
    campaigns.result = { data: undefined, isLoading: false, isError: true }
    show()
    expect(screen.getByRole('button', { name: 'Campaign scope' })).toBeInTheDocument()
    expect(useCampaign.getState().campaignId).toBe('c2')
    expect(errors).not.toHaveBeenCalled()
    errors.mockRestore()
  })

  it('falls back to the first campaign when the saved one is gone', () => {
    useCampaign.setState({ campaignId: 'deleted' })
    campaigns.result = { data: two, isLoading: false, isError: false }
    show()
    expect(useCampaign.getState().campaignId).toBe('c1')
    expect(screen.getByText('Enterprise churn')).toBeInTheDocument()
  })

  it('keeps the saved campaign while the list is still loading', () => {
    useCampaign.setState({ campaignId: 'c2' })
    campaigns.result = { data: undefined, isLoading: true, isError: false }
    show()
    expect(useCampaign.getState().campaignId).toBe('c2')
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('clears the choice when there are genuinely no campaigns', () => {
    useCampaign.setState({ campaignId: 'c2' })
    campaigns.result = { data: [], isLoading: false, isError: false }
    show()
    expect(useCampaign.getState().campaignId).toBeNull()
    expect(screen.getByText('No campaign')).toBeInTheDocument()
  })
})

describe('campaign store', () => {
  it('does not notify anyone when the campaign is set to what it already is', () => {
    useCampaign.setState({ campaignId: 'c1' })
    const listener = vi.fn()
    const stop = useCampaign.subscribe(listener)
    useCampaign.getState().setCampaign('c1')
    expect(listener).not.toHaveBeenCalled()
    useCampaign.getState().setCampaign('c2')
    expect(listener).toHaveBeenCalledTimes(1)
    stop()
  })
})
