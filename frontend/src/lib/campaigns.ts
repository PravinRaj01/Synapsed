import { useQuery } from '@tanstack/react-query'
import type { Campaign } from '@/api/models'
import { api, unwrap } from './api'

export function useCampaigns() {
  return useQuery({
    queryKey: ['campaigns'],
    queryFn: () => unwrap(api.GET('/api/v1/campaigns', {})) as Promise<Campaign[]>,
  })
}
