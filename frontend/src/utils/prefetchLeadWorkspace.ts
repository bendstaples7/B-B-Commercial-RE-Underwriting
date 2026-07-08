import type { QueryClient } from '@tanstack/react-query'
import { commandCenterService, leadScoreService, queueService } from '@/services/api'
import { leadService } from '@/services/leadApi'

/** Cache lead workspace data briefly so queue prev/next feels instant. */
export const LEAD_WORKSPACE_STALE_MS = 60_000

export function prefetchLeadWorkspace(queryClient: QueryClient, leadId: number): void {
  if (!Number.isFinite(leadId) || leadId <= 0) return

  void queryClient.prefetchQuery({
    queryKey: ['commandCenter', leadId],
    queryFn: () => commandCenterService.getCommandCenter(leadId),
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })
  void queryClient.prefetchQuery({
    queryKey: ['lead', leadId],
    queryFn: () => leadService.getLeadDetail(leadId),
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })
  void queryClient.prefetchQuery({
    queryKey: ['leadScore', leadId],
    queryFn: async () => (await leadScoreService.getLeadScore(leadId)).data,
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })
}

export function prefetchQueueNavigation(
  queryClient: QueryClient,
  queueKey: string,
  leadId: number,
): void {
  void queryClient.prefetchQuery({
    queryKey: ['queue-navigation', queueKey, leadId],
    queryFn: () => queueService.getNavigation(queueKey, leadId),
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })
}

export function prefetchAdjacentQueueLeads(
  queryClient: QueryClient,
  queueKey: string,
  prevId: number | null | undefined,
  nextId: number | null | undefined,
): void {
  for (const id of [prevId, nextId]) {
    if (id == null) continue
    prefetchLeadWorkspace(queryClient, id)
    prefetchQueueNavigation(queryClient, queueKey, id)
  }
}
