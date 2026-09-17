/**
 * Format a phone number for display as (XXX) XXX-XXXX when possible.
 * Leaves the original string unchanged when the digit count is unrecognized.
 */
export function formatPhoneNumber(phone: string): string {
  if (!phone) return phone
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`
  }
  if (digits.length === 11 && digits.startsWith('1')) {
    return `(${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`
  }
  return phone
}

/** Digits only; strip a leading US country code so 10-digit compares match. */
export function normalizePhoneDigits(phone: string | null | undefined): string {
  const digits = String(phone ?? '').replace(/\D/g, '')
  if (digits.length === 11 && digits.startsWith('1')) return digits.slice(1)
  return digits
}

/** True when two phone strings share the same national digits. */
export function phoneDigitsEqual(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  const left = normalizePhoneDigits(a)
  const right = normalizePhoneDigits(b)
  return left.length >= 7 && left === right
}

/**
 * Pull the first US phone (10 national digits, optional leading 1) from free
 * text (task titles, notes). Ignores shorter digit runs and date-like spans
 * so a title like "Call Sam by 2025-01-15" does not yield a bogus dial target.
 */
export function extractPhoneDigitsFromText(text: string | null | undefined): string | null {
  if (!text) return null
  const matches = String(text).match(/\+?[\d\s().-]{7,}/g)
  if (!matches) return null
  for (const raw of matches) {
    const digits = normalizePhoneDigits(raw)
    if (digits.length === 10) return digits
  }
  return null
}

/**
 * True when a string is phone-shaped (not an email), e.g. misfiled into email_*.
 * Rejects values that contain `@` even if they also have digits.
 */
export function looksLikePhoneNumber(value: string | null | undefined): boolean {
  if (value == null) return false
  const raw = String(value).trim()
  if (!raw || raw.includes('@')) return false
  const digits = raw.replace(/\D/g, '')
  if (digits.length === 10) return true
  if (digits.length === 11 && digits.startsWith('1')) return true
  return false
}

/** Build a tel: href from a display or raw phone string. */
export function phoneTelHref(phone: string): string {
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 10) return `tel:+1${digits}`
  if (digits.length === 11 && digits.startsWith('1')) return `tel:+${digits}`
  if (digits.length > 0) return `tel:${digits}`
  return `tel:${phone}`
}

/** Build an sms: href from a display or raw phone string. */
export function phoneSmsHref(phone: string): string {
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 10) return `sms:+1${digits}`
  if (digits.length === 11 && digits.startsWith('1')) return `sms:+${digits}`
  if (digits.length > 0) return `sms:${digits}`
  return `sms:${phone}`
}

/** Normalize phone for clipboard copy (digits only, with leading +1 for US 10-digit). */
export function phoneCopyText(phone: string): string {
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 10) return `+1${digits}`
  if (digits.length === 11 && digits.startsWith('1')) return `+${digits}`
  return digits || phone
}
