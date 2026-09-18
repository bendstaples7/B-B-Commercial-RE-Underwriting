/** Product clock times display in US Central (America/Chicago). */
export const BUSINESS_TIME_ZONE = 'America/Chicago'

const DATE_ONLY_SLASH_RE = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/
const DATE_ONLY_ISO_RE = /^(\d{4})-(\d{2})-(\d{2})$/
const NAIVE_ISO_DATETIME_RE = /^\d{4}-\d{2}-\d{2}T/
const HAS_TZ_RE = /(Z|[+-]\d{2}:?\d{2})$/i

const CALENDAR_DATE_OPTS: Intl.DateTimeFormatOptions = {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
}

const CENTRAL_DATE_TIME_OPTS: Intl.DateTimeFormatOptions = {
  timeZone: BUSINESS_TIME_ZONE,
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
}

export interface FormatDateTimeOptions {
  /** Split calendar date and clock+zone onto two lines for narrow tables. */
  multiline?: boolean
  /** Include seconds (webhook event logs). Default is minute precision. */
  seconds?: boolean
}

function formatCalendarDay(year: number, month: number, day: number): string {
  const utc = new Date(Date.UTC(year, month - 1, day))
  if (
    Number.isNaN(utc.getTime())
    || utc.getUTCFullYear() !== year
    || utc.getUTCMonth() !== month - 1
    || utc.getUTCDate() !== day
  ) {
    return '—'
  }
  return utc.toLocaleDateString('en-US', {
    timeZone: 'UTC',
    ...CALENDAR_DATE_OPTS,
  })
}

/**
 * Expand 2-digit years with a Windows-style pivot: 00–68 → 2000s, 69–99 → 1900s.
 * Mail history is historical, so `6/21/99` is 1999 (not 2099).
 */
function expandTwoDigitYear(year: number): number {
  if (year >= 100) return year
  return year <= 68 ? 2000 + year : 1900 + year
}

function parseSlashDate(text: string): { year: number; month: number; day: number } | null {
  const slash = DATE_ONLY_SLASH_RE.exec(text)
  if (!slash) return null
  const month = Number(slash[1])
  const day = Number(slash[2])
  const year = expandTwoDigitYear(Number(slash[3]))
  if (formatCalendarDay(year, month, day) === '—') return null
  return { year, month, day }
}

/**
 * Parse ISO or US slash dates for display. Naive ISO datetimes are UTC.
 * Date-only values are calendar days (UTC midnight of that date).
 */
export function parseDisplayTimestamp(value: unknown): Date | null {
  if (value == null) return null
  const text = String(value).trim()
  if (!text) return null
  const slashMatch = DATE_ONLY_SLASH_RE.exec(text)
  if (slashMatch) {
    const slash = parseSlashDate(text)
    if (!slash) return null
    return new Date(Date.UTC(slash.year, slash.month - 1, slash.day))
  }
  const isoDate = DATE_ONLY_ISO_RE.exec(text)
  if (isoDate) {
    const year = Number(isoDate[1])
    const month = Number(isoDate[2])
    const day = Number(isoDate[3])
    if (formatCalendarDay(year, month, day) === '—') return null
    return new Date(Date.UTC(year, month - 1, day))
  }
  const isoText =
    NAIVE_ISO_DATETIME_RE.test(text) && !HAS_TZ_RE.test(text) ? `${text}Z` : text
  const ms = Date.parse(isoText)
  if (!Number.isNaN(ms)) return new Date(ms)
  return null
}

/**
 * Calendar date for UI. Date-only values keep the written day (no TZ shift).
 * Datetimes use the US Central calendar day of that instant.
 */
export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const text = String(dateStr).trim()
  if (!text) return '—'
  const slash = parseSlashDate(text)
  if (slash) return formatCalendarDay(slash.year, slash.month, slash.day)
  const isoDate = DATE_ONLY_ISO_RE.exec(text)
  if (isoDate) {
    return formatCalendarDay(
      Number(isoDate[1]),
      Number(isoDate[2]),
      Number(isoDate[3]),
    )
  }
  const parsed = parseDisplayTimestamp(text)
  if (!parsed) return '—'
  return parsed.toLocaleDateString('en-US', {
    timeZone: BUSINESS_TIME_ZONE,
    ...CALENDAR_DATE_OPTS,
  })
}

/** Alias of formatDate — ISO date-only strings stay calendar dates. */
export function formatDateOnly(value: string | null | undefined): string {
  return formatDate(value)
}

/**
 * Clock time for UI in US Central Time (CDT/CST).
 * Date-only values stay calendar dates (no invented clock time).
 */
export function formatDateTime(
  dateStr: string | null | undefined,
  options?: FormatDateTimeOptions,
): string {
  if (!dateStr) return '—'
  const text = String(dateStr).trim()
  if (!text) return '—'
  if (DATE_ONLY_SLASH_RE.test(text) || DATE_ONLY_ISO_RE.test(text)) {
    return formatDate(text)
  }
  const parsed = parseDisplayTimestamp(text)
  if (!parsed) return '—'
  const opts: Intl.DateTimeFormatOptions = options?.seconds
    ? { ...CENTRAL_DATE_TIME_OPTS, second: '2-digit' }
    : CENTRAL_DATE_TIME_OPTS
  const formatted = parsed.toLocaleString('en-US', opts)
  if (options?.multiline) {
    return formatted.replace(/, (?=\d{1,2}:)/, '\n')
  }
  return formatted
}

export function humanize(snake: string): string {
  return snake
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Title-case property type for display (triplex → Triplex, multi_family → Multi Family). */
export function formatPropertyTypeLabel(raw: string | null | undefined): string {
  if (!raw) return ''
  return raw
    .trim()
    .split(/[\s_]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

/** Residential / Commercial (and other lead_category values) for header KPI. */
export function formatLeadCategoryLabel(raw: string | null | undefined): string {
  if (!raw) return ''
  const key = raw.trim().toLowerCase()
  if (key === 'residential') return 'Residential'
  if (key === 'commercial') return 'Commercial'
  return formatPropertyTypeLabel(raw)
}

export function outreachStatusLabel(status: string): string {
  return humanize(status)
}

export function getEnrichmentStatusColor(
  status: string,
): 'success' | 'error' | 'warning' | 'default' {
  switch (status) {
    case 'success':
      return 'success'
    case 'failed':
      return 'error'
    case 'pending':
      return 'warning'
    default:
      return 'default'
  }
}

export function getOutreachStatusColor(
  status: string,
): 'success' | 'info' | 'warning' | 'error' | 'default' {
  switch (status) {
    case 'converted':
      return 'success'
    case 'responded':
      return 'info'
    case 'contacted':
      return 'warning'
    case 'opted_out':
      return 'error'
    default:
      return 'default'
  }
}

/** Currency display with whole-dollar rounding (shared by Quick Stats + At a glance). */
export function formatMoneyValue(value: number | string | null | undefined): string | null {
  if (value == null || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return null
  return `$${Math.round(n).toLocaleString()}`
}

/** Assessor PIN row street (+ unit/apt when present) — condo/ownership PIN tables. */
export function formatAssessorPinAddress(row: {
  property_street?: string | null
  unit?: string | null
  apt?: string | null
} | null | undefined): string {
  const street = row?.property_street?.trim()
  if (!street) return '—'
  const unit = (row?.unit || row?.apt)?.toString().trim()
  return unit ? `${street}, ${unit}` : street
}
