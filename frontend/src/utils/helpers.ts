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
    .replace(/&#(\d+);/g, (match, n) => {
      const code = Number(n)
      return Number.isFinite(code) ? String.fromCharCode(code) : match
    })
}

/**
 * Strip HTML tags to plain text for timeline / CRM bodies that arrive as markup.
 * Block closers and <br> become spaces; entities are decoded; whitespace collapsed.
 * Safe for use with untrusted CRM HTML (no DOM innerHTML).
 */
export function stripHtmlTags(rawHtml: string | null | undefined): string {
  if (!rawHtml) return ''
  let text = String(rawHtml)
  // Unescape then strip up to 3 times so encoded tags (&lt;b&gt;) cannot survive
  for (let i = 0; i < 3; i += 1) {
    text = text.replace(/<\s*br\s*\/?>/gi, ' ')
    text = text.replace(/<\/\s*(p|div|li|tr|h[1-6])\s*>/gi, ' ')
    text = text.replace(/<[^>]+>/g, '')
    // Truncated CRM bodies may leave an unterminated '<' fragment
    text = text.replace(/<[^>]*$/g, '')
    const decoded = decodeHtmlEntities(text)
    if (decoded === text) break
    text = decoded
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