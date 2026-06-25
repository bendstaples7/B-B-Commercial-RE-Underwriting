import type { ScoreTier } from '@/components/LeadScoreBadge'

export const TIER_RANGE_LABELS: Record<ScoreTier, string> = {
  A: '75–100 (strong fit)',
  B: '60–74 (good fit)',
  C: '40–59 (marginal)',
  D: '0–39 (low priority)',
}

export function formatScoreFieldLabel(field: string): string {
  return field
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}
