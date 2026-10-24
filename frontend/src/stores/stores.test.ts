import { beforeEach, describe, expect, it } from 'vitest'
import { useCampaign } from './campaign'
import { useTheme } from './theme'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.dataset.theme = 'light'
  useTheme.setState({ theme: 'light' })
  useCampaign.setState({ campaignId: null })
})

describe('theme', () => {
  it('toggles between light and dark and updates the page', () => {
    useTheme.getState().toggle()
    expect(useTheme.getState().theme).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    useTheme.getState().toggle()
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('remembers the choice for next time', () => {
    useTheme.getState().set('dark')
    expect(JSON.parse(localStorage.getItem('synapsed-theme')!).state.theme).toBe('dark')
  })
})

describe('campaign scope', () => {
  it('holds the active campaign and remembers it', () => {
    useCampaign.getState().setCampaign('c-1')
    expect(useCampaign.getState().campaignId).toBe('c-1')
    expect(JSON.parse(localStorage.getItem('synapsed-campaign')!).state.campaignId).toBe('c-1')
  })

  it('can be cleared', () => {
    useCampaign.getState().setCampaign('c-1')
    useCampaign.getState().setCampaign(null)
    expect(useCampaign.getState().campaignId).toBeNull()
  })
})
