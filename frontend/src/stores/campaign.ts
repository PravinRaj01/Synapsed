import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type CampaignState = {
  /** The Global Campaign Scope: every page filters by this campaign. */
  campaignId: string | null
  setCampaign: (id: string | null) => void
}

export const useCampaign = create<CampaignState>()(
  persist((set) => ({ campaignId: null, setCampaign: (campaignId) => set({ campaignId }) }), {
    name: 'synapsed-campaign',
  }),
)
