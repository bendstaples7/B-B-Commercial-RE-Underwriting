/**
 * Shared Needs Review reason labels (queue table + Command Center popover).
 */
import type { DuplicateClusterMember, DuplicateClusterPreview, SameAddressLeadSummary } from '@/types'

export const POSSIBLE_DUPLICATE_RECORDS_LABEL = 'Possible duplicate records'

export type DuplicateClusterReasonInput = {
  id?: number | null
  review_reason?: string | null
  suggested_winner_id?: number | null
  duplicate_cluster_ids?: number[] | null
  duplicate_confidence?: string | null
}

export function duplicateConfidenceLabel(confidence: string | null | undefined): string {
  const normalized = String(confidence || '').trim().toLowerCase()
  if (!normalized) return ''
  return normalized === 'ambiguous' ? ' (ambiguous match)' : ` (${normalized} match)`
}

/** Human label for the Needs Review "Review Reason" column / CC callout. */
export function formatNeedsReviewReason(row: DuplicateClusterReasonInput): string {
  if (row.review_reason === 'duplicate_lead_cluster') {
    const twin = row.suggested_winner_id
    const ids = (row.duplicate_cluster_ids ?? []).filter((id) => id !== row.id)
    const confidence = duplicateConfidenceLabel(row.duplicate_confidence)
    const base = POSSIBLE_DUPLICATE_RECORDS_LABEL
    return twin
      ? `${base} → keep #${twin}${ids.length ? ` (+${ids.length})` : ''}${confidence}`
      : `${base}${confidence}`
  }
  return row.review_reason?.trim() || 'Needs review'
}

export function isDuplicateClusterReason(reason: string | null | undefined): boolean {
  return reason === 'duplicate_lead_cluster'
}

function toTwin(member: DuplicateClusterMember | SameAddressLeadSummary): SameAddressLeadSummary {
  return {
    id: member.id,
    property_street: member.property_street,
    owner_display_name: member.owner_display_name,
    people_names: member.people_names ?? [],
  }
}

/** Cluster members other than the open lead, as merge-dialog twins. */
export function duplicateClusterTwins(
  leadId: number,
  cluster: DuplicateClusterPreview | null | undefined,
): SameAddressLeadSummary[] {
  return (cluster?.members ?? [])
    .filter((member) => member.id !== leadId)
    .map(toTwin)
}

/** Union situs twins with Needs Review cluster members (cluster fills husk vs unit). */
export function mergeDuplicateTwins(
  leadId: number,
  sameAddress: SameAddressLeadSummary[] | null | undefined,
  cluster: DuplicateClusterPreview | null | undefined,
): SameAddressLeadSummary[] {
  const byId = new Map<number, SameAddressLeadSummary>()
  for (const row of sameAddress ?? []) {
    if (row.id === leadId) continue
    byId.set(row.id, row)
  }
  for (const row of duplicateClusterTwins(leadId, cluster)) {
    const existing = byId.get(row.id)
    if (!existing) {
      byId.set(row.id, row)
      continue
    }
    if (!(existing.people_names?.length) && row.people_names.length) {
      byId.set(row.id, { ...existing, people_names: row.people_names })
    }
  }
  return [...byId.values()]
}
