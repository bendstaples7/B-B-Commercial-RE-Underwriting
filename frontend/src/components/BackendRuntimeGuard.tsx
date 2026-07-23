/**
 * Invisible mount for {@link useBackendRuntimeGuard}.
 *
 * Keeps React Query caches in sync when the backend process restarts (including
 * automatic source_stale restarts). Never renders UI — users must not see
 * “restart required” messaging.
 */
import { useBackendRuntimeGuard } from '@/hooks/useBackendRuntimeGuard'

export function BackendRuntimeGuard() {
  useBackendRuntimeGuard()
  return null
}
