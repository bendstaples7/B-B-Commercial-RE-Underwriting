/**
 * LeadScoreBadge — compact color-coded badge displaying a lead's score tier.
 *
 * Tier colors follow the product spec:
 *   A = green   (success)
 *   B = blue    (info)
 *   C = yellow  (warning)
 *   D = red     (error)
 *
 * When no tier is provided (e.g. a lead has no LeadScoreRecord yet), the
 * badge renders a neutral "Not scored" indicator.
 */
import { Chip, ChipProps } from '@mui/material'
import type { LeadScoreRecord } from '@/types'

export type ScoreTier = LeadScoreRecord['score_tier']

export interface LeadScoreBadgeProps {
  /** The score tier to display. `null` or `undefined` renders "Not scored". */
  tier?: ScoreTier | null
  /** Chip size. Defaults to `small` for use in dense tables. */
  size?: ChipProps['size']
  /** Optional className passthrough. */
  className?: string
}

interface TierStyle {
  label: string
  color: ChipProps['color']
}

const TIER_STYLES: Record<ScoreTier, TierStyle> = {
  A: { label: 'A', color: 'success' },
  B: { label: 'B', color: 'info' },
  C: { label: 'C', color: 'warning' },
  D: { label: 'D', color: 'error' },
}

const NOT_SCORED_STYLE: TierStyle = { label: 'Not scored', color: 'default' }

export function LeadScoreBadge({
  tier,
  size = 'small',
  className,
}: LeadScoreBadgeProps) {
  const style = tier ? TIER_STYLES[tier] : NOT_SCORED_STYLE
  const ariaLabel = tier ? `Lead score tier ${tier}` : 'Lead not scored'

  return (
    <Chip
      label={style.label}
      color={style.color}
      size={size}
      variant="filled"
      aria-label={ariaLabel}
      className={className}
      data-testid="lead-score-badge"
      data-tier={tier ?? 'none'}
    />
  )
}

export default LeadScoreBadge
