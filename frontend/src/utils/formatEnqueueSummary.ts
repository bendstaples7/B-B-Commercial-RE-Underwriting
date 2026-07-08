import type { EnqueueLeadResult } from '@/services/openLetterApi'

export interface EnqueueCounts {
  added: number
  skipped: number
  invalid: number
  results?: EnqueueLeadResult[]
}

const STATUS_LABELS: Record<string, string> = {
  already_queued: 'already in batch',
  invalid_address: 'invalid address',
  recently_sold: 'recently sold',
  not_found: 'not found',
  not_authorized: 'not authorized',
  error: 'could not queue',
}

/** Human-readable summary of an enqueue API response. */
export function formatEnqueueSummary(result: EnqueueCounts): string {
  const parts: string[] = []
  if (result.added > 0) {
    parts.push(`Added ${result.added}`)
  }

  if (result.results?.length) {
    const byStatus = new Map<string, number>()
    for (const row of result.results) {
      if (row.status === 'queued') continue
      byStatus.set(row.status, (byStatus.get(row.status) ?? 0) + 1)
    }
    for (const [status, count] of byStatus) {
      const label = STATUS_LABELS[status] ?? status.replace(/_/g, ' ')
      parts.push(`${count} ${label}`)
    }
  } else {
    if (result.skipped > 0) parts.push(`${result.skipped} skipped`)
    if (result.invalid > 0) {
      parts.push(`${result.invalid} invalid address${result.invalid === 1 ? '' : 'es'}`)
    }
  }

  if (parts.length === 0) return 'No leads added'
  return parts.join(' · ')
}

/** Human-readable dry-run preview before enqueue. */
export function formatEnqueuePreview(preview: {
  would_add: number
  would_skip: number
  would_fail: number
}): string {
  const parts = [`${preview.would_add} ready to add`]
  if (preview.would_skip > 0) parts.push(`${preview.would_skip} skipped`)
  if (preview.would_fail > 0) {
    parts.push(
      `${preview.would_fail} would fail validation`,
    )
  }
  return parts.join(' · ')
}
