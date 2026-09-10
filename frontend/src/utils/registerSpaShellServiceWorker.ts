/** Register the SPA shell service worker (production only). */
export function registerSpaShellServiceWorker(): void {
  if (typeof window === 'undefined') return
  if (!('serviceWorker' in navigator)) return
  if (import.meta.env.DEV) return

  const register = () => {
    void navigator.serviceWorker.register('/spa-shell-sw.js').catch((err) => {
      console.warn('[spa] service worker registration failed', err)
    })
  }

  if (document.readyState === 'complete') {
    register()
  } else {
    window.addEventListener('load', register, { once: true })
  }
}
