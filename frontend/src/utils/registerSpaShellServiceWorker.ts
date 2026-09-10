/** Register the SPA shell service worker (production only), with retries. */
export function registerSpaShellServiceWorker(): void {
  if (typeof window === 'undefined') return
  if (!('serviceWorker' in navigator)) return
  if (import.meta.env.DEV) return

  const maxAttempts = 3
  let attempts = 0

  const register = () => {
    attempts += 1
    void navigator.serviceWorker
      .register('/spa-shell-sw.js')
      .catch((err) => {
        console.warn(
          `[spa] service worker registration failed (attempt ${attempts}/${maxAttempts})`,
          err,
        )
        if (attempts >= maxAttempts) return
        window.setTimeout(register, 1500 * attempts)
      })
  }

  const start = () => {
    register()
    // Retry on next focus/visibility if earlier attempts failed.
    const onVisible = () => {
      if (attempts >= maxAttempts) return
      if (navigator.serviceWorker.controller) return
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
