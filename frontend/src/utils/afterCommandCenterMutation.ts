/**
 * Canonical post-mutation refresh for Command Center.
 *
 * Same-URL navigate is a no-op — always invalidate commandCenter query keys
 * so banners / people / twins cannot stay stale after a successful write.
 */
import type { QueryClient } from '@tanstack/react-query'

export type AfterCommandCenterMutationNavigate = (to: string) => void

export type AfterCommandCenterMutationOptions = {
  winnerId: number
  loserId?: number | null
  /** Optional; still invalidate even when omitted or when already on winner. */
  navigate?: AfterCommandCenterMutationNavigate
}

export function commandCenterQueryKey(leadId: number): readonly ['commandCenter', number] {
  return ['commandCenter', leadId] as const
}

export async function afterCommandCenterMutation(
  queryClient: QueryClient,
  options: AfterCommandCenterMutationOptions,
): Promise<void> {
  const { winnerId, loserId, navigate } = options
  const tasks: Array<Promise<unknown>> = [
    queryClient.invalidateQueries({ queryKey: commandCenterQueryKey(winnerId) }),
  ]
  if (loserId != null && loserId !== winnerId) {
    tasks.push(queryClient.invalidateQueries({ queryKey: commandCenterQueryKey(loserId) }))
  }
  await Promise.all(tasks)
  navigate?.(`/leads/${winnerId}`)
}
