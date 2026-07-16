export interface SaleDateMeta {
  last_updated_at?: string | null
  last_checked_at?: string | null
  source?: string | null
  status?: string | null
  error_reason?: string | null
}

/** How recently a sale-date check counts as "fresh" for the verified checkmark. */
export const SALE_DATE_RECENT_VERIFICATION_DAYS = 30

/**
 * True when Cook County (or equivalent) verification ran successfully within
 * `days` of `now`. Uses `last_checked_at` only — import updates do not count.
 */
export function isSaleDateVerifiedWithinDays(
  meta: SaleDateMeta | null | undefined,
  days: number = SALE_DATE_RECENT_VERIFICATION_DAYS,
  now: Date = new Date(),
): boolean {
  if (!meta?.last_checked_at) return false
  if (meta.status?.trim() === 'failed') return false
  const checked = new Date(meta.last_checked_at)
  if (Number.isNaN(checked.getTime())) return false
  const ageMs = now.getTime() - checked.getTime()
  if (ageMs < 0) return true
  return ageMs <= days * 24 * 60 * 60 * 1000
}

/** Muted caption for sale-date freshness, e.g. "Last checked Mar 2024 · Cook County records". */
export function formatSaleDateFreshness(meta: SaleDateMeta | null | undefined): string | null {
  const stamp = meta?.last_checked_at || meta?.last_updated_at
  if (!stamp) return null
  const checked = new Date(stamp)
  if (Number.isNaN(checked.getTime())) return null
  const monthYear = checked.toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
  const source = meta?.source?.trim()
  const status = meta?.status?.trim()
  const suffix =
    status === 'no_results'
      ? ' (no sale found)'
      : status === 'failed'
        ? ' (check failed)'
        : ''
  return source
    ? `Last checked ${monthYear} · ${source}${suffix}`
    : `Last checked ${monthYear}${suffix}`
}
