/**
 * Outreach contact placement policy for the lead Command Center.
 *
 * Invariant: contact appears on exactly one surface per view.
 * - primary_task: inline on the first open task (HubSpot or native)
 * - recommended_action: inline in the Recommended Action panel when no open tasks
 * - none: no contact to show (non-outreach recommended actions)
 */
import type { LeadTask, OutreachContact } from '@/types'

export type OutreachContactSurface = 'primary_task' | 'recommended_action' | 'none'

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

export function outreachContactPlacement(
  openTasks: LeadTask[],
  contact: OutreachContact | null | undefined,
  recommendedAction?: string | null,
): OutreachContactSurface {
  if (!isOutreachRecommendedAction(recommendedAction)) return 'none'
  const hasOpenTasks = openTasks.length > 0
  if (hasOpenTasks) return 'primary_task'
  return 'recommended_action'
}
