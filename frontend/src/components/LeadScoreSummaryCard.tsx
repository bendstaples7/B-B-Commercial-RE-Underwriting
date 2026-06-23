/**
 * Compact lead score summary for the command center main column.
 * Surfaces the numeric score, letter tier, and top contributing dimensions
 * without requiring the user to discover the Score tab.
 */
import {
  Box,
  Button,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import type { PropertyScoreRecord } from '@/types'
import { LeadScoreBadge } from './LeadScoreBadge'
import type { ScoreTier } from './LeadScoreBadge'

const TIER_RANGE_LABELS: Record<ScoreTier, string> = {
  A: '75–100 (strong fit)',
  B: '60–74 (good fit)',
  C: '40–59 (marginal)',
  D: '0–39 (low priority)',
}

function fieldLabel(field: string): string {
  return field
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}

export interface LeadScoreSummaryCardProps {
  score: PropertyScoreRecord
  onViewFullBreakdown?: () => void
}

export function LeadScoreSummaryCard({ score, onViewFullBreakdown }: LeadScoreSummaryCardProps) {
  const breakdownEntries = Object.entries(score.score_details ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5)

  const tierTooltip = (
    <>
      Letter grade from total score (0–100).
      <br />
      Tier {score.score_tier}: {TIER_RANGE_LABELS[score.score_tier]}
    </>
  )

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }} data-testid="lead-score-summary-card">
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'flex-start' }}>
        <Box sx={{ minWidth: 140 }}>
          <Typography variant="overline" color="text.secondary" display="block">
            Lead Score
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
            <Typography variant="h5" component="span" fontWeight="bold">
              {Math.round(score.total_score)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              / 100
            </Typography>
            <Tooltip title={tierTooltip}>
              <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                <LeadScoreBadge tier={score.score_tier} size="small" />
                <InfoOutlinedIcon sx={{ fontSize: 16, color: 'text.disabled' }} />
              </Box>
            </Tooltip>
          </Stack>
        </Box>

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
            Top score drivers
          </Typography>
          {breakdownEntries.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No breakdown available.
            </Typography>
          ) : (
            <Stack spacing={0.25}>
              {breakdownEntries.map(([dimension, points]) => (
                <Box
                  key={dimension}
                  sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}
                >
                  <Typography variant="body2" noWrap sx={{ flex: 1 }}>
                    {fieldLabel(dimension)}
                  </Typography>
                  <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }}>
                    +{points}
                  </Typography>
                </Box>
              ))}
            </Stack>
          )}
        </Box>

        {onViewFullBreakdown && (
          <Button size="small" variant="text" onClick={onViewFullBreakdown} sx={{ flexShrink: 0 }}>
            View full breakdown
          </Button>
        )}
      </Stack>
    </Paper>
  )
}

export default LeadScoreSummaryCard
