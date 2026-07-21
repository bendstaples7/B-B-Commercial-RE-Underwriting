import type { PropertyContactSummary, PropertyOrganizationSummary } from '@/types'

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

const GENERIC_OWNER_TOKENS = new Set([
  'FSBO',
  'OWNER',
  'UNKNOWN',
  'OCCUPANT',
  'RESIDENT',
  'SELLER',
  'NONE',
  'TBD',
  'EMPTY',
  'NA',
])

const GENERIC_OWNER_PHRASES = [
  'FOR SALE BY OWNER',
  'FOR RENT',
  'FOR LEASE',
  'BARE OWNER',
  'CURRENT RESIDENT',
  'CURRENT OWNER',
  'NO OWNER',
]

const STREET_TOKENS = [
  'ST',
  'STREET',
  'AVE',
  'AVENUE',
  'RD',
  'ROAD',
  'BLVD',
  'BOULEVARD',
  'DR',
  'DRIVE',
  'LN',
  'LANE',
  'CT',
  'COURT',
  'PL',
  'PLACE',
  'WAY',
  'CIR',
  'CIRCLE',
  'PKWY',
  'PARKWAY',
  'HWY',
  'HIGHWAY',
  'TER',
  'TERRACE',
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

/** True for placeholder owner labels that cannot identify a real person. */
export function isGenericOwnerName(name: string | null | undefined): boolean {
  const normalized = (name || '').trim().replace(/\s+/g, ' ')
  if (!normalized) return true
  const upper = normalized.toUpperCase()
  if (GENERIC_OWNER_PHRASES.some((phrase) => upper.includes(phrase))) return true
  return upper
    .split(/\s+/)
    .map((token) => token.replace(/[^A-Z0-9]/g, ''))
    .some((token) => GENERIC_OWNER_TOKENS.has(token))
}

/**
 * True when a name looks like a street address stuffed into owner fields
 * (e.g. ``3508SACRAMENTO MAYNARD`` or ``123 Main St``).
 */
export function isAddressLikeContactName(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): boolean {
  const name = contactDisplayName(contact)
  if (!name) return false
  const upper = name.toUpperCase().trim()
  if (!/\d/.test(upper)) return false

  const tokens = upper.split(/[\s,]+/).filter(Boolean)
  if (tokens.some((t) => STREET_TOKENS.includes(t.replace(/\./g, '')))) return true

  // Mashed house-number + street fragment without spaces: "3508SACRAMENTO"
  if (/\d[A-Z]{3,}/.test(upper.replace(/\s/g, ''))) return true

  // Leading house number + remaining alpha tokens (no entity markers)
  if (/^\d+\s+[A-Z]/.test(upper) && !isEntityContactName(contact)) return true

  return false
}

type OwnerRankTier = 0 | 1 | 2

function ownerRankTier(
  contact: { first_name?: string | null; last_name?: string | null },
): OwnerRankTier {
  if (isAddressLikeContactName(contact)) return 2
  if (isEntityContactName(contact)) return 1
  return 0
}

function ownerContacts(
  contacts: PropertyContactSummary[] | undefined | null,
): PropertyContactSummary[] {
  if (!contacts?.length) return []
  const owners = contacts.filter((c) => !c.role || c.role === 'owner')
  return owners.length ? owners : contacts
}

/**
 * Rank owner contacts for display: person → entity/LLC → address-like.
 * Preserves relative order within each tier.
 */
export function rankOwnersForDisplay(
  contacts: PropertyContactSummary[] | undefined | null,
): PropertyContactSummary[] {
  const owners = ownerContacts(contacts)
  return [...owners].sort((a, b) => ownerRankTier(a) - ownerRankTier(b))
}

export type OwnerDisplayEntry = {
  label: 'Owner' | 'Owner 2' | 'Company' | 'Also listed'
  name: string
  contact?: PropertyContactSummary
  organizationId?: number
}

function normalizeOwnerKey(name: string): string {
  return name.toUpperCase().replace(/[^A-Z0-9]/g, '')
}

/** Identity for person dedupe: first given name + last (ignores middle initials). */
export function personIdentityKey(
  contact: { first_name?: string | null; last_name?: string | null } | null | undefined,
): string {
  if (!contact) return ''
  const last = (contact.last_name || '').toUpperCase().replace(/[^A-Z]/g, '')
  const firstToken = (contact.first_name || '')
    .trim()
    .split(/\s+/)[0]
    ?.toUpperCase()
    .replace(/[^A-Z]/g, '') || ''
  if (!last && !firstToken) return ''
  return `${firstToken}|${last}`
}

/** Identity key from a full display name like ``JOSEPH A KIFERBAUM``. */
export function personIdentityKeyFromFullName(name: string | null | undefined): string {
  const trimmed = (name || '').trim()
  if (!trimmed) return ''
  const parts = trimmed.split(/\s+/).filter(Boolean)
  if (parts.length === 1) {
    return personIdentityKey({ first_name: parts[0], last_name: null })
  }
  return personIdentityKey({
    first_name: parts.slice(0, -1).join(' '),
    last_name: parts[parts.length - 1],
  })
}

/**
 * Labeled owner rows for Command Center:
 * person → Owner / Owner 2, linked orgs → Company, address-like → Also listed.
 */
export function ownerDisplayEntries(
  contacts: PropertyContactSummary[] | undefined | null,
  flatOwner1First?: string | null,
  flatOwner1Last?: string | null,
  flatOwner2First?: string | null,
  flatOwner2Last?: string | null,
  organizations?: PropertyOrganizationSummary[] | null,
): OwnerDisplayEntry[] {
  const ranked = rankOwnersForDisplay(contacts)
  const flatPairs: Array<{ first_name?: string | null; last_name?: string | null }> = [
    { first_name: flatOwner1First, last_name: flatOwner1Last },
    { first_name: flatOwner2First, last_name: flatOwner2Last },
  ]

  const seen = new Set<string>()
  const people: OwnerDisplayEntry[] = []
  const companies: OwnerDisplayEntry[] = []
  const alsoListed: OwnerDisplayEntry[] = []

  const markSeen = (name: string): boolean => {
    const key = normalizeOwnerKey(name)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  }

  for (const org of organizations ?? []) {
    const name = (org.name || '').trim()
    if (!name || !markSeen(name)) continue
    companies.push({
      label: 'Company',
      name,
      organizationId: org.id,
    })
  }

  const considerPair = (
    pair: { first_name?: string | null; last_name?: string | null },
    contact?: PropertyContactSummary,
  ) => {
    const name = contactDisplayName(pair).trim()
    if (!name) return
    const tier = ownerRankTier(pair)
    if (tier === 2) {
      if (!markSeen(name)) return
      alsoListed.push({ label: 'Also listed', name, contact })
      return
    }
    if (tier === 1) {
      // Entity-shaped leftover (pre-migration) — show as Company until org exists
      if (!markSeen(name)) return
      companies.push({ label: 'Company', name, contact })
      return
    }
    if (!markSeen(name)) return
    people.push({
      label: people.length === 0 ? 'Owner' : 'Owner 2',
      name,
      contact,
    })
  }

  for (const contact of ranked) {
    considerPair(contact, contact)
  }
  for (const pair of flatPairs) {
    considerPair(pair)
  }

  // Relabel people after collecting (first Owner, rest Owner 2)
  const labeledPeople = people.map((p, idx) => ({
    ...p,
    label: (idx === 0 ? 'Owner' : 'Owner 2') as OwnerDisplayEntry['label'],
  }))

  return [...labeledPeople, ...companies, ...alsoListed]
}

/**
 * Prefer a real person from contacts; then linked company name; then any named contact.
 * Falls back to flat owner first/last when owner contacts are absent or unnamed.
 */
export function primaryOwnerDisplayName(
  contacts: PropertyContactSummary[] | undefined | null,
  fallbackFirst?: string | null,
  fallbackLast?: string | null,
  organizations?: PropertyOrganizationSummary[] | null,
): string {
  const ranked = rankOwnersForDisplay(contacts)
  for (const contact of ranked) {
    if (isAddressLikeContactName(contact) || isEntityContactName(contact)) continue
    const name = contactDisplayName(contact)
    if (name) return name
  }

  const flat = [fallbackFirst, fallbackLast].filter(Boolean).join(' ')
  if (
    flat
    && !isAddressLikeContactName({ first_name: fallbackFirst, last_name: fallbackLast })
    && !isEntityContactName({ first_name: fallbackFirst, last_name: fallbackLast })
  ) {
    return flat
  }

  const orgName = (organizations ?? []).map((o) => o.name?.trim()).find(Boolean)
  if (orgName) return orgName

  for (const contact of ranked) {
    if (isAddressLikeContactName(contact)) continue
    const name = contactDisplayName(contact)
    if (name) return name
  }
  if (flat) return flat
  for (const contact of ranked) {
    const name = contactDisplayName(contact)
    if (name) return name
  }
  return ''
}
