import { useMutation, useQuery } from '@tanstack/react-query'
import { api, unwrap } from './api'

export function useOpportunityMatrix(campaignId: string | null | undefined) {
  return useQuery({
    queryKey: ['matrix', campaignId],
    enabled: !!campaignId,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{campaign_id}/opportunity-matrix', { params: { path: { campaign_id: campaignId! } } })),
  })
}

export function usePresetCharts(campaignId: string | null | undefined) {
  return useQuery({
    queryKey: ['presets', campaignId],
    enabled: !!campaignId,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{campaign_id}/charts/presets', { params: { path: { campaign_id: campaignId! } } })),
  })
}

/** Turn a plain-language request into a chart. The model only picks from fixed options; the server builds and runs the query. */
export function useChartFromPrompt(campaignId: string) {
  return useMutation({
    mutationFn: (prompt: string) => unwrap(api.POST('/api/v1/campaigns/{campaign_id}/charts', { params: { path: { campaign_id: campaignId } }, body: { prompt } })),
  })
}
