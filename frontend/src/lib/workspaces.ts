import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { useCampaign } from '@/stores/campaign'
import { api, unwrap } from './api'
import type { Overview, SetupValues } from './onboarding'

export type Workspace = components['schemas']['WorkspaceOut']

export function useWorkspaces() {
  return useQuery({ queryKey: ['workspaces'], queryFn: () => unwrap(api.GET('/api/v1/workspaces', {})) })
}

/** Everything the dashboard shows for a campaign, in one call. */
export function useOverview(campaignId: string | null | undefined) {
  return useQuery({
    queryKey: ['overview', campaignId],
    enabled: !!campaignId,
    queryFn: (): Promise<Overview> => unwrap(api.GET('/api/v1/campaigns/{campaign_id}/overview', { params: { path: { campaign_id: campaignId! } } })),
  })
}

function refreshCampaignData(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ['campaigns'] }),
    queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
    queryClient.invalidateQueries({ queryKey: ['overview'] }),
  ])
}

/** Fill an empty campaign with the demo sandbox (no AI calls on the server). */
export function useLoadDemo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (campaignId: string) => unwrap(api.POST('/api/v1/campaigns/{campaign_id}/demo', { params: { path: { campaign_id: campaignId } } })),
    onSuccess: () => refreshCampaignData(queryClient),
  })
}

type SetupInput = { values: SetupValues; workspaceId: string | null; withDemo: boolean }
export type SetupResult = { campaignId: string; demoLoaded: boolean; demoError: string | null }

/**
 * The onboarding wizard's last step: create the workspace if this is the user's first, then the campaign with its
 * segments, then optionally load the demo. The campaign is kept even if the demo fails, and the result says so.
 */
export function useCreateSetup() {
  const queryClient = useQueryClient()
  const setCampaign = useCampaign((s) => s.setCampaign)
  return useMutation({
    mutationFn: async ({ values, workspaceId, withDemo }: SetupInput): Promise<SetupResult> => {
      let workspace = workspaceId
      if (!workspace) {
        const p = values.profile
        const created = await unwrap(
          api.POST('/api/v1/workspaces', {
            body: {
              name: p.company,
              company: p.company,
              industry: p.industry,
              domain: p.domain || null,
              target_audience: p.targetAudience || null,
              owner_role: p.ownerRole || null,
            },
          }),
        )
        workspace = created.id
      }
      const c = values.campaign
      const campaign = await unwrap(
        api.POST('/api/v1/campaigns', {
          body: { workspace_id: workspace, name: c.name, goal: c.goal || null, segments: c.segments.map((s) => ({ name: s.name, tier: s.tier, weight: s.weight })) },
        }),
      )
      let demoLoaded = false
      let demoError: string | null = null
      if (withDemo) {
        try {
          await unwrap(api.POST('/api/v1/campaigns/{campaign_id}/demo', { params: { path: { campaign_id: campaign.id } } }))
          demoLoaded = true
        } catch (e) {
          demoError = e instanceof Error ? e.message : 'The demo could not be loaded.'
        }
      }
      return { campaignId: campaign.id, demoLoaded, demoError }
    },
    onSuccess: async ({ campaignId }) => {
      await refreshCampaignData(queryClient)
      setCampaign(campaignId)
    },
  })
}
