/**
 * Resolve the Google Maps JS / Places API key for the SPA.
 *
 * Build-time ``VITE_GOOGLE_MAPS_API_KEY`` is preferred. When CI builds without
 * that secret (historically empty in production), fall back to a deploy-injected
 * ``window.__BB_GOOGLE_MAPS_API_KEY__`` or an authenticated backend config fetch.
 */

const PLACEHOLDER = 'your-google-maps-api-key'

declare global {
  interface Window {
    __BB_GOOGLE_MAPS_API_KEY__?: string
  }
}

export function normalizeGoogleMapsApiKey(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const key = raw.trim()
  if (!key || key === PLACEHOLDER) return null
  return key
}

/** Synchronous sources available before any network call. */
export function resolveGoogleMapsApiKeySync(): string | null {
  const fromEnv = normalizeGoogleMapsApiKey(import.meta.env.VITE_GOOGLE_MAPS_API_KEY)
  if (fromEnv) return fromEnv
  if (typeof window !== 'undefined') {
    return normalizeGoogleMapsApiKey(window.__BB_GOOGLE_MAPS_API_KEY__)
  }
  return null
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
