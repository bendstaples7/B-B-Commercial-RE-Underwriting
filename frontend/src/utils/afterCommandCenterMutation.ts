/**
 * Canonical post-mutation refresh for Command Center.
 *
 * Same-URL navigate is a no-op — always invalidate commandCenter query keys
 * so banners / people / twins cannot stay stale after a successful write.
 */
import type { QueryClient } from '@tanstack/react-query'
import type { NavigateOptions } from 'react-router-dom'
import type { FromQueueState } from '@/utils/fromQueue'
import { buildLeadUrl } from '@/utils/queueLogNavigation'

export type AfterCommandCenterMutationNavigate = (to: string, options?: NavigateOptions) => void

export type CommandCenterMutationFlashSnackbar = {
  message: string
  severity?: 'success' | 'warning' | 'error'
  linkTo?: string
  linkLabel?: string
}

export type AfterCommandCenterMutationOptions = {
  winnerId: number
  loserId?: number | null
  /** Optional; still invalidate even when omitted or when already on winner. */
  navigate?: AfterCommandCenterMutationNavigate
  /** Preserve work-queue context when a mutation moves the user to another lead. */
  fromQueue?: FromQueueState | null
  /** Optional destination-owned feedback shown after navigation/remount. */
  flashSnackbar?: CommandCenterMutationFlashSnackbar
}

export function commandCenterQueryKey(leadId: number): readonly ['commandCenter', number] {
  return ['commandCenter', leadId] as const
}

export async function afterCommandCenterMutation(
  queryClient: QueryClient,
  options: AfterCommandCenterMutationOptions,
): Promise<void> {
  const { winnerId, loserId, navigate, fromQueue, flashSnackbar } = options
  const tasks: Array<Promise<unknown>> = [
    queryClient.invalidateQueries({ queryKey: commandCenterQueryKey(winnerId) }),
  ]
  if (loserId != null && loserId !== winnerId) {
    tasks.push(queryClient.invalidateQueries({ queryKey: commandCenterQueryKey(loserId) }))
  }
  // Post-mutation refresh is best-effort: the write already committed, and
  // route repair must still happen if a cache invalidation rejects.
  await Promise.allSettled(tasks)
  if (!navigate) return

  const state = {
    ...(fromQueue ? { fromQueue } : {}),
    ...(flashSnackbar ? { flashSnackbar } : {}),
  }
  const target = buildLeadUrl(winnerId, fromQueue?.key, fromQueue?.outreach)
  if (Object.keys(state).length) {
    navigate(target, { state })
  } else {
    navigate(target)
  }
}
