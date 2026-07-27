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

/** Table caption under the Submitted cell (omit when staged === submitted). */
export function formatMailSubmitReconciliationTable(
  campaign: MailSubmitReconciliationFields,
): string | null {
  if (
    campaign.staged_count == null
    || campaign.submitted_count == null
    || campaign.staged_count === campaign.submitted_count
  ) {
    return null
  }
  const drops = formatDropSummary(campaign.submit_drop_summary)
  return (
    `staged ${campaign.staged_count}`
    + (campaign.invalid_at_submit_count
      ? ` · ${campaign.invalid_at_submit_count} invalid`
      : '')
    + (drops ? ` · ${drops}` : '')
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
