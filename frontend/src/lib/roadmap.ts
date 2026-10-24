import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, unwrapEmpty } from './api'
import { withHorizon, type Horizon, type ItemEdit, type RoadmapItem } from './board'

const roadmapKey = (campaignId: string | null | undefined) => ['roadmap', campaignId] as const

export function useRoadmap(campaignId: string | null | undefined) {
  return useQuery({
    queryKey: roadmapKey(campaignId),
    enabled: !!campaignId,
    queryFn: () => unwrap(api.GET('/api/v1/campaigns/{campaign_id}/roadmap', { params: { path: { campaign_id: campaignId! } } })),
  })
}

/** What else shows the board: the matrix (horizon in its tooltip) and the overview (roadmap count). */
function refreshAround(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all(['matrix', 'overview'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })))
}

/**
 * Move a card to another column. The card moves at once; if the server refuses, it goes back and the error is thrown
 * so the caller can say why.
 */
export function useMoveItem(campaignId: string) {
  const queryClient = useQueryClient()
  const key = roadmapKey(campaignId)
  return useMutation({
    mutationFn: ({ id, horizon }: { id: string; horizon: Horizon }) => unwrap(api.PATCH('/api/v1/roadmap/{item_id}', { params: { path: { item_id: id } }, body: { horizon } })),
    onMutate: async ({ id, horizon }) => {
      await queryClient.cancelQueries({ queryKey: key })
      const before = queryClient.getQueryData<RoadmapItem[]>(key)
      if (before) queryClient.setQueryData<RoadmapItem[]>(key, withHorizon(before, id, horizon))
      return { before }
    },
    onError: (_error, _vars, context) => {
      if (context?.before) queryClient.setQueryData(key, context.before)
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({ queryKey: key })
      await refreshAround(queryClient)
    },
  })
}

/** Save an edit to a card (title, description, scores). The server recomputes ICE, and its answer replaces the card. */
export function useUpdateItem(campaignId: string) {
  const queryClient = useQueryClient()
  const key = roadmapKey(campaignId)
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<ItemEdit> }) => unwrap(api.PATCH('/api/v1/roadmap/{item_id}', { params: { path: { item_id: id } }, body: patch })),
    onSuccess: (saved) => {
      queryClient.setQueryData<RoadmapItem[]>(key, (items) => items?.map((i) => (i.id === saved.id ? saved : i)))
      void refreshAround(queryClient)
    },
  })
}

// ---------------------------------------------------------------- PRDs

export function usePrdVersions(itemId: string | null) {
  return useQuery({
    queryKey: ['prds', itemId],
    enabled: !!itemId,
    queryFn: () => unwrap(api.GET('/api/v1/roadmap/{item_id}/prds', { params: { path: { item_id: itemId! } } })),
  })
}

export function usePrd(prdId: string | null) {
  return useQuery({
    queryKey: ['prd', prdId],
    enabled: !!prdId,
    queryFn: () => unwrap(api.GET('/api/v1/prds/{prd_id}', { params: { path: { prd_id: prdId! } } })),
  })
}

/** Write a new PRD version from the theme's evidence. It calls a model, so it can take half a minute. */
export function useGeneratePrd(itemId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/roadmap/{item_id}/prd', { params: { path: { item_id: itemId } } })),
    onSuccess: (prd) => {
      queryClient.setQueryData(['prd', prd.id], prd)
      void queryClient.invalidateQueries({ queryKey: ['prds', itemId] })
    },
  })
}

export function useDeletePrd(itemId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (prdId: string) => unwrapEmpty(api.DELETE('/api/v1/prds/{prd_id}', { params: { path: { prd_id: prdId } } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['prds', itemId] }),
  })
}

export function useIntegrations() {
  return useQuery({ queryKey: ['integrations'], queryFn: () => unwrap(api.GET('/api/v1/integrations', {})), staleTime: 5 * 60_000 })
}

export function useSendToJira(itemId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (prdId: string) => unwrap(api.POST('/api/v1/prds/{prd_id}/jira', { params: { path: { prd_id: prdId } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['prds', itemId] })
      void queryClient.invalidateQueries({ queryKey: ['prd'] })
    },
  })
}
