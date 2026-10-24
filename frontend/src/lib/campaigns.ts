import { useQuery } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, unwrap } from './api'

export type Campaign = components['schemas']['CampaignOut']

export function useCampaigns() {
  return useQuery({
    queryKey: ['campaigns'],
    queryFn: () => unwrap(api.GET('/api/v1/campaigns', {})),
  })
}
