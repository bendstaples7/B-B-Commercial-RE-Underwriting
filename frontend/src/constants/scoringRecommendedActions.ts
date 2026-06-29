import type { UnifiedRecommendedAction } from '@/types'

export const SCORING_ACTION_LABELS: Record<UnifiedRecommendedAction, string> = {
  review_now: 'Review Now',
  enrich_data: 'Enrich Data',
  mail_ready: 'Mail Ready',
  call_ready: 'Call Ready',
  valuation_needed: 'Valuation Needed',
  suppress: 'Suppress',
  nurture: 'Nurture',
  needs_manual_review: 'Needs Manual Review',
  follow_up_now: 'Follow Up Now',
  ready_for_outreach: 'Ready for Outreach',
  add_contact_info: 'Add Contact Info',
  create_task: 'Create a Task',
  resolve_match: 'Resolve Property Match',
  analyze_property: 'Analyze Property',
  do_not_contact: 'Do Not Contact',
}

export function scoringActionLabel(action: UnifiedRecommendedAction | string): string {
  return SCORING_ACTION_LABELS[action as UnifiedRecommendedAction] ?? action
}
