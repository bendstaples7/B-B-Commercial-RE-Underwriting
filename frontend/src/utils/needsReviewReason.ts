/**
 * Shared Needs Review reason labels (queue table + Command Center panel).
 */

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
    return twin
      ? `Duplicate cluster → #${twin}${ids.length ? ` (+${ids.length})` : ''}${confidence}`
      : `Duplicate cluster${confidence}`
  }
  return row.review_reason?.trim() || 'Needs review'
}

export function isDuplicateClusterReason(reason: string | null | undefined): boolean {
  return reason === 'duplicate_lead_cluster'
}
