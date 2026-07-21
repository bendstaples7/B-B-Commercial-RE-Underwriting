/**
 * Poll /api/health for backend process identity.
 *
 * - When ``build_id`` changes (backend process restarted), invalidate React Query
 *   caches so queue rows cannot keep stale payloads.
 * - When ``source_stale`` is true (Python sources changed after process start),
 *   surface a banner telling the user to restart the backend.
 */
import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { analysisService } from '@/services/api'
import { useAuth } from '@/context/AuthContext'

const BUILD_ID_STORAGE_KEY = 'bb_backend_build_id'

export type BackendRuntimeHealth = {
  status: string
  build_id?: string
  source_stale?: boolean
  started_at?: string
  pid?: number
  db_mode?: string
}

export function useBackendRuntimeGuard(): {
  sourceStale: boolean
  buildId: string | null
} {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const lastBuildId = useRef<string | null>(
    typeof sessionStorage !== 'undefined'
      ? sessionStorage.getItem(BUILD_ID_STORAGE_KEY)
      : null,
  )

  const { data } = useQuery({
    queryKey: ['backend', 'health', 'runtime'],
    queryFn: () => analysisService.runtimeHealth(),
    enabled: !!user,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: false,
    throwOnError: false,
    staleTime: 10_000,
  })

  useEffect(() => {
    const buildId = data?.build_id
    if (!buildId) return

    const previous = lastBuildId.current
    if (previous && previous !== buildId) {
      // Backend process restarted — drop cached data so no view keeps a stale
      // payload. Scope to data queries: never invalidate this guard's own poll
      // (would loop) and leave auth state intact.
      void queryClient.invalidateQueries({
        predicate: (query) => query.queryKey?.[0] !== 'backend',
      })
    }
    lastBuildId.current = buildId
    try {
      sessionStorage.setItem(BUILD_ID_STORAGE_KEY, buildId)
    } catch {
      // sessionStorage may be unavailable (private mode) — ignore
    }
  }, [data?.build_id, queryClient])

  return {
    sourceStale: Boolean(data?.source_stale),
    buildId: data?.build_id ?? null,
  }
}
