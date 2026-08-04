/**
 * Persisted "sent from" email addresses for the Log Email form.
 *
 * Addresses are stored client-side (localStorage) so a user's outbound
 * mailboxes (e.g. personal + team addresses) persist across sessions
 * without requiring a backend settings table.
 */

export const SENT_FROM_ADDRESSES_STORAGE_KEY = 'bb.email.sentFromAddresses'

function readStorage(): string[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(SENT_FROM_ADDRESSES_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is string => typeof v === 'string' && v.trim().length > 0)
  } catch {
    return []
  }
}

function writeStorage(addresses: string[]): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(SENT_FROM_ADDRESSES_STORAGE_KEY, JSON.stringify(addresses))
  } catch {
    // Ignore storage errors (private browsing, quota exceeded, etc.) —
    // the address is still usable for this session's dropdown selection.
  }
}

/** All persisted "sent from" addresses, most-recently-added last. */
export function getSentFromAddresses(): string[] {
  return readStorage()
}

/** Persist a new "sent from" address (no-op if blank or already saved). */
export function addSentFromAddress(address: string): string[] {
  const trimmed = address.trim()
  if (!trimmed) return readStorage()
  const existing = readStorage()
  if (existing.includes(trimmed)) return existing
  const next = [...existing, trimmed]
  writeStorage(next)
  return next
}
