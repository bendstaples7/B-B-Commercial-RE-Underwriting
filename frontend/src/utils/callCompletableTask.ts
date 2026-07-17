/**
 * Match open tasks that may be completed when logging a call.
 * Mirrors backend/app/utils/call_completable_task.py
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
    return (a.due_date || '').localeCompare(b.due_date || '')
  })
}

/** Prefer overdue → due today; first call-completable open task (native or HubSpot). */
export function findCallCompletableTask(tasks: LeadTask[]): LeadTask | null {
  const openTasks = sortOpenTasks(
    tasks.filter((t) => t.status === 'open' || t.status === 'overdue'),
  )

  for (const task of openTasks) {
    if (isCallCompletableTask(task.task_type, task.title)) {
      return task
    }
  }

  if (openTasks.length === 1 && !isMailOrEmailOutreachTask(openTasks[0].task_type, openTasks[0].title)) {
    return openTasks[0]
  }

  return null
}
