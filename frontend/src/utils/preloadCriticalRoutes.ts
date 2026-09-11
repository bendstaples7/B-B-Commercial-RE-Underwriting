/**
 * Idle-preload high-traffic lazy route shells so first navigation after boot
 * rarely hits a cold dynamic import (after deploy, grace assets + version
 * guard cover the rest).
 */
const CRITICAL_IMPORTS: Array<() => Promise<unknown>> = [
  () => import('@/components/MarketingHub'),
  () => import('@/components/UnifiedLeadCommandCenter'),
  () => import('@/components/TodaysActionQueue'),
  () => import('@/components/PropertyListPage'),
]

export function preloadCriticalRouteChunks(): void {
  if (typeof window === 'undefined') return

  const run = () => {
    for (const load of CRITICAL_IMPORTS) {
      void load().catch(() => {
        // Ignore — chunk miss is handled by lazyWithRetry / version guard.
      })
    }
  }

  const ric = (
    window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number
    }
  ).requestIdleCallback

  if (typeof ric === 'function') {
    ric(run, { timeout: 4000 })
  } else {
    window.setTimeout(run, 1500)
  }
}
