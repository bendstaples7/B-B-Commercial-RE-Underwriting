import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchGoogleMapsApiKeyFromBackend,
  normalizeGoogleMapsApiKey,
  resolveGoogleMapsApiKeySync,
} from './googleMapsApiKey'

describe('normalizeGoogleMapsApiKey', () => {
  it('rejects empty and placeholder values', () => {
    expect(normalizeGoogleMapsApiKey('')).toBeNull()
    expect(normalizeGoogleMapsApiKey('your-google-maps-api-key')).toBeNull()
    expect(normalizeGoogleMapsApiKey('REPLACE_ME')).toBeNull()
    expect(normalizeGoogleMapsApiKey('  ')).toBeNull()
  })

  it('accepts a real key', () => {
    expect(normalizeGoogleMapsApiKey('AIzaSyExampleKey')).toBe('AIzaSyExampleKey')
  })
})

describe('resolveGoogleMapsApiKeySync', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_GOOGLE_MAPS_API_KEY', '')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    delete window.__BB_GOOGLE_MAPS_API_KEY__
  })

  it('reads deploy-injected window key when vite env is empty/placeholder', () => {
    window.__BB_GOOGLE_MAPS_API_KEY__ = 'AIzaSyFromDeployInject'
    expect(resolveGoogleMapsApiKeySync()).toBe('AIzaSyFromDeployInject')
  })

  it('prefers deploy-injected window key over baked vite env', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_API_KEY', 'AIzaSyFromViteEnv')
    window.__BB_GOOGLE_MAPS_API_KEY__ = 'AIzaSyFromDeployInject'
    expect(resolveGoogleMapsApiKeySync()).toBe('AIzaSyFromDeployInject')
  })

  it('uses vite env when no deploy-injected key is present', () => {
    vi.stubEnv('VITE_GOOGLE_MAPS_API_KEY', 'AIzaSyFromViteEnv')
    expect(resolveGoogleMapsApiKeySync()).toBe('AIzaSyFromViteEnv')
  })
})

describe('fetchGoogleMapsApiKeyFromBackend', () => {
  it('returns the key from /api/config/client', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ google_maps_api_key: 'AIzaSyFromApi' }),
    })
    await expect(fetchGoogleMapsApiKeyFromBackend(fetchImpl as unknown as typeof fetch)).resolves.toBe(
      'AIzaSyFromApi',
    )
    expect(fetchImpl).toHaveBeenCalled()
    const [url] = fetchImpl.mock.calls[0]
    expect(String(url)).toContain('/config/client')
  })

  it('returns null on network/auth failure', async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(fetchGoogleMapsApiKeyFromBackend(fetchImpl as unknown as typeof fetch)).resolves.toBeNull()
  })
})
