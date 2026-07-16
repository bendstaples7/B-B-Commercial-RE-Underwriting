import type { ContactMethod, UnifiedRecommendedAction } from '@/types'

export const SCORING_ACTION_LABELS: Record<UnifiedRecommendedAction, string> = {
  review_now: 'Review Now',
  enrich_data: 'Enrich Data',
  mail_ready: 'Mail Ready',
  call_ready: 'Call Ready',
  valuation_needed: 'Valuation Needed',
  suppress: 'Suppress',
  nurture: 'Nurture',
  hold: 'Skip Trace Hold',
  needs_manual_review: 'Needs Manual Review',
  follow_up_now: 'Follow Up Now',
  ready_for_outreach: 'Ready for Outreach',
  add_contact_info: 'Add Contact Info',
  create_task: 'Create a Task',
  resolve_match: 'Resolve Property Match',
  analyze_property: 'Analyze Property',
  do_not_contact: 'Do Not Contact',
}

export const CONTACT_METHOD_LABELS: Record<ContactMethod, string> = {
  phone: 'Call',
  email: 'Email',
  text: 'Text',
  direct_mail: 'Direct Mail',
}

export function scoringActionLabel(action: UnifiedRecommendedAction | string): string {
  return SCORING_ACTION_LABELS[action as UnifiedRecommendedAction] ?? action
}

export function outreachDisplayLabel(
  action: UnifiedRecommendedAction | string | null | undefined,
  method?: ContactMethod | string | null,
): string {
  if (!action) return '—'

  if (method === 'direct_mail') return 'Direct Mail'
  if (action === 'call_ready' || (action === 'follow_up_now' && method === 'phone')) {
    return 'Call Now'
  }
  if (action === 'follow_up_now' && method === 'email') return 'Email Now'
  if (action === 'follow_up_now' && method === 'text') return 'Text Now'
  if (action === 'ready_for_outreach' && method === 'phone') return 'Ready to Call'
  if (action === 'ready_for_outreach' && method === 'email') return 'Ready to Email'
  if (action === 'ready_for_outreach' && method === 'text') return 'Ready to Text'
  if (action === 'review_now' && method) {
    return `Review — ${CONTACT_METHOD_LABELS[method as ContactMethod] ?? method}`
  }
  if (action === 'nurture' && method) {
    return `Nurture — ${CONTACT_METHOD_LABELS[method as ContactMethod] ?? method}`
  }

  return SCORING_ACTION_LABELS[action as UnifiedRecommendedAction] ?? action
}
