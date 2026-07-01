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
    default:
      return 'default'
  }
}
