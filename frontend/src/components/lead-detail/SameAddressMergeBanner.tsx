/**
 * Same-address duplicate banner + choose-primary merge dialog.
 *
 * Auto-detects same-building twins when the API returns them (blue banner).
 * Manual entry lives on Command Center header overflow (⋯ → Merge duplicate…);
 * open the dialog via controlled `open` / `onOpenChange` from that menu.
 * Dialog search supports name / address / lead #. Opening the dialog loads
 * property, source, portfolio, and activity context for each candidate.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type InputHTMLAttributes } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
  TextField,
  Typography,
} from '@mui/material'
import { alpha } from '@mui/material/styles'
import { LEAD_STATUS_LABELS } from '@/components/LeadStatusChip'
import { commandCenterService, searchService } from '@/services/api'
import type { MergeFieldChoices } from '@/services/api'
import type {
  LeadStatus,
  MergeActivitySummary,
  MergeRelatedProperty,
  SameAddressLeadSummary,
  SearchResultItem,
} from '@/types'
import { formatDate, formatPropertyTypeLabel, humanize } from '@/utils/formatters'
import { formatPhoneNumber, normalizePhoneDigits } from '@/utils/phone'

const SEARCH_DEBOUNCE_MS = 300

export type SameAddressMergedPayload = {
  winnerId: number
  loserId: number
}

export interface SameAddressMergeBannerProps {
  leadId: number
  twins: SameAddressLeadSummary[]
  currentOwnerLabel: string
  currentPeopleNames: string[]
  /**
   * Required: refresh Command Center after merge (same-URL navigate alone is a
   * no-op). Prefer afterCommandCenterMutation via UnifiedLeadCommandCenter.
   */
  onMerged: (payload: SameAddressMergedPayload) => void | Promise<void>
  /** Controlled dialog open (header ⋯ → Merge duplicate…). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Hide the auto-detect banner when a richer duplicate callout is already showing. */
  hideBanner?: boolean
}

function peopleLine(names: string[]): string {
  if (!names.length) return 'No people listed'
  return names.join(', ')
}

function statusLabel(status: string | null | undefined): string {
  if (!status) return ''
  if (Object.hasOwn(LEAD_STATUS_LABELS, status)) {
    return LEAD_STATUS_LABELS[status as LeadStatus]
  }
  return humanize(status)
}

function addressLine(row: SameAddressLeadSummary): string {
  const street = (row.property_street || '').trim()
  const locality = [row.property_city, row.property_state, row.property_zip]
    .map((part) => (part || '').trim())
    .filter(Boolean)
    .join(' ')
  if (street && locality) return `${street}, ${locality}`
  return street || locality || 'No address on file'
}

function sourceToken(raw: string): string {
  const key = raw.trim().toLowerCase()
  if (key === 'hubspot') return 'HubSpot'
  return humanize(raw)
}

function sourceLine(row: SameAddressLeadSummary): string {
  const bits: string[] = []
  const source = (row.source || '').trim()
  const deal = (row.deal_source || '').trim()
  const channel = (row.data_source || '').trim()
  const kind = (row.source_type || '').trim()
  if (source) bits.push(sourceToken(source))
  if (deal && deal.toLowerCase() !== source.toLowerCase()) bits.push(sourceToken(deal))
  if (channel) bits.push(sourceToken(channel))
  if (kind && kind.toLowerCase() !== channel.toLowerCase()) bits.push(sourceToken(kind))
  if (row.hubspot_confirmed) bits.push('HubSpot linked')
  else if (row.date_added_to_hubspot) bits.push('In HubSpot')
  return bits.length ? bits.join(' · ') : 'No source on file'
}

function activityLine(row: SameAddressLeadSummary): string {
  const activity = row.activity
  if (!activity) return ''
  const parts: string[] = []
  if (activity.total > 0) {
    parts.push(`${activity.total} total`)
    if (activity.calls) parts.push(`${activity.calls} call${activity.calls === 1 ? '' : 's'}`)
    if (activity.notes) parts.push(`${activity.notes} note${activity.notes === 1 ? '' : 's'}`)
    if (activity.emails) parts.push(`${activity.emails} email${activity.emails === 1 ? '' : 's'}`)
    if (activity.mail) parts.push(`${activity.mail} mail`)
  }
  const openTasks = row.open_task_count ?? 0
  if (openTasks) parts.push(`${openTasks} open task${openTasks === 1 ? '' : 's'}`)
  if (!parts.length) return 'Activities: none'
  let line = `Activities: ${parts.join(' · ')}`
  const last = (activity.last_summary || '').trim()
  if (last) {
    const when = activity.last_occurred_at ? formatDate(activity.last_occurred_at) : ''
    line += when && when !== '—' ? `. Last ${when}: ${last}` : `. Last: ${last}`
  }
  return line
}

function datesLine(row: SameAddressLeadSummary): string {
  const bits: string[] = []
  if (row.created_at) bits.push(`Added ${formatDate(row.created_at)}`)
  if (row.last_contact_date) bits.push(`Last contact ${formatDate(row.last_contact_date)}`)
  return bits.join(' · ')
}

function relatedValue(row: SameAddressLeadSummary): string {
  const related = row.related_properties
  if (!related?.length) return 'None'
  return related.map((prop) => {
    const street = (prop.property_street || `Lead #${prop.id}`).trim()
    const status = statusLabel(prop.lead_status)
    return status ? `${street} (${status})` : street
  }).join('; ')
}

function activityValue(row: SameAddressLeadSummary): string {
  const line = activityLine(row)
  if (!line || line === 'Activities: none') return 'None'
  return line.replace(/^Activities: /, '')
}

function filledText(
  primary: string | null | undefined,
  incoming: string | null | undefined,
): string | null {
  const kept = (primary ?? '').trim()
  if (kept) return kept
  const fill = (incoming ?? '').trim()
  return fill || null
}

function unionNames(
  left: string[] | null | undefined,
  right: string[] | null | undefined,
): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const name of [...(left ?? []), ...(right ?? [])]) {
    const text = (name || '').trim()
    if (!text) continue
    const key = text.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(text)
  }
  return out
}

const TRAILING_ZIP = /\s+\d{5}(?:-\d{4})?\s*$/

/** Street the merge keeps: drop a trailing ZIP, else a more specific prefix. */
function preferStreet(
  primaryStreet: string | null | undefined,
  incomingStreet: string | null | undefined,
): string | null {
  const primary = (primaryStreet ?? '').trim()
  const incoming = (incomingStreet ?? '').trim()
  if (!primary) return incoming || null
  if (!incoming) return primary
  if (TRAILING_ZIP.test(primary) && !TRAILING_ZIP.test(incoming)) return incoming
  if (incoming.toUpperCase().startsWith(`${primary.toUpperCase()} `)) return incoming
  return primary
}

function unionRelated(
  primary: SameAddressLeadSummary,
  incoming: SameAddressLeadSummary,
): MergeRelatedProperty[] {
  const exclude = new Set([primary.id, incoming.id])
  const seen = new Set<number>()
  const out: MergeRelatedProperty[] = []
  for (const prop of [...(primary.related_properties ?? []), ...(incoming.related_properties ?? [])]) {
    if (!prop || exclude.has(prop.id) || seen.has(prop.id)) continue
    seen.add(prop.id)
    out.push(prop)
  }
  return out
}

function combinedActivity(
  primary: SameAddressLeadSummary,
  incoming: SameAddressLeadSummary,
): MergeActivitySummary | undefined {
  if (primary.activity == null || incoming.activity == null) return undefined
  const kept = primary.activity
  const added = incoming.activity
  const keptAt = kept.last_occurred_at ? Date.parse(kept.last_occurred_at) : Number.NaN
  const addedAt = added.last_occurred_at ? Date.parse(added.last_occurred_at) : Number.NaN
  const incomingLater = !Number.isNaN(addedAt) && (Number.isNaN(keptAt) || addedAt > keptAt)
  const last = incomingLater ? added : kept
  return {
    total: (kept.total || 0) + (added.total || 0),
    calls: (kept.calls || 0) + (added.calls || 0),
    notes: (kept.notes || 0) + (added.notes || 0),
    emails: (kept.emails || 0) + (added.emails || 0),
    mail: (kept.mail || 0) + (added.mail || 0),
    last_occurred_at: last.last_occurred_at ?? null,
    last_summary: last.last_summary ?? null,
    last_event_type: last.last_event_type ?? null,
  }
}

/**
 * Surviving record after merge_lead_into_winner.
 * Status, score, created/last-contact, and non-empty copied fields stay with
 * the primary. People, companies, activities, tasks, and other properties
 * consolidate. data_source / deal_source / source_type are not copied.
 */
function afterCombinePreview(
  primary: SameAddressLeadSummary,
  incoming: SameAddressLeadSummary,
): SameAddressLeadSummary {
  const ready = primary.activity != null && incoming.activity != null
  const units =
    primary.units != null && !Number.isNaN(Number(primary.units))
      ? primary.units
      : (incoming.units ?? null)
  return {
    id: primary.id,
    owner_display_name: primary.owner_display_name,
    people_names: unionNames(primary.people_names, incoming.people_names),
    property_street: preferStreet(primary.property_street, incoming.property_street),
    property_city: filledText(primary.property_city, incoming.property_city),
    property_state: filledText(primary.property_state, incoming.property_state),
    property_zip: filledText(primary.property_zip, incoming.property_zip),
    county_assessor_pin: filledText(primary.county_assessor_pin, incoming.county_assessor_pin),
    property_type: filledText(primary.property_type, incoming.property_type),
    units,
    lead_status: primary.lead_status ?? null,
    lead_score: primary.lead_score ?? null,
    source: filledText(primary.source, incoming.source),
    deal_source: filledText(primary.deal_source, null),
    data_source: filledText(primary.data_source, null),
    source_type: filledText(primary.source_type, null),
    created_at: primary.created_at ?? null,
    last_contact_date: primary.last_contact_date ?? null,
    date_added_to_hubspot: filledText(
      primary.date_added_to_hubspot,
      incoming.date_added_to_hubspot,
    ),
    hubspot_confirmed: Boolean(primary.hubspot_confirmed || incoming.hubspot_confirmed),
    has_phone: Boolean(primary.has_phone || incoming.has_phone || (primary.phones ?? []).length || (incoming.phones ?? []).length),
    has_email: Boolean(primary.has_email || incoming.has_email || (primary.emails ?? []).length || (incoming.emails ?? []).length),
    phones: unionPhones(primary.phones, incoming.phones),
    emails: unionEmails(primary.emails, incoming.emails),
    open_task_count: ready
      ? (primary.open_task_count ?? 0) + (incoming.open_task_count ?? 0)
      : primary.open_task_count,
    organizations: ready
      ? unionNames(primary.organizations, incoming.organizations)
      : primary.organizations,
    activity: combinedActivity(primary, incoming),
    related_properties: ready ? unionRelated(primary, incoming) : primary.related_properties,
  }
}

type FieldPick = { incoming: boolean; primary: boolean }

const MERGE_ROWS: Array<{ key: string; label: string; editable: boolean }> = [
  { key: 'people', label: 'People', editable: true },
  { key: 'property', label: 'This property', editable: true },
  { key: 'pin', label: 'PIN', editable: true },
  { key: 'type', label: 'Type', editable: true },
  { key: 'units', label: 'Units', editable: true },
  { key: 'status', label: 'Status', editable: true },
  { key: 'score', label: 'Score', editable: false },
  { key: 'source', label: 'Source', editable: true },
  { key: 'dates', label: 'Dates', editable: true },
  { key: 'companies', label: 'Companies', editable: true },
  { key: 'related', label: 'Other properties', editable: true },
  { key: 'activities', label: 'Activities', editable: true },
  { key: 'contact', label: 'Contact', editable: true },
]

const CONSOLIDATE_KEYS = new Set(['people', 'companies', 'related', 'activities', 'contact'])
const EMPTY_FIELD_VALUES = new Set([
  '',
  'None',
  'No people listed',
  'No address on file',
  'No source on file',
  '—',
  '…',
])

const MERGE_ROW_GRID = {
  display: 'grid',
  gridTemplateColumns: '112px minmax(0, 1fr) minmax(0, 1fr) minmax(220px, 1.15fr)',
  columnGap: 1,
  alignItems: 'stretch',
  width: '100%',
} as const

function hasFieldValue(value: string): boolean {
  return !EMPTY_FIELD_VALUES.has(value.trim())
}

function fieldValue(row: SameAddressLeadSummary, key: string, ready: boolean): string {
  if (key === 'people') return peopleLine(row.people_names)
  if (key === 'property') return addressLine(row)
  if (key === 'pin') return (row.county_assessor_pin || '').trim() || 'None'
  if (key === 'type') return formatPropertyTypeLabel(row.property_type) || 'None'
  if (key === 'units') {
    if (row.units == null || Number.isNaN(Number(row.units))) return 'None'
    return String(Number(row.units))
  }
  if (key === 'status') return statusLabel(row.lead_status) || 'None'
  if (key === 'score') {
    if (row.lead_score == null || Number.isNaN(Number(row.lead_score))) return 'None'
    return String(Math.round(Number(row.lead_score)))
  }
  if (key === 'contact') return contactLine(row)
  if (!ready) return ''
  if (key === 'source') return sourceLine(row)
  if (key === 'dates') return datesLine(row) || 'None'
  if (key === 'companies') {
    const names = (row.organizations ?? []).map((name) => name.trim()).filter(Boolean)
    return names.length ? names.join(', ') : 'None'
  }
  if (key === 'related') return relatedValue(row)
  if (key === 'activities') return activityValue(row)
  return ''
}

function defaultFieldPick(
  key: string,
  primary: SameAddressLeadSummary,
  incoming: SameAddressLeadSummary,
  ready: boolean,
): FieldPick {
  const primaryValue = fieldValue(primary, key, ready)
  const incomingValue = fieldValue(incoming, key, ready)
  if (!ready && key !== 'people' && key !== 'property') {
    return { incoming: false, primary: false }
  }
  if (CONSOLIDATE_KEYS.has(key)) {
    return {
      primary: hasFieldValue(primaryValue),
      incoming: hasFieldValue(incomingValue),
    }
  }
  const previewValue = fieldValue(afterCombinePreview(primary, incoming), key, ready)
  if (
    hasFieldValue(previewValue)
    && previewValue === incomingValue
    && previewValue !== primaryValue
  ) {
    return { incoming: true, primary: false }
  }
  if (hasFieldValue(primaryValue)) return { incoming: false, primary: true }
  if (hasFieldValue(incomingValue)) return { incoming: true, primary: false }
  return { incoming: false, primary: false }
}

function composeField(
  key: string,
  primary: SameAddressLeadSummary,
  incoming: SameAddressLeadSummary,
  pick: FieldPick,
  ready: boolean,
): string {
  const primaryValue = fieldValue(primary, key, ready)
  const incomingValue = fieldValue(incoming, key, ready)
  if (pick.primary && pick.incoming) {
    if (CONSOLIDATE_KEYS.has(key)) {
      return fieldValue(afterCombinePreview(primary, incoming), key, ready)
    }
    if (!hasFieldValue(primaryValue)) return hasFieldValue(incomingValue) ? incomingValue : ''
    if (!hasFieldValue(incomingValue) || primaryValue === incomingValue) return primaryValue
    return `${primaryValue} · ${incomingValue}`
  }
  if (pick.primary) return primaryValue
  if (pick.incoming) return incomingValue
  return ''
}

function parseAddress(line: string): {
  street: string | null
  city: string | null
  state: string | null
  zip: string | null
} {
  const raw = line.trim()
  if (!hasFieldValue(raw) || raw.includes(' · ')) {
    return { street: hasFieldValue(raw) ? raw : null, city: null, state: null, zip: null }
  }
  const comma = raw.indexOf(',')
  if (comma === -1) return { street: raw, city: null, state: null, zip: null }
  const street = raw.slice(0, comma).trim()
  const parts = raw.slice(comma + 1).trim().split(/\s+/).filter(Boolean)
  let zip: string | null = null
  let state: string | null = null
  if (parts.length && /^\d{5}(?:-\d{4})?$/.test(parts[parts.length - 1])) {
    zip = parts.pop() || null
  }
  if (parts.length && /^[A-Za-z]{2}$/.test(parts[parts.length - 1])) {
    state = (parts.pop() || '').toUpperCase() || null
  }
  const city = parts.join(' ')
  return {
    street: street || null,
    city: city || null,
    state,
    zip,
  }
}

function statusCodeFromLabel(label: string): string | null {
  const trimmed = label.trim()
  if (!hasFieldValue(trimmed)) return null
  for (const [code, text] of Object.entries(LEAD_STATUS_LABELS)) {
    if (text.toLowerCase() === trimmed.toLowerCase()) return code
  }
  return Object.hasOwn(LEAD_STATUS_LABELS, trimmed) ? trimmed : null
}

function typeCodeFromLabel(label: string): string | null {
  const trimmed = label.trim()
  if (!hasFieldValue(trimmed)) return null
  return trimmed.toLowerCase().replace(/\s+/g, '_')
}

function parseUnits(text: string): number | null {
  if (!hasFieldValue(text)) return null
  const match = text.match(/\d+/)
  return match ? Number(match[0]) : null
}

function namesFromDraft(text: string): string[] {
  if (!hasFieldValue(text)) return []
  return text.split(',').map((name) => name.trim()).filter((name) => hasFieldValue(name))
}

function blankToNull(text: string | null | undefined): string | null {
  const value = (text || '').trim()
  return hasFieldValue(value) ? value : null
}

function buildMergeChoices(
  primary: SameAddressLeadSummary,
  incoming: SameAddressLeadSummary,
  picks: Record<string, FieldPick>,
  drafts: Record<string, string>,
  ready: boolean,
): MergeFieldChoices {
  const address = parseAddress(drafts.property || '')
  const sourceDraft = drafts.source || ''
  const primarySource = fieldValue(primary, 'source', ready)
  const incomingSource = fieldValue(incoming, 'source', ready)
  const sourcePick = picks.source || { incoming: false, primary: false }
  let source: string | null
  let dealSource: string | null
  let dataSource: string | null
  if (sourcePick.primary && !sourcePick.incoming && sourceDraft === primarySource) {
    source = blankToNull(primary.source)
    dealSource = blankToNull(primary.deal_source)
    dataSource = blankToNull(primary.data_source)
  } else if (sourcePick.incoming && !sourcePick.primary && sourceDraft === incomingSource) {
    source = blankToNull(incoming.source)
    dealSource = blankToNull(incoming.deal_source)
    dataSource = blankToNull(incoming.data_source)
  } else {
    source = blankToNull(sourceDraft)
    dealSource = null
    dataSource = null
  }
  const statusDraft = drafts.status || ''
  const statusFromPrimary = statusLabel(primary.lead_status)
  const statusFromIncoming = statusLabel(incoming.lead_status)
  const statusPick = picks.status || { incoming: false, primary: false }
  let leadStatus: string | null = statusCodeFromLabel(statusDraft)
  if (statusPick.primary && !statusPick.incoming && statusDraft === statusFromPrimary) {
    leadStatus = primary.lead_status || null
  } else if (statusPick.incoming && !statusPick.primary && statusDraft === statusFromIncoming) {
    leadStatus = incoming.lead_status || null
  }
  const typeDraft = drafts.type || ''
  const typePick = picks.type || { incoming: false, primary: false }
  let propertyType = typeCodeFromLabel(typeDraft)
  if (
    typePick.primary
    && !typePick.incoming
    && typeDraft === (formatPropertyTypeLabel(primary.property_type) || 'None')
  ) {
    propertyType = blankToNull(primary.property_type)
  } else if (
    typePick.incoming
    && !typePick.primary
    && typeDraft === (formatPropertyTypeLabel(incoming.property_type) || 'None')
  ) {
    propertyType = blankToNull(incoming.property_type)
  }
  const peoplePick = picks.people || { incoming: false, primary: false }
  const activityPick = picks.activities || { incoming: false, primary: false }
  const companyPick = picks.companies || { incoming: false, primary: false }
  const contactPick = picks.contact || { incoming: false, primary: false }
  const contactDraft = drafts.contact || ''
  const contactComposed = composeField('contact', primary, incoming, contactPick, ready)
  const methodsKnown = primary.phones != null || incoming.phones != null
    || primary.emails != null || incoming.emails != null
  const contactMethods = methodsKnown || contactDraft !== contactComposed
    ? (contactDraft !== contactComposed
      ? parseContactDraft(contactDraft)
      : checkedContactMethods(contactPick, primary, incoming))
    : null
  return {
    property_street: address.street,
    property_city: address.city,
    property_state: address.state,
    property_zip: address.zip,
    county_assessor_pin: blankToNull((drafts.pin || '').replace(/^PIN\s+/i, '')),
    property_type: propertyType,
    units: parseUnits(drafts.units || ''),
    lead_status: leadStatus,
    source,
    deal_source: dealSource,
    data_source: dataSource,
    people_names: namesFromDraft(drafts.people || ''),
    keep_incoming_people: peoplePick.incoming,
    keep_primary_people: peoplePick.primary,
    keep_incoming_activities: activityPick.incoming,
    keep_primary_activities: activityPick.primary,
    keep_incoming_companies: companyPick.incoming,
    keep_primary_companies: companyPick.primary,
    ...(contactMethods
      ? { phones: contactMethods.phones, emails: contactMethods.emails }
      : {}),
  }
}

function withDecision(
  row: SameAddressLeadSummary,
  detail: SameAddressLeadSummary | undefined,
): SameAddressLeadSummary {
  if (!detail) return row
  return {
    ...row,
    ...detail,
    owner_display_name: detail.owner_display_name || row.owner_display_name,
    people_names: detail.people_names?.length ? detail.people_names : row.people_names,
    property_street: detail.property_street || row.property_street,
  }
}

function unionEmails(
  left: string[] | null | undefined,
  right: string[] | null | undefined,
): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of [...(left ?? []), ...(right ?? [])]) {
    const text = (raw || '').trim()
    if (!text) continue
    const key = text.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(text)
  }
  return out
}

function unionPhones(
  left: string[] | null | undefined,
  right: string[] | null | undefined,
): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of [...(left ?? []), ...(right ?? [])]) {
    const text = (raw || '').trim()
    if (!text) continue
    const key = normalizePhoneDigits(text) || text.toLowerCase()
    if (!key || seen.has(key)) continue
    seen.add(key)
    out.push(text)
  }
  return out
}

function contactLine(row: SameAddressLeadSummary): string {
  const phones = (row.phones ?? [])
    .map((phone) => formatPhoneNumber((phone || '').trim()))
    .filter(Boolean)
  const emails = (row.emails ?? []).map((email) => (email || '').trim()).filter(Boolean)
  const bits = [...phones, ...emails]
  if (!bits.length) {
    if (row.has_phone) bits.push('phone')
    if (row.has_email) bits.push('email')
  }
  return bits.length ? bits.join(' · ') : 'None'
}

function checkedContactMethods(
  pick: FieldPick,
  primary: SameAddressLeadSummary,
  incoming: SameAddressLeadSummary,
): { phones: string[]; emails: string[] } {
  return {
    phones: unionPhones(pick.primary ? primary.phones : [], pick.incoming ? incoming.phones : []),
    emails: unionEmails(pick.primary ? primary.emails : [], pick.incoming ? incoming.emails : []),
  }
}

function parseContactDraft(text: string): { phones: string[]; emails: string[] } {
  const phones: string[] = []
  const emails: string[] = []
  const parts = text.split(/[·;\n]/).map((part) => part.trim()).filter((part) => hasFieldValue(part))
  for (const part of parts) {
    const lower = part.toLowerCase()
    if (lower === 'phone' || lower === 'email') continue
    if (part.includes('@')) {
      emails.push(part)
      continue
    }
    if (normalizePhoneDigits(part).length >= 7) phones.push(part)
  }
  return { phones: unionPhones(phones, []), emails: unionEmails(emails, []) }
}

function checkboxInputProps(
  ariaLabel: string,
  testId: string,
): InputHTMLAttributes<HTMLInputElement> {
  return {
    'aria-label': ariaLabel,
    'data-testid': testId,
  } as InputHTMLAttributes<HTMLInputElement>
}

function searchHitLabel(item: SearchResultItem): string {
  const owner = (item.owner_display_name || item.label || `Lead #${item.id}`).trim()
  const street = (item.property_street || '').trim()
  return street ? `${owner} — ${street} (#${item.id})` : `${owner} (#${item.id})`
}

export function SameAddressMergeBanner({
  leadId,
  twins,
  currentOwnerLabel,
  currentPeopleNames,
  onMerged,
  open: openProp,
  onOpenChange,
  hideBanner = false,
}: SameAddressMergeBannerProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
  const isControlled = openProp !== undefined
  const open = isControlled ? Boolean(openProp) : uncontrolledOpen
  const setOpen = useCallback(
    (next: boolean) => {
      if (!isControlled) setUncontrolledOpen(next)
      onOpenChange?.(next)
    },
    [isControlled, onOpenChange],
  )
  const [winnerId, setWinnerId] = useState<number>(leadId)
  const [removeId, setRemoveId] = useState<number | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [searchHits, setSearchHits] = useState<SearchResultItem[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [selectedHit, setSelectedHit] = useState<SearchResultItem | null>(null)
  const [pastePreview, setPastePreview] = useState<SameAddressLeadSummary | null>(null)
  const [pasteError, setPasteError] = useState<string | null>(null)
  const [pasteLookupPending, setPasteLookupPending] = useState(false)
  const [validatedOtherId, setValidatedOtherId] = useState<number | null>(null)
  const [decisionById, setDecisionById] = useState<Record<number, SameAddressLeadSummary>>({})
  const [contextLoading, setContextLoading] = useState(false)
  const [contextError, setContextError] = useState<string | null>(null)
  const [pickOverride, setPickOverride] = useState<Record<string, FieldPick>>({})
  const [draftOverride, setDraftOverride] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const removeIdRef = useRef<number | null>(null)
  const searchInputRef = useRef('')
  const pasteLookupPromise = useRef<Promise<boolean> | null>(null)
  const pasteLookupRequestId = useRef(0)
  const searchRequestId = useRef(0)
  const contextRequestId = useRef(0)

  const rememberDecision = useCallback((rows: SameAddressLeadSummary[]) => {
    setDecisionById((prev) => {
      const next = { ...prev }
      for (const row of rows) {
        if (!row?.id) continue
        const prior = next[row.id]
        next[row.id] = {
          ...prior,
          ...row,
          owner_display_name: row.owner_display_name || prior?.owner_display_name || `Lead #${row.id}`,
          people_names: row.people_names?.length ? row.people_names : (prior?.people_names ?? []),
          property_street: row.property_street || prior?.property_street || null,
        }
      }
      return next
    })
  }, [])

  const selectRemoveId = useCallback((nextRemoveId: number | null) => {
    removeIdRef.current = nextRemoveId
    setRemoveId(nextRemoveId)
    setPickOverride({})
    setDraftOverride({})
  }, [])

  const first = twins[0]
  const extra = Math.max(0, twins.length - 1)
  const hasTwins = twins.length > 0

  const invalidatePasteLookup = useCallback(() => {
    pasteLookupRequestId.current += 1
    pasteLookupPromise.current = null
    setPasteLookupPending(false)
  }, [])

  const options = useMemo(() => {
    const rows: SameAddressLeadSummary[] = [
      {
        id: leadId,
        property_street: null,
        owner_display_name: currentOwnerLabel || `Lead #${leadId}`,
        people_names: currentPeopleNames,
      },
      ...twins,
    ]
    if (pastePreview && !rows.some((row) => row.id === pastePreview.id)) {
      rows.push(pastePreview)
    }
    return rows
  }, [currentOwnerLabel, currentPeopleNames, leadId, pastePreview, twins])

  const removable = useMemo(
    () => options.filter((row) => row.id !== winnerId),
    [options, winnerId],
  )

  const decisionViews = useMemo(
    () => options.map((row) => withDecision(row, decisionById[row.id])),
    [decisionById, options],
  )
  const primaryView = decisionViews.find((row) => row.id === winnerId) ?? decisionViews[0] ?? null
  const incomingView = decisionViews.find((row) => row.id === removeId)
    ?? decisionViews.find((row) => primaryView != null && row.id !== primaryView.id)
    ?? null
  const compareIncoming = incomingView && primaryView && incomingView.id !== primaryView.id
    ? incomingView
    : null
  const compareReady = Boolean(primaryView?.activity && compareIncoming?.activity)

  const resolvedRows = useMemo(() => {
    if (!primaryView || !compareIncoming) return []
    return MERGE_ROWS.map((row) => {
      const pick = {
        ...defaultFieldPick(row.key, primaryView, compareIncoming, compareReady),
        ...pickOverride[row.key],
      }
      const draft = Object.prototype.hasOwnProperty.call(draftOverride, row.key)
        ? draftOverride[row.key]
        : composeField(row.key, primaryView, compareIncoming, pick, compareReady)
      return { ...row, pick, draft }
    })
  }, [compareIncoming, compareReady, draftOverride, pickOverride, primaryView])

  const contextKey = useMemo(() => {
    const ids = new Set<number>([leadId])
    for (const twin of twins) ids.add(twin.id)
    if (validatedOtherId != null) ids.add(validatedOtherId)
    if (pastePreview?.id) ids.add(pastePreview.id)
    return [...ids]
      .filter((id) => Number.isInteger(id) && id > 0)
      .sort((a, b) => a - b)
      .join(',')
  }, [leadId, pastePreview?.id, twins, validatedOtherId])

  const resetDialogState = useCallback(() => {
    setWinnerId(leadId)
    setError(null)
    setSearchInput('')
    searchInputRef.current = ''
    setSearchHits([])
    setSearchLoading(false)
    setSearchError(null)
    setSelectedHit(null)
    invalidatePasteLookup()
    setPastePreview(null)
    setPasteError(null)
    setValidatedOtherId(null)
    setDecisionById({})
    setContextLoading(false)
    setContextError(null)
    setPickOverride({})
    setDraftOverride({})
    contextRequestId.current += 1
    selectRemoveId(first?.id ?? null)
  }, [first?.id, invalidatePasteLookup, leadId, selectRemoveId])

  useEffect(() => {
    if (!open) return
    resetDialogState()
  }, [open, resetDialogState])

  useEffect(() => {
    if (!open) return
    const requestId = contextRequestId.current + 1
    contextRequestId.current = requestId
    const ids = contextKey
      .split(',')
      .map((part) => Number(part))
      .filter((id) => Number.isInteger(id) && id > 0)
    setContextLoading(true)
    setContextError(null)
    let pending: Promise<{ leads: SameAddressLeadSummary[] }>
    try {
      pending = Promise.resolve(commandCenterService.getMergeContext(leadId, ids))
    } catch {
      if (contextRequestId.current !== requestId) return
      setContextError('Could not load properties, source, and activities.')
      setContextLoading(false)
      return
    }
    void pending
      .then((res) => {
        if (contextRequestId.current !== requestId) return
        rememberDecision(res?.leads ?? [])
        setContextLoading(false)
      })
      .catch(() => {
        if (contextRequestId.current !== requestId) return
        setContextError('Could not load properties, source, and activities.')
        setContextLoading(false)
      })
  }, [contextKey, leadId, open, rememberDecision])

  const closeDialog = useCallback(() => {
    if (saving) return
    setOpen(false)
    // Clear paste/manual twin state on close so cancel + reopen cannot keep
    // a stale lead id if open→true is coalesced before open flips false.
    resetDialogState()
  }, [resetDialogState, saving])

  useEffect(() => {
    if (removeId != null && removable.some((row) => row.id === removeId)) return
    selectRemoveId(removable[0]?.id ?? null)
  }, [removable, removeId, selectRemoveId])

  // Debounced lead search for the manual picker.
  useEffect(() => {
    if (!open) return
    const trimmed = searchInput.trim()
    if (trimmed.length < 2) {
      setSearchHits([])
      setSearchLoading(false)
      setSearchError(null)
      return
    }
    // Pure lead numbers skip typeahead search — validated via merge-preview.
    if (/^\d+$/.test(trimmed)) {
      setSearchHits([])
      setSearchLoading(false)
      setSearchError(null)
      return
    }
    const requestId = searchRequestId.current + 1
    searchRequestId.current = requestId
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => {
      setSearchLoading(true)
      setSearchError(null)
      void searchService
        .search({ q: trimmed, page: 1, per_page: 10, signal: controller.signal })
        .then((response) => {
          if (searchRequestId.current !== requestId) return
          setSearchHits(
            (response.leads ?? []).filter(
              (hit) => hit.type === 'lead' && hit.id !== leadId,
            ),
          )
        })
        .catch(() => {
          if (controller.signal.aborted) return
          if (searchRequestId.current !== requestId) return
          setSearchHits([])
          setSearchError('Search failed. Try again or enter a lead number.')
        })
        .finally(() => {
          if (searchRequestId.current === requestId) setSearchLoading(false)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [leadId, open, searchInput])

  const validateOtherLeadId = async (rawId: string): Promise<boolean> => {
    if (pasteLookupPromise.current) return pasteLookupPromise.current
    const raw = rawId.trim()
    if (!raw) {
      invalidatePasteLookup()
      setPastePreview(null)
      setPasteError(null)
      setValidatedOtherId(null)
      return hasTwins
    }
    const parsed = Number(raw)
    if (!Number.isInteger(parsed) || parsed <= 0 || parsed === leadId) {
      invalidatePasteLookup()
      setPasteError('Enter a different lead number.')
      setPastePreview(null)
      setValidatedOtherId(null)
      return false
    }
    const requestId = pasteLookupRequestId.current + 1
    pasteLookupRequestId.current = requestId
    const isCurrentLookup = () => pasteLookupRequestId.current === requestId
    const lookup = (async () => {
      setPasteLookupPending(true)
      try {
        const preview = await commandCenterService.getMergePreview(leadId, parsed)
        if (!isCurrentLookup()) {
          return false
        }
        if (!preview.same_building && !preview.mergeable) {
          setPasteError('That record is not the same address.')
          setPastePreview(null)
          setValidatedOtherId(null)
          return false
        }
        setPasteError(null)
        setPastePreview(preview.other)
        rememberDecision([preview.current, preview.other].filter(Boolean))
        setValidatedOtherId(parsed)
        selectRemoveId(preview.other.id)
        return true
      } catch (err) {
        if (!isCurrentLookup()) {
          return false
        }
        setPasteError(err instanceof Error ? err.message : 'Could not look up that lead.')
        setPastePreview(null)
        setValidatedOtherId(null)
        return false
      } finally {
        if (pasteLookupRequestId.current === requestId) {
          setPasteLookupPending(false)
          pasteLookupPromise.current = null
        }
      }
    })()
    pasteLookupPromise.current = lookup
    return lookup
  }

  const handleSelectSearchHit = async (hit: SearchResultItem | null) => {
    setSelectedHit(hit)
    invalidatePasteLookup()
    setPastePreview(null)
    setPasteError(null)
    setValidatedOtherId(null)
    setError(null)
    if (!hit) return
    const label = searchHitLabel(hit)
    setSearchInput(label)
    searchInputRef.current = label
    await validateOtherLeadId(String(hit.id))
  }

  const handleWinnerChange = (nextWinnerId: number) => {
    setWinnerId(nextWinnerId)
    setPickOverride({})
    setDraftOverride({})
    if (removeId === nextWinnerId) {
      selectRemoveId(options.find((row) => row.id !== nextWinnerId)?.id ?? null)
    }
  }

  const handleMerge = async () => {
    const rawSearch = searchInput.trim()
    const numericOnly = /^\d+$/.test(rawSearch) ? rawSearch : null
    const needsManualOther = !hasTwins && validatedOtherId == null
    if (needsManualOther && !numericOnly && !selectedHit) {
      setPasteError('Search for the other lead, or type its lead number.')
      setError('Find the other lead to combine.')
      return
    }
    if (validatedOtherId == null && (numericOnly || selectedHit)) {
      const idToValidate = selectedHit ? String(selectedHit.id) : (numericOnly as string)
      const valid = await validateOtherLeadId(idToValidate)
      if (!valid) return
    } else if (pasteLookupPromise.current) {
      const valid = await pasteLookupPromise.current
      if (!valid) return
    } else if (needsManualOther) {
      setPasteError('Search for the other lead, or type its lead number.')
      return
    }

    const stayId = winnerId
    const otherId = removeIdRef.current
    if (!otherId || otherId === stayId) {
      setError('Choose a primary record, and which one to remove.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const choices = primaryView && compareIncoming && compareReady
        ? buildMergeChoices(
          primaryView,
          compareIncoming,
          Object.fromEntries(resolvedRows.map((row) => [row.key, row.pick])),
          Object.fromEntries(resolvedRows.map((row) => [row.key, row.draft])),
          compareReady,
        )
        : undefined
      const result = choices
        ? await commandCenterService.mergeInto(otherId, stayId, choices)
        : await commandCenterService.mergeInto(otherId, stayId)
      const mergedLoserId =
        typeof result.loser_id === 'number' && result.loser_id > 0
          ? result.loser_id
          : otherId
      // Merge already committed — refresh is best-effort so a failed invalidate
      // does not look like a failed combine.
      try {
        await onMerged({
          winnerId: result.winner_id,
          loserId: mergedLoserId,
        })
      } catch {
        // Swallow: merge already committed; parent-owned feedback reports success.
      }
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not combine those records.')
    } finally {
      setSaving(false)
    }
  }

  const bannerDetail = hasTwins
    ? extra
      ? `${first.owner_display_name} (#${first.id}) and ${extra} more`
      : `${first.owner_display_name} (#${first.id})`
    : null

  const searchHelper = pasteLookupPending
    ? 'Checking lead...'
    : (pasteError
      ?? searchError
      ?? (hasTwins
        ? 'Optional — search name, address, or lead # to merge a different twin.'
        : 'Search by name, address, or lead number.'))

  return (
    <>
      {hasTwins && !hideBanner ? (
        <Alert
          severity="info"
          data-testid="same-address-merge-banner"
          sx={{
            cursor: 'auto',
            py: 0.5,
            alignItems: 'center',
            '& .MuiAlert-message': { width: '100%', py: 0.25 },
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 1,
              flexWrap: 'wrap',
            }}
          >
            <Typography variant="body2" sx={{ minWidth: 0 }}>
              Another record for this address: {bannerDetail}
            </Typography>
            <Button
              size="small"
              variant="contained"
              data-testid="same-address-merge-open"
              onClick={() => setOpen(true)}
              sx={{ cursor: 'pointer', flexShrink: 0 }}
            >
              Review merge
            </Button>
          </Box>
        </Alert>
      ) : null}

      <Dialog
        open={open}
        onClose={closeDialog}
        aria-labelledby="same-address-merge-title"
        fullWidth
        maxWidth="xl"
        data-testid="same-address-merge-dialog"
        PaperProps={{ sx: { cursor: 'auto' } }}
      >
        <DialogTitle id="same-address-merge-title">Combine these records</DialogTitle>
        <DialogContent sx={{ cursor: 'auto' }}>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            {hasTwins
              ? 'Choose which record is primary. The other one is removed. People, phones, activities, and tasks move onto the primary. If two rows are the same person they become one person with all phone numbers.'
              : 'Find the other lead for this same building (search or lead number). Choose which record is primary; the other is removed. People, phones, activities, and tasks move onto the primary. If two rows are the same person they become one person with all phone numbers.'}
          </Typography>

          <Autocomplete
            freeSolo
            options={searchHits}
            loading={searchLoading}
            value={selectedHit}
            inputValue={searchInput}
            filterOptions={(opts) => opts}
            getOptionLabel={(option) =>
              typeof option === 'string' ? option : searchHitLabel(option)
            }
            isOptionEqualToValue={(option, value) => option.id === value.id}
            onInputChange={(_event, value, reason) => {
              if (reason === 'reset') return
              searchInputRef.current = value
              setSearchInput(value)
              setSelectedHit(null)
              invalidatePasteLookup()
              setPastePreview(null)
              setPasteError(null)
              setValidatedOtherId(null)
            }}
            onChange={(_event, value) => {
              if (typeof value === 'string') {
                setSelectedHit(null)
                searchInputRef.current = value
                setSearchInput(value)
                if (/^\d+$/.test(value.trim())) {
                  void validateOtherLeadId(value.trim())
                }
                return
              }
              void handleSelectSearchHit(value)
            }}
            onBlur={() => {
              const raw = searchInputRef.current.trim()
              if (/^\d+$/.test(raw) && validatedOtherId == null) {
                void validateOtherLeadId(raw)
              }
            }}
            renderOption={(props, option) => (
              <li
                {...props}
                key={option.id}
                data-testid={`same-address-merge-search-hit-${option.id}`}
              >
                <Box sx={{ py: 0.25 }}>
                  <Typography variant="body2" fontWeight={600}>
                    {option.owner_display_name || option.label} (#{option.id})
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {option.property_street || 'No street on file'}
                  </Typography>
                </Box>
              </li>
            )}
            renderInput={(params) => (
              <TextField
                {...params}
                size="small"
                label="Find the other lead"
                placeholder="Name, address, or lead #"
                error={Boolean(pasteError || searchError)}
                helperText={searchHelper}
                inputProps={{
                  ...params.inputProps,
                  // Keep paste-id test id so numeric-entry tests stay stable.
                  'data-testid': 'same-address-merge-paste-id',
                  style: { ...(params.inputProps.style || {}), cursor: 'text' },
                }}
                InputProps={{
                  ...params.InputProps,
                  endAdornment: (
                    <>
                      {searchLoading || pasteLookupPending ? (
                        <CircularProgress color="inherit" size={16} />
                      ) : null}
                      {params.InputProps.endAdornment}
                    </>
                  ),
                }}
                sx={{ caretColor: 'text.primary' }}
              />
            )}
            sx={{ mt: 0.5 }}
          />

          {pastePreview ? (
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ mt: 1 }}
              data-testid="same-address-merge-search-selected"
            >
              Selected: {pastePreview.owner_display_name} (#{pastePreview.id})
              {pastePreview.property_street ? ` — ${pastePreview.property_street}` : ''}
            </Typography>
          ) : null}

          <FormControl component="fieldset" sx={{ mt: 1.5, display: 'block' }}>
            <FormLabel id="same-address-merge-stay-label" sx={{ mb: 0.5 }}>
              Choose primary
            </FormLabel>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              Each field is one row so you can read across. Check a lead to bring that value in — both can be checked. Edit After combine to set the address, PIN, type, units, status, source, or people. Activity and company checks decide which records move. Score is recalculated. Other properties stay their own leads.
            </Typography>
            <RadioGroup
              aria-labelledby="same-address-merge-stay-label"
              value={String(winnerId)}
              onChange={(event) => handleWinnerChange(Number(event.target.value))}
            >
              <Box data-testid="same-address-merge-compare" sx={{ cursor: 'auto' }}>
                {!compareIncoming || !primaryView ? (
                  <Box
                    data-testid="same-address-merge-incoming-empty"
                    sx={{
                      p: 1.25,
                      borderRadius: 1,
                      border: '1px dashed',
                      borderColor: 'divider',
                      cursor: 'auto',
                    }}
                  >
                    <Typography variant="overline" color="text.secondary">
                      Merges in
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                      Search for the other lead. Its property, source, and activities will show here.
                    </Typography>
                  </Box>
                ) : (
                  <>
                    <Box sx={MERGE_ROW_GRID}>
                      <Box sx={{ cursor: 'auto' }} />
                      <Box
                        component="label"
                        data-testid={`same-address-merge-facts-${compareIncoming.id}`}
                        sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, p: 1, cursor: 'pointer' }}
                      >
                        <Radio
                          value={String(compareIncoming.id)}
                          data-testid={`same-address-merge-stay-${compareIncoming.id}`}
                          inputProps={{ 'aria-label': `Choose #${compareIncoming.id} as primary` }}
                          sx={{ p: 0.25, cursor: 'pointer' }}
                        />
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="overline" color="text.secondary" display="block">
                            Merges in
                          </Typography>
                          <Typography variant="body2" fontWeight={700}>
                            {compareIncoming.owner_display_name} (#{compareIncoming.id})
                            {compareIncoming.id === leadId ? ' · this lead' : ''}
                          </Typography>
                        </Box>
                      </Box>
                      <Box
                        component="label"
                        data-testid={`same-address-merge-facts-${primaryView.id}`}
                        sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, p: 1, cursor: 'pointer', borderRadius: 1, bgcolor: 'action.hover' }}
                      >
                        <Radio
                          value={String(primaryView.id)}
                          data-testid={`same-address-merge-stay-${primaryView.id}`}
                          inputProps={{ 'aria-label': `Choose #${primaryView.id} as primary` }}
                          sx={{ p: 0.25, cursor: 'pointer' }}
                        />
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant="overline" color="primary.main" display="block">
                            Primary
                          </Typography>
                          <Typography variant="body2" fontWeight={700}>
                            {primaryView.owner_display_name} (#{primaryView.id})
                            {primaryView.id === leadId ? ' · this lead' : ''}
                          </Typography>
                        </Box>
                      </Box>
                      <Box
                        data-testid="same-address-merge-after"
                        sx={{
                          p: 1,
                          borderRadius: 1,
                          border: '1px solid',
                          borderColor: 'success.main',
                          bgcolor: (theme) => alpha(theme.palette.success.main, 0.08),
                          cursor: 'auto',
                        }}
                      >
                        <Typography variant="overline" color="success.dark" display="block">
                          After combine
                        </Typography>
                        <Typography variant="body2" fontWeight={700}>
                          {primaryView.owner_display_name} (#{primaryView.id})
                        </Typography>
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          Lead #{compareIncoming.id} is removed. Checked rows come in. Edit a line to override it.
                        </Typography>
                      </Box>
                    </Box>
                    {resolvedRows.map((row) => {
                      const incomingText = fieldValue(compareIncoming, row.key, compareReady)
                      const primaryText = fieldValue(primaryView, row.key, compareReady)
                      const sideText = (value: string) => {
                        if (value) return value
                        if (!compareReady && contextLoading) return 'Loading…'
                        if (!compareReady && contextError) return contextError
                        return '—'
                      }
                      return (
                        <Box
                          key={row.key}
                          data-testid={`same-address-merge-row-${row.key}`}
                          sx={MERGE_ROW_GRID}
                        >
                          <Box sx={{ px: 0.5, py: 0.75, borderTop: '1px solid', borderColor: 'divider', cursor: 'auto' }}>
                            <Typography variant="caption" color="text.secondary">
                              {row.label}
                            </Typography>
                          </Box>
                          <Box sx={{ minWidth: 0, px: 0.5, py: 0.5, borderTop: '1px solid', borderColor: 'divider', display: 'flex', alignItems: 'flex-start', gap: 0.5, cursor: 'auto' }}>
                            <Checkbox
                              size="small"
                              checked={row.pick.incoming}
                              onChange={(event) => {
                                const incoming = event.target.checked
                                setPickOverride((prev) => ({
                                  ...prev,
                                  [row.key]: { ...row.pick, incoming },
                                }))
                                setDraftOverride((prev) => {
                                  const next = { ...prev }
                                  delete next[row.key]
                                  return next
                                })
                              }}
                              inputProps={checkboxInputProps(
                                `Bring ${row.label} from lead #${compareIncoming.id}`,
                                `same-address-merge-pick-${compareIncoming.id}-${row.key}`,
                              )}
                              sx={{ p: 0.25, mt: 0.25, cursor: 'pointer' }}
                            />
                            <Typography variant="body2" sx={{ overflowWrap: 'anywhere', flex: 1, pt: 0.35 }}>
                              {sideText(incomingText)}
                            </Typography>
                          </Box>
                          <Box sx={{ minWidth: 0, px: 0.5, py: 0.5, borderTop: '1px solid', borderColor: 'divider', display: 'flex', alignItems: 'flex-start', gap: 0.5, bgcolor: 'action.hover', cursor: 'auto' }}>
                            <Checkbox
                              size="small"
                              checked={row.pick.primary}
                              onChange={(event) => {
                                const primary = event.target.checked
                                setPickOverride((prev) => ({
                                  ...prev,
                                  [row.key]: { ...row.pick, primary },
                                }))
                                setDraftOverride((prev) => {
                                  const next = { ...prev }
                                  delete next[row.key]
                                  return next
                                })
                              }}
                              inputProps={checkboxInputProps(
                                `Bring ${row.label} from lead #${primaryView.id}`,
                                `same-address-merge-pick-${primaryView.id}-${row.key}`,
                              )}
                              sx={{ p: 0.25, mt: 0.25, cursor: 'pointer' }}
                            />
                            <Typography variant="body2" sx={{ overflowWrap: 'anywhere', flex: 1, pt: 0.35 }}>
                              {sideText(primaryText)}
                            </Typography>
                          </Box>
                          <Box sx={{ minWidth: 0, px: 0.5, py: 0.5, borderTop: '1px solid', borderColor: 'divider', bgcolor: (theme) => alpha(theme.palette.success.main, 0.08), cursor: 'auto' }}>
                            <TextField
                              size="small"
                              fullWidth
                              multiline
                              minRows={1}
                              maxRows={4}
                              disabled={!row.editable}
                              value={row.draft}
                              onChange={(event) => {
                                const value = event.target.value
                                setDraftOverride((prev) => ({ ...prev, [row.key]: value }))
                              }}
                              helperText={row.key === 'score' ? 'Recalculated when you combine' : undefined}
                              inputProps={{
                                'data-testid': `same-address-merge-after-${row.key}`,
                                'aria-label': `After combine ${row.label}`,
                                style: { cursor: row.editable ? 'text' : 'auto' },
                              }}
                              sx={{ caretColor: 'text.primary' }}
                            />
                          </Box>
                        </Box>
                      )
                    })}
                  </>
                )}
              </Box>
            </RadioGroup>
          </FormControl>
          {removable.length > 1 ? (
            <FormControl component="fieldset" sx={{ mt: 1.5, display: 'block' }}>
              <FormLabel id="same-address-merge-remove-label" sx={{ mb: 0.5 }}>
                Which record merges in
              </FormLabel>
              <RadioGroup
                aria-labelledby="same-address-merge-remove-label"
                value={removeId != null ? String(removeId) : ''}
                onChange={(event) => selectRemoveId(Number(event.target.value))}
              >
                {removable.map((row) => (
                  <FormControlLabel
                    key={row.id}
                    value={String(row.id)}
                    control={<Radio data-testid={`same-address-merge-remove-${row.id}`} />}
                    label={
                      <Typography variant="body2">
                        {row.owner_display_name} (#{row.id})
                      </Typography>
                    }
                  />
                ))}
              </RadioGroup>
            </FormControl>
          ) : null}
          {error ? (
            <Typography
              color="error"
              variant="body2"
              sx={{ mt: 1 }}
              data-testid="same-address-merge-error"
            >
              {error}
            </Typography>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog} disabled={saving} sx={{ cursor: 'pointer' }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={() => {
              void handleMerge()
            }}
            disabled={saving}
            data-testid="same-address-merge-confirm"
            sx={{ cursor: 'pointer' }}
          >
            Combine
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

export default SameAddressMergeBanner
