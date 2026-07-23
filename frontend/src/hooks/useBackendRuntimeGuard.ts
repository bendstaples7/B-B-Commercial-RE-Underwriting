/**
 * Poll /api/health for backend process identity.
 *
 * When ``build_id`` changes (backend process restarted — including automatic
 * source_stale restarts), invalidate React Query caches so queue rows cannot
 * keep stale payloads.
 *
 * Never surfaces a “restart required” banner. Local/dev auto-restarts when
 * sources are stale; the UI just refreshes caches after the new build_id.
 */
import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { analysisService } from '@/services/api'
import { useAuth } from '@/context/AuthContext'
import type { RuntimeHealthResponse } from '@/types'

const BUILD_ID_STORAGE_KEY = 'bb_backend_build_id'

function readStoredBuildId(): string | null {
  try {
    if (typeof sessionStorage === 'undefined') return null
    return sessionStorage.getItem(BUILD_ID_STORAGE_KEY)
  } catch {
    return null
  }
}

export type BackendRuntimeHealth = RuntimeHealthResponse

export function useBackendRuntimeGuard(): {
  buildId: string | null
  restartScheduled: boolean
} {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const lastBuildId = useRef<string | null>(readStoredBuildId())

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
    buildId: data?.build_id ?? null,
    restartScheduled: Boolean(data?.restart_scheduled),
  }
}
