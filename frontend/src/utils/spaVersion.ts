/**
 * SPA build identity — detects post-deploy stale tabs before lazy imports 404.
 *
 * Prefer /api/spa-version (Cache-Control: no-store from Flask). Fall back to
 * /spa-version.json with fetch cache: 'no-store'.
 */
export type SpaVersionPayload = {
  buildId: string
  builtAt?: string
}

export const SPA_VERSION_META_NAME = 'spa-build-id'

export function readBootSpaBuildId(
  doc: Document = document,
): string | null {
  const meta = doc.querySelector(`meta[name="${SPA_VERSION_META_NAME}"]`)
  const content = meta?.getAttribute('content')?.trim()
  return content || null
}

export function parseSpaVersionPayload(data: unknown): SpaVersionPayload | null {
  if (!data || typeof data !== 'object') return null
  const buildId = (data as { buildId?: unknown; build_id?: unknown }).buildId
    ?? (data as { build_id?: unknown }).build_id
  if (typeof buildId !== 'string' || !buildId.trim()) return null
  const builtAt = (data as { builtAt?: unknown; built_at?: unknown }).builtAt
    ?? (data as { built_at?: unknown }).built_at
  return {
    buildId: buildId.trim(),
    builtAt: typeof builtAt === 'string' ? builtAt : undefined,
  }
}

export async function fetchSpaVersion(
  fetchImpl: typeof fetch = fetch,
): Promise<SpaVersionPayload | null> {
  const tryUrl = async (url: string): Promise<SpaVersionPayload | null> => {
    const res = await fetchImpl(url, {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
    if (!res.ok) return null
    return parseSpaVersionPayload(await res.json())
  }

  try {
    const fromApi = await tryUrl('/api/spa-version')
    if (fromApi) return fromApi
  } catch {
    // fall through
  }
  try {
    return await tryUrl('/spa-version.json')
  } catch {
    return null
  }
}

/** True when the live build id differs from what this tab booted with. */
export function isSpaVersionStale(
  bootBuildId: string | null,
  live: SpaVersionPayload | null,
): boolean {
  if (!bootBuildId || !live?.buildId) return false
  return bootBuildId !== live.buildId
}
