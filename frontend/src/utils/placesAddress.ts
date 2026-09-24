/**
 * Build a street line from Google Places address_components, preserving unit.
 */

const UNIT_MARKER_RE =
  /(?:\b(?:unit|apt|apartment|suite|ste|fl|floor)\b|#)\s*([a-z0-9-]+)/i
/** Bare unit after a street-type token (Place L2, Ave 1A). */
const BARE_AFTER_STREET_RE =
  /\b(?:place|pl|st|street|ave|avenue|rd|road|dr|drive|blvd|ln|ct|court|way|ter|terrace)\b\s+((?:[a-z]\d+[a-z0-9-]*|\d+[a-z][a-z0-9-]*))\b/i
/** Bare trailing unit when the line is already street-only. */
const BARE_TRAILING_RE =
  /\s+((?:[a-z]\d+[a-z0-9-]*|\d+[a-z][a-z0-9-]*))\s*$/i

export type PlacesAddressComponent = {
  long_name?: string
  short_name?: string
  types?: string[]
}

function normalizeUnitToken(raw: string): string {
  return raw.replace(/[^a-z0-9]/gi, '').toLowerCase()
}

/** Extract a comparable unit token from a free-typed street line. */
export function extractUnitToken(street: string | null | undefined): string {
  const full = (street || '').trim()
  if (!full) return ''
  // Work on the pre-comma segment so city/state/ZIP do not block matching.
  const line = full.split(',')[0]?.trim() || full

  const marked = UNIT_MARKER_RE.exec(line)
  if (marked?.[1]) {
    return normalizeUnitToken(marked[1])
  }
  const afterStreet = BARE_AFTER_STREET_RE.exec(line)
  if (afterStreet?.[1]) {
    return normalizeUnitToken(afterStreet[1])
  }
  const trailing = BARE_TRAILING_RE.exec(line)
  if (trailing?.[1]) {
    return normalizeUnitToken(trailing[1])
  }
  return ''
}

/**
 * Canonical FE counterpart to backend ``situs_unit_token_from_parts``:
 * street first, then address line 2.
 */
export function extractUnitTokenFromParts(
  street: string | null | undefined,
  address2: string | null | undefined,
): string {
  return extractUnitToken(street) || extractUnitToken(address2)
}

/**
 * True when ``address_2`` looks like Apt/Unit/Suite (situs line 2), not a
 * HubSpot-style full secondary street that belongs under Additional Address.
 */
const FULL_STREET_HINT_RE =
  /^\d+\s+\S.+\b(?:ave|avenue|st|street|blvd|rd|road|dr|drive|ln|lane|ct|court|pl|place|way|ter|terrace)\b/i

export function isUnitStyleAddressLine(value: string | null | undefined): boolean {
  const raw = (value || '').trim()
  if (!raw) return false
  const lines = raw.split(/[\n;]+/).map((s) => s.trim()).filter(Boolean)
  if (!lines.length) return false
  // Any full-street line → treat the whole field as additional address.
  if (lines.some((line) => FULL_STREET_HINT_RE.test(line))) {
    return false
  }
  return lines.some(
    (line) =>
      Boolean(extractUnitToken(line))
      || /^(?:unit|apt|apartment|suite|ste|#|fl|floor|c\/o|attn|attention)\b/i.test(line),
  )
}

/** Format a unit token for appending to a street (e.g. l2 → Unit L2). */
export function formatUnitSuffix(token: string): string {
  const cleaned = token.replace(/[^a-z0-9-]/gi, '')
  if (!cleaned) return ''
  return `Unit ${cleaned.toUpperCase()}`
}

/**
 * Street line from Places details.
 *
 * Includes ``subpremise`` (apt/unit). When Places omits the unit but the user
 * already typed one (``priorStreet``), that unit is appended so Quick Add does
 * not silently drop condo doors like L2.
 */
export function streetLineFromPlacesComponents(
  components: PlacesAddressComponent[],
  options?: {
    priorStreet?: string | null
    descriptionFallback?: string | null
  },
): string {
  const priorStreet = options?.priorStreet
  const descriptionFallback = options?.descriptionFallback
  const find = (type: string) =>
    components.find((c) => (c.types || []).includes(type))
  const streetNumber = find('street_number')?.long_name
  const route = find('route')?.long_name
  const subpremise =
    find('subpremise')?.long_name
    || find('subpremise')?.short_name
    || null

  let street = [streetNumber, route].filter(Boolean).join(' ').trim()
  if (!street) {
    const guess = (descriptionFallback || '').split(',')[0]?.trim() || ''
    street = guess
  }

  const placesUnit = (subpremise || '').trim()
  if (placesUnit) {
    const already = extractUnitToken(street)
    if (!already) {
      street = `${street} ${placesUnit}`.trim()
    }
    return street
  }

  const priorUnit = extractUnitToken(priorStreet)
  if (priorUnit && !extractUnitToken(street)) {
    street = `${street} ${formatUnitSuffix(priorUnit)}`.trim()
  }
  return street
}
