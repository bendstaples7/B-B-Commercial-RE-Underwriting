/**
 * Cook County PIN helpers — mirror backend `app.services.plugins.pin_utils`.
 *
 * Canonical display/storage form for 14-digit parcels: XX-XX-XXX-XXX-XXXX
 * (e.g. 14-28-400-008-0000). Non-14-digit values are returned trimmed unchanged.
 */

export function normalizePinDigits(pin: string): string {
  return pin.replace(/[-\s]/g, '').trim()
}

/** Dashed Cook County PIN for display and storage when the value is 14 digits. */
export function formatCookCountyPin(pin: string | null | undefined): string {
  if (pin == null) return ''
  const trimmed = String(pin).trim()
  if (!trimmed) return ''
  const digits = normalizePinDigits(trimmed)
  if (digits.length === 14 && /^\d{14}$/.test(digits)) {
    return `${digits.slice(0, 2)}-${digits.slice(2, 4)}-${digits.slice(4, 7)}-${digits.slice(7, 10)}-${digits.slice(10, 14)}`
  }
  return trimmed
}
