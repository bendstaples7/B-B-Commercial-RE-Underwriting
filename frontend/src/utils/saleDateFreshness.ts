export interface SaleDateMeta {
  last_updated_at?: string | null
  source?: string | null
}

/** Muted caption for when sale date was last updated, e.g. "Updated Mar 2024 · Cook County records". */
export function formatSaleDateFreshness(meta: SaleDateMeta | null | undefined): string | null {
  if (!meta?.last_updated_at) return null
  const updated = new Date(meta.last_updated_at)
  if (Number.isNaN(updated.getTime())) return null
  const monthYear = updated.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
  const source = meta.source?.trim()
  return source ? `Updated ${monthYear} · ${source}` : `Updated ${monthYear}`
}
