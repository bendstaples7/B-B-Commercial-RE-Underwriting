import type { RecommendedAction } from '@/types'

export const SCORING_ACTION_LABELS: Record<RecommendedAction, string> = {
  review_now: 'Review Now',
  enrich_data: 'Enrich Data',
  mail_ready: 'Mail Ready',
  call_ready: 'Call Ready',
  valuation_needed: 'Valuation Needed',
  suppress: 'Suppress',
  nurture: 'Nurture',
  needs_manual_review: 'Needs Manual Review',
}

export function scoringActionLabel(action: RecommendedAction | string): string {
  return SCORING_ACTION_LABELS[action as RecommendedAction] ?? action
}
