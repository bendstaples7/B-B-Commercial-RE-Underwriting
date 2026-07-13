export interface QueueContext {
  label: string
  path: string
  reason: string
  color: 'error' | 'warning' | 'info' | 'success' | 'default'
}

/** Keys shown as alert banners (noisy queues stay sidebar-only). */
const BANNER_QUEUE_META: Record<
  string,
  { reason: string; color: QueueContext['color'] }
> = {
  'do-not-contact': {
    reason: 'This lead is marked Do Not Contact.',
    color: 'error',
  },
  'needs-review': {
    reason: 'This lead has been flagged for review.',
    color: 'warning',
  },
  'follow-up-overdue': {
    reason: 'A follow-up task is overdue.',
    color: 'error',
  },
  'missing-property-match': {
    reason: 'No confirmed property match exists for this lead.',
    color: 'info',
  },
  'no-next-action': {
    reason: 'No open tasks or next action defined.',
    color: 'default',
  },
}

/**
 * Format command-center queue membership for banners.
 * Membership comes from QueueService via ``work_queues`` — do not re-derive filters here.
 */
export function deriveQueueContext(data: {
  work_queues?: Array<{ key: string; label: string; path: string }>
  review_reason?: string | null
}): QueueContext[] {
  const queues = Array.isArray(data.work_queues) ? data.work_queues : []
  const banners: QueueContext[] = []

  for (const q of queues) {
    const meta = BANNER_QUEUE_META[q.key]
    if (!meta) continue
    banners.push({
      label: q.label,
      path: q.path,
      reason:
        q.key === 'needs-review' && data.review_reason
          ? data.review_reason
          : meta.reason,
      color: meta.color,
    })
  }

  return banners
}
