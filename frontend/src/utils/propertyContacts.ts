import type { PropertyContactSummary } from '@/types'

/** Join first/last into a display name; empty string if both missing. */
export function contactDisplayName(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): string {
  if (!contact) return ''
  return [contact.first_name, contact.last_name].filter(Boolean).join(' ')
}

/**
 * Prefer command-center / property ``contacts[]`` (already primary-first).
 * Falls back to flat owner first/last when contacts are absent or unnamed.
 */
export function primaryOwnerDisplayName(
  contacts: PropertyContactSummary[] | undefined | null,
  fallbackFirst?: string | null,
  fallbackLast?: string | null,
): string {
  if (contacts?.length) {
    for (const contact of contacts) {
      const name = contactDisplayName(contact)
      if (name) return name
    }
  }
  return [fallbackFirst, fallbackLast].filter(Boolean).join(' ')
}
