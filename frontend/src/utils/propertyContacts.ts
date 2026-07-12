import type { PropertyContactSummary } from '@/types'

const ENTITY_MARKERS = [
  'LLC',
  'L.L.C',
  'INC',
  'CORP',
  'TRUST',
  'LP',
  'LLP',
  'COMPANY',
  'CO.',
]

const ENTITY_PATTERNS = ENTITY_MARKERS.map((marker) => ({
  marker,
  re: new RegExp(`(?:^|[\\s,])${marker.replace(/\./g, '\\.')}(?:$|[\\s,])`, 'i'),
}))

/** Join first/last into a display name; empty string if both missing. */
export function contactDisplayName(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): string {
  if (!contact) return ''
  return [contact.first_name, contact.last_name].filter(Boolean).join(' ')
}

/** True when a contact name looks like an LLC / corp / trust entity. */
export function isEntityContactName(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): boolean {
  const name = contactDisplayName(contact)
  if (!name) return false
  const upper = name.toUpperCase()
  return ENTITY_PATTERNS.some(({ marker, re }) => {
    return re.test(upper) || upper.endsWith(marker) || upper.includes(` ${marker}`)
  })
}

/**
 * Prefer command-center / property ``contacts[]`` owner-role entries
 * (already primary-first). Falls back to flat owner first/last when owner
 * contacts are absent or unnamed.
 */
export function primaryOwnerDisplayName(
  contacts: PropertyContactSummary[] | undefined | null,
  fallbackFirst?: string | null,
  fallbackLast?: string | null,
): string {
  if (contacts?.length) {
    const owners = contacts.filter(
      (c) => !c.role || c.role === 'owner',
    )
    const ordered = owners.length ? owners : contacts
    for (const contact of ordered) {
      const name = contactDisplayName(contact)
      if (name) return name
    }
  }
  return [fallbackFirst, fallbackLast].filter(Boolean).join(' ')
}
