/**
 * Dev-only live-UI capture API (window.__bbLiveUi) + metrics helpers.
 * Production builds tree-shake this module via LiveUiCaptureHost DEV gate.
 */
export type LiveUiCaptureResult = {
  ok: boolean
  error?: string
  report?: Record<string, unknown>
  warnClipped?: boolean
}

export type LiveUiSessionResult = {
  ok: boolean
  path?: string
  error?: string
}

declare global {
  interface Window {
    __bbLiveUi?: {
      exportSession: () => Promise<LiveUiSessionResult>
      capture: (opts?: {
        selector?: string
        label?: string
        url?: string
      }) => Promise<LiveUiCaptureResult>
      collectMetrics: (selector?: string) => Record<string, unknown>
      last?: LiveUiCaptureResult | LiveUiSessionResult
    }
  }
}

export function collectLiveUiMetrics(
  selector = '[data-testid="property-overview-header"]',
): Record<string, unknown> {
  const root = document.querySelector(selector)
  if (!root) return { ok: false, error: `missing selector ${selector}` }
  const rootRect = root.getBoundingClientRect()
  const children = [...root.querySelectorAll('[data-testid]')].slice(0, 80).map((el) => {
    const r = el.getBoundingClientRect()
    return {
      testId: el.getAttribute('data-testid'),
      left: r.left,
      right: r.right,
      top: r.top,
      bottom: r.bottom,
      width: r.width,
      height: r.height,
      clippedByRoot:
        r.left + 0.5 < rootRect.left ||
        r.right - 0.5 > rootRect.right ||
        r.top + 0.5 < rootRect.top ||
        r.bottom - 0.5 > rootRect.bottom,
    }
  })
  const clipped = children.filter((c) => c.clippedByRoot)
  return {
    ok: true,
    selector,
    url: location.href,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    root: {
      left: rootRect.left,
      right: rootRect.right,
      top: rootRect.top,
      bottom: rootRect.bottom,
      width: rootRect.width,
      height: rootRect.height,
    },
    clippedCount: clipped.length,
    clippedTestIds: clipped.map((c) => c.testId),
    children,
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = (await res.json().catch(() => ({}))) as T & { error?: string }
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || `HTTP ${res.status}`)
  }
  return data
}

export function installBbLiveUiApi(): void {
  if (typeof window === 'undefined') return

  const api = {
    async exportSession(): Promise<LiveUiSessionResult> {
      const session_token = localStorage.getItem('session_token')
      const user_id = localStorage.getItem('user_id')
      if (!session_token) {
        const fail = { ok: false, error: 'Not logged in (no session_token)' }
        window.__bbLiveUi!.last = fail
        return fail
      }
      try {
        const data = await postJson<LiveUiSessionResult>('/__bb/live-ui/session', {
          session_token,
          user_id,
          origin: location.origin,
        })
        window.__bbLiveUi!.last = data
        return data
      } catch (err) {
        const fail = { ok: false, error: String((err as Error)?.message || err) }
        window.__bbLiveUi!.last = fail
        return fail
      }
    },

    async capture(opts?: {
      selector?: string
      label?: string
      url?: string
    }): Promise<LiveUiCaptureResult> {
      // Ensure agent can re-auth Playwright against this browser session.
      await api.exportSession()
      try {
        const data = await postJson<LiveUiCaptureResult>('/__bb/live-ui/capture', {
          selector: opts?.selector || '[data-testid="property-overview-header"]',
          label: opts?.label || 'capture-fab',
          url: opts?.url || `${location.pathname}${location.search}`,
        })
        window.__bbLiveUi!.last = data
        return data
      } catch (err) {
        const fail = { ok: false, error: String((err as Error)?.message || err) }
        window.__bbLiveUi!.last = fail
        return fail
      }
    },

    collectMetrics(selector?: string) {
      return collectLiveUiMetrics(selector)
    },

    last: undefined as LiveUiCaptureResult | LiveUiSessionResult | undefined,
  }

  window.__bbLiveUi = api
}
