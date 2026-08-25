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

export function fromQueueFromKey(
  key: string | null | undefined,
  outreach?: string | null,
): FromQueueState | null {
  if (!key) return null
  const meta = WORK_QUEUE_META[key]
  if (!meta) return null
  return {
    key,
    label: meta.label,
    ...(outreach ? { outreach } : {}),
  }
}

export function queuePath(key: string): string {
  return `/queues/${key}`
}

const QUEUE_SESSION_STORAGE_PREFIX = 'bb-queue-session:'

export type QueueSessionHistory = Pick<FromQueueState, 'visitedHistory' | 'forwardStack'>

function queueSessionStorageKey(queueKey: string, outreach?: string): string {
  return `${QUEUE_SESSION_STORAGE_PREFIX}${queueKey}:${outreach || 'all'}`
}

export function readQueueSessionHistory(
  queueKey: string,
  outreach?: string,
  currentLeadId?: number,
): QueueSessionHistory | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(queueSessionStorageKey(queueKey, outreach))
    if (!raw) return null
    const parsed = JSON.parse(raw) as QueueSessionHistory
    const visitedHistory = Array.isArray(parsed.visitedHistory)
      ? parsed.visitedHistory.filter((id) => Number.isInteger(id))
      : []
    const forwardStack = Array.isArray(parsed.forwardStack)
      ? parsed.forwardStack.filter((id) => Number.isInteger(id))
      : []
    if (!visitedHistory.length && !forwardStack.length) return null
    // Browser Back restores the original route state. If persisted history says
    // the current lead is the previous lead, treating it as restored state would
    // make the lead its own "Go back" target.
    if (currentLeadId != null && visitedHistory.at(-1) === currentLeadId) {
      const priorHistory = visitedHistory.slice(0, -1)
      if (!priorHistory.length && !forwardStack.length) return null
      return { visitedHistory: priorHistory, forwardStack }
    }
    return { visitedHistory, forwardStack }
  } catch {
    return null
  }
}

export function writeQueueSessionHistory(
  queueKey: string,
  history: QueueSessionHistory,
  outreach?: string,
): void {
  if (typeof sessionStorage === 'undefined') return
  const visitedHistory = history.visitedHistory ?? []
  const forwardStack = history.forwardStack ?? []
  try {
    const storageKey = queueSessionStorageKey(queueKey, outreach)
    if (!visitedHistory.length && !forwardStack.length) {
      sessionStorage.removeItem(storageKey)
      return
    }
    sessionStorage.setItem(
      storageKey,
      JSON.stringify({ visitedHistory, forwardStack }),
    )
  } catch {
    // Queue navigation should not fail just because browser storage is blocked.
  }
}

export function clearQueueSessionHistory(queueKey: string, outreach?: string): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.removeItem(queueSessionStorageKey(queueKey, outreach))
  } catch {
    // Ignore unavailable storage.
  }
}

export function clearAllQueueSessionHistory(): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
      const key = sessionStorage.key(i)
      if (key?.startsWith(QUEUE_SESSION_STORAGE_PREFIX)) {
        sessionStorage.removeItem(key)
      }
    }
  } catch {
    // Ignore unavailable storage.
  }
}

/** Merge router state with session-persisted back/forward stacks when state was dropped. */
export function mergeQueueSessionHistory(
  fromQueue: FromQueueState,
  currentLeadId?: number,
): FromQueueState {
  const stored = readQueueSessionHistory(fromQueue.key, fromQueue.outreach, currentLeadId)
  if (!stored) return fromQueue
  return {
    ...fromQueue,
    visitedHistory: fromQueue.visitedHistory?.length
      ? fromQueue.visitedHistory
      : stored.visitedHistory,
    forwardStack: fromQueue.forwardStack?.length
      ? fromQueue.forwardStack
      : stored.forwardStack,
  }
}

export function buildLeadQueueSearch(
  queueKey: string | undefined,
  outreach?: string | null,
): string {
  if (!queueKey || !WORK_QUEUE_META[queueKey]) return ''
  const params = new URLSearchParams({ queue: queueKey })
  if (outreach) params.set('outreach', outreach)
  return `?${params.toString()}`
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
