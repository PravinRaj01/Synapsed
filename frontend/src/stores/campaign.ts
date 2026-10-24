import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type CampaignState = {
  /** The Global Campaign Scope: every page filters by this campaign. */
  campaignId: string | null
  setCampaign: (id: string | null) => void
}

export const useCampaign = create<CampaignState>()(
  persist(
    (set) => ({
      campaignId: null,
      // Setting the value it already has changes nothing and tells nobody, so it can never start a render loop.
      setCampaign: (campaignId) => set((s) => (s.campaignId === campaignId ? s : { campaignId })),
    }),
    { name: 'synapsed-campaign' },
  ),
)
