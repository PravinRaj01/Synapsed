import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { components } from '@/api/schema'
import { api, unwrap } from './api'
import { ApiError } from './errors'

export type Segment = components['schemas']['SegmentUsageOut']
export type ThemeRow = components['schemas']['ThemeRowOut']
export type ThemeDetail = components['schemas']['ThemeDetailOut']
export type ResourceDetail = components['schemas']['ResourceDetailOut']
export type ResearchResult = components['schemas']['ResearchResult']

export function useSources(campaignId: string | null | undefined) {
  return useQuery({
    queryKey: ['sources', campaignId],
    enabled: !!campaignId,
    queryFn: () => unwrap(api.GET('/api/v1/resources', { params: { query: { campaign_id: campaignId! } } })),
  })
}

export function useSegments(campaignId: string | null | undefined) {
  return useQuery({
    queryKey: ['segments', campaignId],
    enabled: !!campaignId,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{campaign_id}/segments', { params: { path: { campaign_id: campaignId! } } })),
  })
}

export function useThemes(campaignId: string | null | undefined) {
  return useQuery({
    queryKey: ['themes', campaignId],
    enabled: !!campaignId,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{campaign_id}/themes', { params: { path: { campaign_id: campaignId! } } })),
  })
}

export function useThemeDetail(themeId: string | null) {
  return useQuery({
    queryKey: ['theme', themeId],
    enabled: !!themeId,
    queryFn: () => unwrap(api.GET('/api/v1/themes/{theme_id}', { params: { path: { theme_id: themeId! } } })),
  })
}

export function useSourceDetail(resourceId: string | null) {
  return useQuery({
    queryKey: ['source', resourceId],
    enabled: !!resourceId,
    queryFn: () => unwrap(api.GET('/api/v1/resources/{resource_id}', { params: { path: { resource_id: resourceId! } } })),
  })
}

/** Everything that depends on a campaign's sources, refreshed after any change to them. */
export function useRefreshVault() {
  const queryClient = useQueryClient()
  return () =>
    Promise.all(
      ['sources', 'segments', 'themes', 'theme', 'source', 'overview', 'campaigns'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
    )
}

export function useApprove() {
  const refresh = useRefreshVault()
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST('/api/v1/resources/{resource_id}/approve', { params: { path: { resource_id: id } } })),
    onSettled: () => refresh(),
  })
}

export function useReject() {
  const refresh = useRefreshVault()
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST('/api/v1/resources/{resource_id}/reject', { params: { path: { resource_id: id } } })),
    onSettled: () => refresh(),
  })
}

export function useUpdateSource() {
  const refresh = useRefreshVault()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; title?: string; segment_id?: string | null }) =>
      unwrap(api.PATCH('/api/v1/resources/{resource_id}', { params: { path: { resource_id: id } }, body })),
    onSettled: () => refresh(),
  })
}

export function useBulkSegment(campaignId: string) {
  const refresh = useRefreshVault()
  return useMutation({
    mutationFn: ({ ids, segmentId }: { ids: string[]; segmentId: string | null }) =>
      unwrap(api.POST('/api/v1/campaigns/{campaign_id}/resources/segment', { params: { path: { campaign_id: campaignId } }, body: { resource_ids: ids, segment_id: segmentId } })),
    onSettled: () => refresh(),
  })
}

export function useResearch(campaignId: string) {
  const refresh = useRefreshVault()
  return useMutation({
    mutationFn: ({ query, segmentId }: { query: string; segmentId: string | null }) =>
      unwrap(api.POST('/api/v1/research', { body: { campaign_id: campaignId, query, max_results: 5, segment_id: segmentId } })),
    onSettled: () => refresh(),
  })
}

export type BulkResult = { done: string[]; failed: { id: string; message: string }[]; stoppedEarly: boolean }

/**
 * Run an action on many sources one after another (approving embeds each one, which takes a few seconds and is
 * rate limited, so they are not sent all at once). A rate limit stops the rest, which are reported as not done.
 */
export async function runForEach(ids: string[], action: (id: string) => Promise<unknown>, onProgress?: (done: number, total: number) => void): Promise<BulkResult> {
  const result: BulkResult = { done: [], failed: [], stoppedEarly: false }
  for (const [i, id] of ids.entries()) {
    try {
      await action(id)
      result.done.push(id)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Something went wrong.'
      result.failed.push({ id, message })
      if (e instanceof ApiError && e.status === 429) {
        result.stoppedEarly = true
        for (const rest of ids.slice(i + 1)) result.failed.push({ id: rest, message: 'Not tried: ' + message })
        break
      }
    }
    onProgress?.(i + 1, ids.length)
  }
  return result
}
