export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString()
}

export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

export function humanize(snake: string): string {
  return snake
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function outreachStatusLabel(status: string): string {
  return humanize(status)
}

export function getEnrichmentStatusColor(
  status: string,
): 'success' | 'error' | 'warning' | 'default' {
  switch (status) {
    case 'success':
      return 'success'
    case 'failed':
      return 'error'
    case 'pending':
      return 'warning'
    default:
      return 'default'
  }
}

export function getOutreachStatusColor(
  status: string,
): 'success' | 'info' | 'warning' | 'error' | 'default' {
  switch (status) {
    case 'converted':
      return 'success'
    case 'responded':
      return 'info'
    case 'contacted':
      return 'warning'
    case 'opted_out':
      return 'error'
    default:
      return 'default'
  }
}
