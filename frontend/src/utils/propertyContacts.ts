import type { PropertyContactSummary } from '@/types'

/** Legal-entity suffixes / holding vehicles (aligned with backend owner_name_utils). */
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
  'CO',
]

/** Clear institutions / public bodies / explicit nonprofit language. */
const INSTITUTIONAL_MARKERS = [
  'VILLAGE',
  'COUNTY',
  'CHURCH',
  'SCHOOL',
  'UNIVERSITY',
  'FOUNDATION',
  'MINISTRY',
  'HOSPITAL',
  'NFP',
  'NONPROFIT',
  'ASSOCIATION',
]

const INSTITUTIONAL_PHRASES = [
  'CITY OF',
  'PARK DISTRICT',
  'HOUSING AUTHORITY',
  'NOT FOR PROFIT',
  'NON PROFIT',
  'NON-PROFIT',
]

const ENTITY_PATTERNS = ENTITY_MARKERS.map((marker) => ({
  marker,
  re: new RegExp(`(?:^|[\\s,])${marker.replace(/\./g, '\\.')}(?:$|[\\s,])`, 'i'),
}))

const INSTITUTIONAL_PATTERNS = INSTITUTIONAL_MARKERS.map((marker) => ({
  marker,
  re: new RegExp(`(?:^|[\\s,])${marker.replace(/\./g, '\\.')}(?:$|[\\s,])`, 'i'),
}))

function nameMatchesMarkers(
  upper: string,
  patterns: { marker: string; re: RegExp }[],
): boolean {
  return patterns.some(({ re }) => re.test(upper))
}

/** Join first/last into a display name; empty string if both missing. */
export function contactDisplayName(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): string {
  if (!contact) return ''
  return [contact.first_name, contact.last_name].filter(Boolean).join(' ')
}

/** True when a contact name looks like a public / nonprofit institution. */
export function isInstitutionalContactName(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): boolean {
  const name = contactDisplayName(contact)
  if (!name) return false
  const upper = name.toUpperCase()
  if (INSTITUTIONAL_PHRASES.some((phrase) => upper.includes(phrase))) return true
  return nameMatchesMarkers(upper, INSTITUTIONAL_PATTERNS)
}

/** True when a contact name looks like an LLC / corp / trust / institution. */
export function isEntityContactName(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): boolean {
  if (isInstitutionalContactName(contact)) return true
  const name = contactDisplayName(contact)
  if (!name) return false
  const upper = name.toUpperCase()
  return nameMatchesMarkers(upper, ENTITY_PATTERNS)
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
