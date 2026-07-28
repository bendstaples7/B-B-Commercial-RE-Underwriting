/**
 * Outreach contact placement policy for the lead Command Center.
 *
 * Invariant: preferred action target (`OutreachContactInline`) appears on
 * exactly one surface per view.
 * - primary_task: first open task is call/email outreach (even when Key Contact
 *   directory is mounted) — phone/email sit next to the work
 * - key_contact_card: Key Contact mounted and primary task is not call/email
 * - recommended_action: primary task is not outreach-capable (call/email/mail)
 *   AND Key Contact directory is not visible — inline under RA
 * - none: no contact to show
 */
import type { LeadTask, OutreachContact } from '@/types'
import {
  isCallCompletableTask,
  isMailOrEmailOutreachTask,
  sortOpenTasks,
} from '@/utils/callCompletableTask'

export type OutreachContactSurface =
  | 'key_contact_card'
  | 'primary_task'
  | 'recommended_action'
  | 'none'

/** Recommended actions that may show outreach contact (mirrors backend OUTREACH_ACTIONS). */
export const OUTREACH_RECOMMENDED_ACTIONS = new Set([
  'follow_up_now',
  'ready_for_outreach',
  'mail_ready',
  'call_ready',
  'review_now',
  'nurture',
])

export function isOutreachRecommendedAction(
  action: string | null | undefined,
): boolean {
  return !!action && OUTREACH_RECOMMENDED_ACTIONS.has(action)
}

/** True when the primary open task is call / follow-up / email / mail work. */
export function isOutreachPrimaryTask(
  task: LeadTask | null | undefined,
): boolean {
  if (!task) return false
  return (
    isCallCompletableTask(task.task_type, task.title) ||
    isMailOrEmailOutreachTask(task.task_type, task.title)
  )
}

/** Match LeadTaskList primary-row ordering (overdue → due today → …). */
export function primaryOpenTask(openTasks: LeadTask[]): LeadTask | null {
  if (!openTasks.length) return null
  return sortOpenTasks(openTasks)[0] ?? null
}

export interface OutreachContactPlacementOptions {
  /** When true (Key Contact card mounted), contact defaults to that card
   *  unless the primary open task is call/email outreach. */
  keyContactCardVisible?: boolean
}

export function outreachContactPlacement(
  openTasks: LeadTask[],
  _contact: OutreachContact | null | undefined,
  recommendedAction?: string | null,
  options?: OutreachContactPlacementOptions,
): OutreachContactSurface {
  const primary = primaryOpenTask(openTasks)
  const primaryIsOutreach = isOutreachPrimaryTask(primary)

  // Preferred dial/email target sits on the due outreach task even when the
  // Key Contact directory is also mounted (plan: action target vs directory).
  if (primaryIsOutreach) return 'primary_task'

  if (options?.keyContactCardVisible) return 'key_contact_card'
  if (!isOutreachRecommendedAction(recommendedAction)) return 'none'
  // Non-outreach primary task must not host contact chrome.
  return 'recommended_action'
}
