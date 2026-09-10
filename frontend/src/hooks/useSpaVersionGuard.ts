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

  // Ref holds the boot id for check() so capturing it does not recreate check
  // and re-fire the polling effect (avoids double /api/spa-version on mount).
  const bootBuildIdRef = useRef<string | null>(null)
  const [bootBuildId, setBootBuildId] = useState<string | null>(null)
  const [liveBuildId, setLiveBuildId] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  /** Build id the user dismissed — re-prompt when a newer live id appears. */
  const [dismissedBuildId, setDismissedBuildId] = useState<string | null>(null)

  const captureBootId = useCallback(() => {
    if (bootBuildIdRef.current != null) return bootBuildIdRef.current
    const id = readBootId()
    bootBuildIdRef.current = id
    setBootBuildId(id)
    return id
  }, [readBootId])

  // Capture boot id when the guard becomes enabled (state for callers; ref for check).
  useEffect(() => {
    if (!enabled) return
    captureBootId()
  }, [captureBootId, enabled])

  const check = useCallback(async () => {
    if (!enabled) return
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      return
    }
    const boot = captureBootId()
    const live = await fetchVersion()
    if (!live) return
    setLiveBuildId(live.buildId)
    if (isSpaVersionStale(boot, live)) {
      setStale(true)
    }
  }, [captureBootId, enabled, fetchVersion])

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
    bootBuildId,
    liveBuildId,
    reload,
    dismiss,
    dismissed: dismissedForLive,
  }
}
