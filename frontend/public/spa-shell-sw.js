/* spa-shell-sw.js — network-first for HTML navigations only.
 *
 * Hashed /assets/* are intentionally NOT cached here (nginx immutable + browser
 * HTTP cache). This worker keeps document requests off a stale app-shell cache
 * after deploy. It must not intercept API/XHR/fetch (destination often "").
 */
/* eslint-disable no-restricted-globals */
const SPA_SHELL_CACHE_PREFIX = 'bb-spa-shell-'

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Only clear caches this worker owns — never wipe unrelated origin caches.
      const keys = await caches.keys()
      await Promise.all(
        keys
          .filter((key) => key.startsWith(SPA_SHELL_CACHE_PREFIX))
          .map((key) => caches.delete(key)),
      )
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return

  const dest = req.destination
  // Do NOT treat destination === '' as a document — fetch/Axios GETs use that
  // and must keep normal HTTP caching + not inherit navigation retry policy.
  const isDocument = req.mode === 'navigate' || dest === 'document'

  const url = new URL(req.url)
  const isVersion =
    url.pathname === '/spa-version.json' || url.pathname === '/api/spa-version'

  if (isDocument || isVersion) {
    event.respondWith(
      fetch(req, { cache: 'no-store' }).catch(() => fetch(req)),
    )
  }
})
