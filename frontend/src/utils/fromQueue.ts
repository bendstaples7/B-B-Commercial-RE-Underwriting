/**
 * Router location state when opening a lead from a work queue.
 */
export interface FromQueueState {
  key: string
  label: string
  /** Today's Action outreach filter (mail_now, call_now, …) for prev/next nav. */
  outreach?: string
  /** Leads visited in this queue session, oldest to newest. */
  visitedHistory?: number[]
  /** Leads available to revisit after moving backwards. */
  forwardStack?: number[]
}

/** Known work queues — used for ?queue= URL param and navigation labels. */
export const WORK_QUEUE_META: Record<string, { label: string }> = {
  'todays-action': { label: "Today's Action" },
  'previously-warm': { label: 'Previously Warm' },
  'follow-up-overdue': { label: 'Follow-Up Overdue' },
  'no-next-action': { label: 'No Next Action' },
  'needs-review': { label: 'Needs Review' },
  'do-not-contact': { label: 'Do Not Contact' },
  'missing-property-match': { label: 'Missing Property Match' },
  'mail-candidates': { label: 'Ready to Mail' },
}

/**
 * Queues where Move to Skip Trace removes the lead from due/work membership
 * and should auto-advance like task completion.
 */
export const SKIP_TRACE_AUTO_ADVANCE_QUEUE_KEYS = new Set([
  'todays-action',
  'follow-up-overdue',
  'previously-warm',
  'no-next-action',
])

export function isFromQueueState(value: unknown): value is FromQueueState {
  if (!value || typeof value !== 'object') return false
  const v = value as Record<string, unknown>
  if (typeof v.key !== 'string' || typeof v.label !== 'string') return false
  if (v.outreach !== undefined && typeof v.outreach !== 'string') return false
  if (v.visitedHistory !== undefined && (!Array.isArray(v.visitedHistory) || !v.visitedHistory.every(Number.isInteger))) return false
  if (v.forwardStack !== undefined && (!Array.isArray(v.forwardStack) || !v.forwardStack.every(Number.isInteger))) return false
  return true
}

export function fromQueueFromKey(key: string | null | undefined): FromQueueState | null {
  if (!key) return null
  const meta = WORK_QUEUE_META[key]
  if (!meta) return null
  return { key, label: meta.label }
}

export function queuePath(key: string): string {
  return `/queues/${key}`
}

export function buildLeadQueueSearch(queueKey: string | undefined): string {
  if (!queueKey || !WORK_QUEUE_META[queueKey]) return ''
  return `?queue=${encodeURIComponent(queueKey)}`
}

/** Add days to today as YYYY-MM-DD (local). */
export function addDaysIso(days: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() + days)
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/** Add months to today as YYYY-MM-DD (local). Clamps day-of-month on overflow. */
export function addMonthsIso(months: number): string {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  const day = d.getDate()
  d.setDate(1)
  d.setMonth(d.getMonth() + months)
  const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()
  d.setDate(Math.min(day, lastDay))
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}
