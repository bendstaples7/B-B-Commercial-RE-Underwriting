/** True while the platform is still placing / waiting on the OLC order.

`processing` is retained for legacy rows; writers today use `pending` then
`submitted` / `failed` / `cancelled`.
*/
export function isMailCampaignSubmitting(status: string): boolean {
  return status === 'pending' || status === 'processing'
}

/** Success banner window for recently submitted campaigns (Ready to Mail). */
export const MAIL_SUBMITTED_BANNER_MS = 24 * 60 * 60 * 1000

/** Campaigns still in `submitted` that should surface a success banner. */
export function isRecentMailCampaignSubmitted(
  campaign: { status: string; submitted_at?: string | null; created_at?: string | null },
  nowMs: number = Date.now(),
  windowMs: number = MAIL_SUBMITTED_BANNER_MS,
): boolean {
  if (campaign.status !== 'submitted') return false
  const ts = campaign.submitted_at || campaign.created_at
  if (!ts) return false
  const t = new Date(ts).getTime()
  if (Number.isNaN(t)) return false
  return nowMs - t >= 0 && nowMs - t < windowMs
}

export function mailCampaignStatusLabel(status: string): string {
  switch (status) {
    case 'pending':
    case 'processing':
      return 'Sending…'
    case 'submitted':
      return 'Submitted to Open Letter'
    case 'mailed':
      return 'Mailed'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
    default:
      return status
  }
}

/** Short labels for dense tables (chips). Full copy stays on banners via ``mailCampaignStatusLabel``. */
export function mailCampaignStatusChipLabel(status: string): string {
  switch (status) {
    case 'pending':
    case 'processing':
      return 'Sending…'
    case 'submitted':
      return 'Submitted'
    case 'mailed':
      return 'Mailed'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
    default:
      return status
  }
}

export function mailCampaignStatusColor(
  status: string,
): 'default' | 'success' | 'error' | 'warning' | 'info' {
  switch (status) {
    case 'mailed':
    case 'submitted':
      return 'success'
    case 'failed':
      return 'error'
    case 'pending':
    case 'processing':
      return 'info'
    case 'cancelled':
      return 'default'
    default:
      return 'default'
  }
}
