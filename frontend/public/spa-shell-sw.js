/* spa-shell-sw.js — network-first for HTML navigations; clear stale caches.
 *
 * Hashed /assets/* are intentionally NOT cached here (nginx immutable + browser
 * HTTP cache). This worker keeps document requests off a stale app-shell cache
 * after deploy.
 */
/* eslint-disable no-restricted-globals */
self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys()
      await Promise.all(keys.map((key) => caches.delete(key)))
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return

  const dest = req.destination
  const isDocument =
    req.mode === 'navigate' || dest === 'document' || dest === ''

  const url = new URL(req.url)
  const isVersion =
    url.pathname === '/spa-version.json' || url.pathname === '/api/spa-version'

  if (isDocument || isVersion) {
    event.respondWith(
      fetch(req, { cache: 'no-store' }).catch(() => fetch(req)),
    )
  }
})
