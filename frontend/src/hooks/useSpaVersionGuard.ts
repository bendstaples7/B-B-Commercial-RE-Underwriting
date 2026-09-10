import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchSpaVersion,
  isSpaVersionStale,
  readBootSpaBuildId,
} from '@/utils/spaVersion'

const DEFAULT_POLL_MS = 60_000

export type UseSpaVersionGuardOptions = {
  pollMs?: number
  /** Injected for tests. */
  fetchVersion?: typeof fetchSpaVersion
  readBootId?: typeof readBootSpaBuildId
  enabled?: boolean
}

/**
 * Poll for a newer SPA build after deploy. Returns stale=true when this tab's
 * boot build id no longer matches the live manifest (prompt user to reload).
 */
export function useSpaVersionGuard(options?: UseSpaVersionGuardOptions): {
  stale: boolean
  bootBuildId: string | null
  liveBuildId: string | null
  reload: () => void
  dismiss: () => void
  dismissed: boolean
} {
  const pollMs = options?.pollMs ?? DEFAULT_POLL_MS
  const fetchVersion = options?.fetchVersion ?? fetchSpaVersion
  const readBootId = options?.readBootId ?? readBootSpaBuildId
  const enabled = options?.enabled ?? true

  const bootBuildId = useRef<string | null>(null)
  const [liveBuildId, setLiveBuildId] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  /** Build id the user dismissed — re-prompt when a newer live id appears. */
  const [dismissedBuildId, setDismissedBuildId] = useState<string | null>(null)

  // Capture boot id when the guard becomes enabled (ref initializers ignore later flips).
  useEffect(() => {
    if (!enabled) return
    if (bootBuildId.current == null) {
      bootBuildId.current = readBootId()
    }
  }, [enabled, readBootId])

  const check = useCallback(async () => {
    if (!enabled) return
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      return
    }
    if (bootBuildId.current == null) {
      bootBuildId.current = readBootId()
    }
    const live = await fetchVersion()
    if (!live) return
    setLiveBuildId(live.buildId)
    if (isSpaVersionStale(bootBuildId.current, live)) {
      setStale(true)
    }
  }, [enabled, fetchVersion, readBootId])

  useEffect(() => {
    if (!enabled) return
    void check()
    const id = window.setInterval(() => {
      void check()
    }, pollMs)
    const onFocus = () => {
      void check()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      window.clearInterval(id)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [check, enabled, pollMs])

  const reload = useCallback(() => {
    window.location.reload()
  }, [])

  const dismiss = useCallback(() => {
    setDismissedBuildId(liveBuildId)
  }, [liveBuildId])

  const dismissedForLive =
    liveBuildId != null && dismissedBuildId != null && dismissedBuildId === liveBuildId

  return {
    stale: stale && !dismissedForLive,
    bootBuildId: bootBuildId.current,
    liveBuildId,
    reload,
    dismiss,
    dismissed: dismissedForLive,
  }
}
