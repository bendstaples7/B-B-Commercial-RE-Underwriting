/**
 * Fail-closed scoping for lead-detail rows.
 *
 * Queue advance historically reused Command Center local state and could paint
 * another lead's timeline/tasks. Never render a row whose `lead_id` is set to a
 * different lead than the one on screen.
 */
export type LeadScopedRow = {
  /** Timeline/task ids may be numeric or HubSpot string ids. */
  id?: number | string
  lead_id?: number | null
}

export type PartitionedLeadRows<T extends LeadScopedRow> = {
  kept: T[]
  dropped: T[]
}

/** Last reported drop signature per surface+lead — avoids console spam on re-render. */
const lastReportedDropSig = new Map<string, string>()

/** Test-only: clear report dedupe cache. */
export function resetLeadScopeReportCacheForTests(): void {
  lastReportedDropSig.clear()
}

export function partitionRowsByLead<T extends LeadScopedRow>(
  rows: readonly T[],
  leadId: number,
): PartitionedLeadRows<T> {
  const kept: T[] = []
  const dropped: T[] = []
  for (const row of rows) {
    if (row.lead_id != null && row.lead_id !== leadId) {
      dropped.push(row)
    } else {
      kept.push(row)
    }
  }
  return { kept, dropped }
}

/**
 * Log foreign rows once per distinct drop set (surface + lead + dropped ids).
 * Cleared automatically when a later call finds nothing to drop for that key.
 */
export function reportForeignLeadRows(
  dropped: readonly LeadScopedRow[],
  leadId: number,
  surface: string,
): void {
  const key = `${surface}:${leadId}`
  if (dropped.length === 0) {
    lastReportedDropSig.delete(key)
    return
  }
  const ids = dropped
    .map((r) => r.id)
    .filter((id): id is number | string => id != null)
    .map(String)
    .sort()
  const sig = ids.join(',') || `count:${dropped.length}`
  if (lastReportedDropSig.get(key) === sig) return
  lastReportedDropSig.set(key, sig)
  console.error(
    `[lead-scope] Dropped ${dropped.length} ${surface} row(s) with foreign lead_id `
    + `(active=${leadId}, dropped_ids=${ids.join(',') || 'unknown'})`,
  )
}

/**
 * When foreign rows were stripped from a local list, shrink the badge/total so
 * "Load more" / counts do not claim rows that were never for this lead.
 * Partial pages with zero drops keep the server total unchanged.
 */
export function scopedListTotal(
  serverTotal: number,
  keptCount: number,
  droppedCount: number,
): number {
  if (droppedCount <= 0) return serverTotal
  return Math.max(keptCount, serverTotal - droppedCount)
}

/**
 * Returns only rows that belong to `leadId` (or lack `lead_id`).
 * Foreign `lead_id` values are dropped and reported via `console.error` (deduped).
 */
export function scopeRowsToLead<T extends LeadScopedRow>(
  rows: readonly T[],
  leadId: number,
  surface: string,
): T[] {
  const { kept, dropped } = partitionRowsByLead(rows, leadId)
  reportForeignLeadRows(dropped, leadId, surface)
  return kept
}

/**
 * Scope rows and adjust a list total in one step (write-path / effect helpers).
 */
export function scopeRowsToLeadWithTotal<T extends LeadScopedRow>(
  rows: readonly T[],
  leadId: number,
  surface: string,
  serverTotal: number,
): { rows: T[]; total: number; droppedCount: number } {
  const { kept, dropped } = partitionRowsByLead(rows, leadId)
  reportForeignLeadRows(dropped, leadId, surface)
  return {
    rows: kept,
    total: scopedListTotal(serverTotal, kept.length, dropped.length),
    droppedCount: dropped.length,
  }
}
