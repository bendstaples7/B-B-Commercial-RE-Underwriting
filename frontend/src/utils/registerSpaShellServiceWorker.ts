/** Register the SPA shell service worker (production only), with retries. */
export function registerSpaShellServiceWorker(): void {
  if (typeof window === 'undefined') return
  if (!('serviceWorker' in navigator)) return
  if (import.meta.env.DEV) return

  const maxAttempts = 3
  let attempts = 0
  let timer: number | null = null

  const clearTimer = () => {
    if (timer != null) {
      window.clearTimeout(timer)
      timer = null
    }
  }

  const register = () => {
    // Guard before incrementing so a queued timer cannot overrun maxAttempts
    // when focus/visibility already consumed remaining attempts.
    if (attempts >= maxAttempts) return
    if (navigator.serviceWorker.controller) return
    attempts += 1
    void navigator.serviceWorker
      .register('/spa-shell-sw.js')
      .then(() => {
        clearTimer()
      })
      .catch((err) => {
        console.warn(
          `[spa] service worker registration failed (attempt ${attempts}/${maxAttempts})`,
          err,
        )
        if (attempts >= maxAttempts) return
        clearTimer()
        timer = window.setTimeout(register, 1500 * attempts)
      })
  }

  const start = () => {
    register()
    // Retry on next focus/visibility if earlier attempts failed.
    const onVisible = () => {
      if (attempts >= maxAttempts) return
      if (navigator.serviceWorker.controller) return
      // Cancel a pending timer so we don't double-fire past maxAttempts.
      clearTimer()
      register()
    }
    window.addEventListener('focus', onVisible)
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') onVisible()
    })
  }

  if (document.readyState === 'complete') {
    start()
  } else {
    window.addEventListener('load', start, { once: true })
  }
}
