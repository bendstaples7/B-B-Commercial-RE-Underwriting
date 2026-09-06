/**
 * Resolve the Google Maps JS / Places API key for the SPA.
 *
 * Production should prefer the deploy-injected ``window`` key. Vite env keys
 * remain supported for local/dev builds, and authenticated backend config is
 * the async fallback.
 */

import keyPolicy from '../../../google_maps_browser_key_policy.json'

const PLACEHOLDER_VALUES = new Set<string>(keyPolicy.placeholderValues)
const BUILD_TIME_ENV_CANDIDATES = keyPolicy.browserEnvCandidates.filter((name) =>
  name.startsWith('VITE_'),
)

function buildTimeEnvValues(): Record<string, unknown> {
  return {
    VITE_GOOGLE_MAPS_API_KEY: import.meta.env.VITE_GOOGLE_MAPS_API_KEY,
  }
}

declare global {
  interface Window {
    __BB_GOOGLE_MAPS_API_KEY__?: string
  }
}

export function normalizeGoogleMapsApiKey(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const key = raw.trim()
  if (!key || PLACEHOLDER_VALUES.has(key)) return null
  return key
}

function resolveBuildTimeGoogleMapsApiKey(): string | null {
  const values = buildTimeEnvValues()
  for (const name of BUILD_TIME_ENV_CANDIDATES) {
    const key = normalizeGoogleMapsApiKey(values[name])
    if (key) return key
  }
  return null
}

/** Synchronous sources available before any network call. */
export function resolveGoogleMapsApiKeySync(): string | null {
  if (typeof window !== 'undefined') {
    const fromWindow = normalizeGoogleMapsApiKey(window.__BB_GOOGLE_MAPS_API_KEY__)
    if (fromWindow) return fromWindow
  }
  return resolveBuildTimeGoogleMapsApiKey()
}

type ClientConfigResponse = {
  google_maps_api_key?: string | null
}

/**
 * Fetch a browser Maps key from the authenticated backend config endpoint.
 * Returns null when unavailable (missing key, network error, 401, etc.).
 */
export async function fetchGoogleMapsApiKeyFromBackend(
  fetchImpl: typeof fetch = fetch,
): Promise<string | null> {
  try {
    const token =
      typeof localStorage !== 'undefined'
        ? localStorage.getItem('session_token')
        : null
    const headers: Record<string, string> = {
      Accept: 'application/json',
    }
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
    const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')
    const response = await fetchImpl(`${base}/config/client`, {
      method: 'GET',
      headers,
      credentials: 'same-origin',
    })
    if (!response.ok) return null
    const data = (await response.json()) as ClientConfigResponse
    return normalizeGoogleMapsApiKey(data.google_maps_api_key)
  } catch {
    return null
  }
}
