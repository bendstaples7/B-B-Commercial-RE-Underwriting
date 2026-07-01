/** Format an ISO mail-send timestamp for table display. */
export function formatLastMailedDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString()
}

/** Format an ISO sale date for table display. */
export function formatLastSaleDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (dateOnly) {
    const [, year, month, day] = dateOnly
    const date = new Date(Number(year), Number(month) - 1, Number(day))
    return date.toLocaleDateString()
  }
  return formatLastMailedDate(iso)
}
