export interface SaleDateMeta {
  last_updated_at?: string | null
  last_checked_at?: string | null
  source?: string | null
  status?: string | null
  error_reason?: string | null
}

export interface SaleDateFreshnessOptions {
  /** True when Most Recent Sale shows a date (not None / empty). */
  hasDisplayedSale?: boolean
}

/** How recently a sale-date check counts as "fresh" for the verified checkmark. */
export const SALE_DATE_RECENT_VERIFICATION_DAYS = 30

function isRecentCheck(
  meta: SaleDateMeta | null | undefined,
  days: number,
  now: Date,
): boolean {
  if (!meta?.last_checked_at) return false
  const checked = new Date(meta.last_checked_at)
  if (Number.isNaN(checked.getTime())) return false
  const ageMs = now.getTime() - checked.getTime()
  if (ageMs < 0) return true
  return ageMs <= days * 24 * 60 * 60 * 1000
}

function formatMonthYear(stamp: string): string | null {
  const checked = new Date(stamp)
  if (Number.isNaN(checked.getTime())) return null
  return checked.toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/**
 * True when Cook County verification confirmed a sale, or confirmed no sale
 * while none is displayed. Uses `last_checked_at` only — import updates do not count.
 */
export function isSaleDateVerifiedWithinDays(
  meta: SaleDateMeta | null | undefined,
  days: number = SALE_DATE_RECENT_VERIFICATION_DAYS,
  now: Date = new Date(),
  options: SaleDateFreshnessOptions = {},
): boolean {
  if (!isRecentCheck(meta, days, now)) return false
  const status = meta?.status?.trim()
  if (status === 'failed') return false
  if (status === 'success') return true
  if (status === 'no_sale') return options.hasDisplayedSale !== true
  return false
}

/**
 * One-line muted caption for sale-date freshness.
 * Unconfirmed probes say "Cannot confirm as of …" — never "Last checked" alone.
 */
export function formatSaleDateFreshness(
  meta: SaleDateMeta | null | undefined,
  options: SaleDateFreshnessOptions = {},
): string | null {
  const isChecked = Boolean(meta?.last_checked_at)
  const stamp = meta?.last_checked_at || meta?.last_updated_at
  if (!stamp) return null
  const monthYear = formatMonthYear(stamp)
  if (!monthYear) return null
  const status = meta?.status?.trim()

  if (isChecked && status === 'failed') {
    return `Check failed as of ${monthYear}`
  }
  if (isChecked && status === 'no_sale') {
    return options.hasDisplayedSale === true
      ? `Cannot confirm as of ${monthYear}`
      : `No sale found as of ${monthYear}`
  }
  if (isChecked && status === 'success') {
    return `Confirmed as of ${monthYear}`
  }
  if (isChecked) {
    return `Checked as of ${monthYear}`
  }
  return `Updated ${monthYear}`
}
