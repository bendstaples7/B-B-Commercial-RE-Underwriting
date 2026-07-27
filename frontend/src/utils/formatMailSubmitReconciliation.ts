/** Shared copy for staged → submitted reconciliation captions. */

export type MailSubmitReconciliationFields = {
  staged_count?: number | null
  submitted_count?: number | null
  invalid_at_submit_count?: number | null
  submit_drop_summary?: Record<string, number> | null
}

function formatDropSummary(
  summary: Record<string, number> | null | undefined,
): string {
  if (!summary) return ''
  const entries = Object.entries(summary)
  if (!entries.length) return ''
  return entries.map(([reason, n]) => `${n}× ${reason}`).join(', ')
}

export type MailSubmitReconciliationParts = {
  stagedLabel: string
  invalidCount: number
  invalidLabel: string | null
  dropSummary: string
}

/** Structured parts for clickable “N invalid” in the batches table. */
export function mailSubmitReconciliationParts(
  campaign: MailSubmitReconciliationFields,
): MailSubmitReconciliationParts | null {
  if (
    campaign.staged_count == null
    || campaign.submitted_count == null
    || campaign.staged_count === campaign.submitted_count
  ) {
    return null
  }
  const invalidCount = campaign.invalid_at_submit_count || 0
  return {
    stagedLabel: `staged ${campaign.staged_count}`,
    invalidCount,
    invalidLabel: invalidCount > 0 ? `${invalidCount} invalid` : null,
    dropSummary: formatDropSummary(campaign.submit_drop_summary),
  }
}

/** Table caption under the Submitted cell (omit when staged === submitted). */
export function formatMailSubmitReconciliationTable(
  campaign: MailSubmitReconciliationFields,
): string | null {
  const parts = mailSubmitReconciliationParts(campaign)
  if (!parts) return null
  return (
    parts.stagedLabel
    + (parts.invalidLabel ? ` · ${parts.invalidLabel}` : '')
    + (parts.dropSummary ? ` · ${parts.dropSummary}` : '')
  )
}

/** Banner suffix after “order accepted …” (leading middle-dot included). */
export function formatMailSubmitReconciliationBanner(
  campaign: MailSubmitReconciliationFields,
): string {
  if (
    campaign.staged_count == null
    || campaign.submitted_count == null
    || campaign.staged_count === campaign.submitted_count
  ) {
    return ''
  }
  const drops = formatDropSummary(campaign.submit_drop_summary)
  return (
    ` · Staged ${campaign.staged_count} → submitted ${campaign.submitted_count}`
    + (campaign.invalid_at_submit_count
      ? ` (${campaign.invalid_at_submit_count} invalid locally)`
      : '')
    + (drops ? ` · ${drops}` : '')
  )
}
