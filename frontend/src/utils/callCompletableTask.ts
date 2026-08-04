/**
 * Match open tasks that may be completed when logging activity.
 * Call matcher mirrors backend/app/utils/call_completable_task.py.
 * Note/email never auto-complete skip-trace / research / system tasks.
 */
import type { LeadTask, LeadTaskType } from '@/types'

const CALL_TITLE_RE = /\b(call|phone|voicemail)\b/i
const FOLLOW_UP_TITLE_RE = /\bfollow[\s-]?up\b/i
const MAIL_OR_EMAIL_TITLE_RE = /\b(email|e-mail|mail|letter)\b/i

const NON_CALL_TASK_TYPES = new Set<LeadTaskType>([
  'research_missing_pin',
  'match_hubspot_deal',
  'run_property_analysis',
  'add_to_mail_batch',
  'skip_trace_owner',
])

/** System / ops tasks that must never auto-complete from Log note or email. */
const NEVER_NOTE_EMAIL_COMPLETE = new Set<LeadTaskType>([
  'research_missing_pin',
  'match_hubspot_deal',
  'run_property_analysis',
  'skip_trace_owner',
])

export function isMailOrEmailOutreachTask(
  taskType: string | null | undefined,
  title: string | null | undefined,
): boolean {
  const ttype = (taskType || 'custom').trim()
  const text = title || ''
  if (ttype === 'add_to_mail_batch') return true
  return MAIL_OR_EMAIL_TITLE_RE.test(text)
}

export function isCallCompletableTask(
  taskType: string | null | undefined,
  title: string | null | undefined,
): boolean {
  const ttype = (taskType || 'custom').trim()
  const text = title || ''

  if (ttype === 'call_owner_today') return true
  if (NON_CALL_TASK_TYPES.has(ttype as LeadTaskType)) return false
  if (isMailOrEmailOutreachTask(taskType, title)) return false
  return CALL_TITLE_RE.test(text) || FOLLOW_UP_TITLE_RE.test(text)
}

/**
 * Email mode: call-completable outreach, or mail/email tasks.
 * Still never skip-trace / research / match / analysis.
 */
export function isEmailCompletableTask(
  taskType: string | null | undefined,
  title: string | null | undefined,
): boolean {
  const ttype = (taskType || 'custom').trim()
  if (NEVER_NOTE_EMAIL_COMPLETE.has(ttype as LeadTaskType)) return false
  if (isMailOrEmailOutreachTask(taskType, title)) return true
  return isCallCompletableTask(taskType, title)
}

/** Resolve numeric LeadTask id (legacy rows may still use ``hs-{id}``). */
export function parseHubSpotTaskId(id: number | string): number | null {
  if (typeof id === 'number' && Number.isFinite(id)) return id
  const match = String(id).match(/^(?:hs-)?(\d+)$/)
  return match ? Number(match[1]) : null
}

const DUE_STATUS_ORDER: Record<string, number> = {
  overdue: 0,
  due_today: 1,
  upcoming: 2,
  no_due: 3,
}

function dueStatus(dueDate: string | null | undefined): string {
  if (!dueDate) return 'no_due'
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const due = new Date(dueDate.includes('T') ? dueDate : `${dueDate}T00:00:00`)
  due.setHours(0, 0, 0, 0)
  const diff = due.getTime() - today.getTime()
  if (diff < 0) return 'overdue'
  if (diff === 0) return 'due_today'
  return 'upcoming'
}

function sortOpenTasks(tasks: LeadTask[]): LeadTask[] {
  return [...tasks].sort((a, b) => {
    const order =
      (DUE_STATUS_ORDER[dueStatus(a.due_date)] ?? 3) -
      (DUE_STATUS_ORDER[dueStatus(b.due_date)] ?? 3)
    if (order !== 0) return order
    if (a.due_date === null && b.due_date === null) return 0
    if (a.due_date === null) return 1
    if (b.due_date === null) return -1
    return (a.due_date || '').localeCompare(b.due_date || '')
  })
}

/** Shared overdue → due-today ordering for open-task primary row selection. */
export { sortOpenTasks }

function findFirstMatching(
  tasks: LeadTask[],
  predicate: (task: LeadTask) => boolean,
  soleFallback?: (task: LeadTask) => boolean,
): LeadTask | null {
  const openTasks = sortOpenTasks(
    tasks.filter((t) => t.status === 'open' || t.status === 'overdue'),
  )

  for (const task of openTasks) {
    if (predicate(task)) return task
  }

  if (openTasks.length === 1 && soleFallback?.(openTasks[0])) {
    return openTasks[0]
  }

  return null
}

/** Prefer overdue → due today; first call-completable open task (native or HubSpot). */
export function findCallCompletableTask(tasks: LeadTask[]): LeadTask | null {
  return findFirstMatching(
    tasks,
    (task) => isCallCompletableTask(task.task_type, task.title),
    (task) => !isMailOrEmailOutreachTask(task.task_type, task.title)
      && !NEVER_NOTE_EMAIL_COMPLETE.has((task.task_type || 'custom') as LeadTaskType)
      && (task.task_type || 'custom') !== 'add_to_mail_batch',
  )
}

/**
 * @deprecated Prefer findCompletableTaskForMode — kept for tests that assert
 * soonest-open ordering helpers separately from mode matchers.
 */
export function findPrimaryOpenTask(tasks: LeadTask[]): LeadTask | null {
  const openTasks = sortOpenTasks(
    tasks.filter((t) => t.status === 'open' || t.status === 'overdue'),
  )
  return openTasks[0] ?? null
}

export function findEmailCompletableTask(tasks: LeadTask[]): LeadTask | null {
  return findFirstMatching(
    tasks,
    (task) => isEmailCompletableTask(task.task_type, task.title),
    (task) =>
      !NEVER_NOTE_EMAIL_COMPLETE.has((task.task_type || 'custom') as LeadTaskType),
  )
}

/** Mode-aware completable task for LogActivityForm next-step panel. */
export function findCompletableTaskForMode(
  mode: 'call' | 'note' | 'email',
  tasks: LeadTask[],
): LeadTask | null {
  if (mode === 'call' || mode === 'note') return findCallCompletableTask(tasks)
  return findEmailCompletableTask(tasks)
}
