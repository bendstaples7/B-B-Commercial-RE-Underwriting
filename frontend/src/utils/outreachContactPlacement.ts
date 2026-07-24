/**
 * Outreach contact placement policy for the lead Command Center.
 *
 * Invariant: contact appears on exactly one surface per view.
 * - key_contact_card: Key Contact card when mounted (lg+ rail or below-lg stack)
 * - primary_task: inline on the first open task (HubSpot or native) — fallback when no Key Contact card
 * - recommended_action: inline in the Recommended Action panel when no open tasks — fallback when no Key Contact card
 * - none: no contact to show (non-outreach recommended actions)
 */
import type { LeadTask, OutreachContact } from '@/types'

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

export interface OutreachContactPlacementOptions {
  /** When true (Key Contact card mounted), contact lives only on that card. */
  keyContactCardVisible?: boolean
}

export function outreachContactPlacement(
  openTasks: LeadTask[],
  _contact: OutreachContact | null | undefined,
  recommendedAction?: string | null,
  options?: OutreachContactPlacementOptions,
): OutreachContactSurface {
  if (options?.keyContactCardVisible) return 'key_contact_card'
  if (!isOutreachRecommendedAction(recommendedAction)) return 'none'
  const hasOpenTasks = openTasks.length > 0
  if (hasOpenTasks) return 'primary_task'
  return 'recommended_action'
}
