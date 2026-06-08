/**
 * Shared helper functions used across pages.
 */

export function formatCurrency(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function statusColor(status: string): 'default' | 'primary' | 'success' | 'warning' {
  switch (status?.toLowerCase()) {
    case 'active':
      return 'success'
    case 'under_review':
      return 'primary'
    case 'draft':
      return 'warning'
    default:
      return 'default'
  }
}