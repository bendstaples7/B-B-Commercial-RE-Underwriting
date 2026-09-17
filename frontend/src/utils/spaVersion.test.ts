import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchSpaVersion,
  isSpaVersionStale,
  parseSpaVersionPayload,
  readBootSpaBuildId,
  SPA_VERSION_META_NAME,
} from './spaVersion'

describe('spaVersion', () => {
  it('reads boot build id from meta', () => {
    document.head.innerHTML = `<meta name="${SPA_VERSION_META_NAME}" content="abc123" />`
    expect(readBootSpaBuildId(document)).toBe('abc123')
  })

  it('parses camelCase and snake_case payloads', () => {
    expect(parseSpaVersionPayload({ buildId: 'x', builtAt: 't' })).toEqual({
      buildId: 'x',
      builtAt: 't',
    })
    expect(parseSpaVersionPayload({ build_id: 'y', built_at: 'u' })).toEqual({
      buildId: 'y',
      builtAt: 'u',
    })
    expect(parseSpaVersionPayload({})).toBeNull()
  })

  it('detects stale tabs', () => {
    expect(isSpaVersionStale('a', { buildId: 'b' })).toBe(true)
    expect(isSpaVersionStale('a', { buildId: 'a' })).toBe(false)
    expect(isSpaVersionStale(null, { buildId: 'a' })).toBe(false)
  })

  describe('fetchSpaVersion', () => {
    beforeEach(() => {
      vi.restoreAllMocks()
    })
    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('prefers /api/spa-version', async () => {
      const fetchImpl = vi.fn(async (url: string) => {
        if (String(url).includes('/api/spa-version')) {
          return {
            ok: true,
            json: async () => ({ buildId: 'from-api' }),
          }
        }
        throw new Error('should not hit static')
      }) as unknown as typeof fetch
      await expect(fetchSpaVersion(fetchImpl)).resolves.toEqual({
        buildId: 'from-api',
        builtAt: undefined,
      })
    })

    it('falls back to /spa-version.json', async () => {
      const fetchImpl = vi.fn(async (url: string) => {
        if (String(url).includes('/api/spa-version')) {
          return { ok: false, json: async () => ({}) }
        }
        return {
          ok: true,
          json: async () => ({ build_id: 'from-static' }),
        }
      }) as unknown as typeof fetch
      await expect(fetchSpaVersion(fetchImpl)).resolves.toEqual({
        buildId: 'from-static',
        builtAt: undefined,
      })
    })
  })
})
