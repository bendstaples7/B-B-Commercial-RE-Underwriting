/**
 * Shared helper functions used across pages.
 */

export function formatCurrency(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** Format an ISO date-only value in local time without a UTC day shift. */
export function formatDateOnly(value: string | null | undefined): string {
  if (!value) return '—'
  const isoDate = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  const date = isoDate
    ? new Date(Date.UTC(
      Number(isoDate[1]),
      Number(isoDate[2]) - 1,
      Number(isoDate[3]),
    ))
    : new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  if (
    isoDate
    && (
      date.getUTCFullYear() !== Number(isoDate[1])
      || date.getUTCMonth() !== Number(isoDate[2]) - 1
      || date.getUTCDate() !== Number(isoDate[3])
    )
  ) return '—'
  return date.toLocaleDateString(
    undefined,
    isoDate ? { timeZone: 'UTC' } : undefined,
  )
}

export function formatPhoneConfidence(
  confidenceScore?: number | null,
  notes?: string | null,
): string {
  const parts: string[] = []
  if (confidenceScore != null) {
    parts.push(`${confidenceScore}%`)
  }
  if (notes?.trim()) {
    parts.push(notes.trim())
  }
  return parts.join(' · ')
}

/**
 * Decode a small set of common HTML entities without using innerHTML
 * (which can rehydrate markup from encoded strings).
 */
function decodeHtmlEntities(text: string): string {
  return text
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#x27;/gi, "'")
    .replace(/&#x([0-9a-f]+);/gi, (match, hex) => {
      const code = Number.parseInt(hex, 16)
      return Number.isFinite(code) && code <= 0x10ffff
        ? String.fromCodePoint(code)
        : match
    })
    .replace(/&#(\d+);/g, (match, n) => {
      const code = Number(n)
      return Number.isFinite(code) && code <= 0x10ffff
        ? String.fromCodePoint(code)
        : match
    })
}

/**
 * Strip tags with quoted attributes (may contain '>').
 * Leaves comparisons like "x < y" / "Cost < $500" alone.
 * Does not use DOMParser/innerHTML — those can request URLs from imgs/iframes.
 */
function stripAngleTags(text: string): string {
  let out = text.replace(/<\s*br\b[^>]*>/gi, '\n')
  out = out.replace(/<\/\s*(p|div|li|tr|h[1-6])\s*>/gi, ' ')
  out = out.replace(/<\/?[a-zA-Z][^>]*?(?:"[^"]*"|'[^']*'|[^>'"])*>/g, '')
  out = out.replace(/<[a-zA-Z/][^>]*$/g, '')
  return out
}

/**
 * Strip HTML tags to plain text for timeline / CRM bodies that arrive as markup.
 * Regex-only (no DOMParser) so HubSpot tracking pixels / remote resources are never fetched.
 */
export function stripHtmlTags(
  rawHtml: string | null | undefined,
  options?: { preserveNewlines?: boolean },
): string {
  if (!rawHtml) return ''
  const preserveNewlines = Boolean(options?.preserveNewlines)
  let text = String(rawHtml)

  for (let i = 0; i < 3; i += 1) {
    const before = text
    text = stripAngleTags(text)
    text = decodeHtmlEntities(text)
    if (text === before) break
  }

  if (preserveNewlines) {
    return text.replace(/[^\S\n]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim()
  }
  return text.replace(/\s+/g, ' ').trim()
}

export function statusColor(status: string): 'default' | 'primary' | 'success' | 'warning' {
  switch (status?.toLowerCase()) {
    case 'active':
      return 'success'
    case 'under_review':
      return 'primary'
    case 'draft':
      return 'warning'
    default:
      return 'default'
  }
}
