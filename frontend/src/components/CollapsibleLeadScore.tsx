/**
 * Collapsible lead score breakdown — expands when the user taps the score/tier.
 */
import { useState } from 'react'
import {
  Box,
  Collapse,
  IconButton,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import type { PropertyScoreRecord } from '@/types'
import { LeadScoreBadge } from './LeadScoreBadge'
import { TIER_RANGE_LABELS, formatScoreFieldLabel } from '@/utils/scoreTierMeta'
import { ScoreBreakdownCard } from './ScoreBreakdownCard'

export interface CollapsibleLeadScoreProps {
  score: PropertyScoreRecord
  onViewFullBreakdown?: () => void
}

export function CollapsibleLeadScore({ score, onViewFullBreakdown }: CollapsibleLeadScoreProps) {
  const [expanded, setExpanded] = useState(false)
  const tierTooltip = `Tier ${score.score_tier}: ${TIER_RANGE_LABELS[score.score_tier]} — letter grade from total score (0–100)`

  const topDrivers = Object.entries(score.score_details ?? {})
    .filter(([key]) => key !== 'notes_keywords')
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3)

  return (
    <Box sx={{ mb: 2 }} data-testid="collapsible-lead-score">
      <Paper
        variant="outlined"
        sx={{
          px: 1.5,
          py: 1,
          cursor: 'pointer',
          '&:hover': { bgcolor: 'action.hover' },
        }}
        onClick={() => setExpanded((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setExpanded((v) => !v)
          }
        }}
        tabIndex={0}
        role="button"
        aria-expanded={expanded}
        data-testid="collapsible-lead-score-toggle"
      >
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" color="text.secondary">
              Lead Score
            </Typography>
            <Typography variant="subtitle1" fontWeight="bold">
              {Math.round(score.total_score)} / 100
            </Typography>
            <Tooltip title={tierTooltip}>
              <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.25 }}>
                <LeadScoreBadge tier={score.score_tier} size="small" />
                <InfoOutlinedIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
              </Box>
            </Tooltip>
            {!expanded && topDrivers.length > 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                {formatScoreFieldLabel(topDrivers[0][0])} +{topDrivers[0][1]}
                {topDrivers.length > 1 ? ` · +${topDrivers.length - 1} more` : ''}
              </Typography>
            )}
          </Stack>
          <IconButton
            size="small"
            aria-label={expanded ? 'Collapse score breakdown' : 'Expand score breakdown'}
            sx={{
              transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s',
            }}
          >
            <ExpandMoreIcon />
          </IconButton>
        </Stack>
      </Paper>

      <Collapse in={expanded}>
        <Box sx={{ mt: 1 }}>
          <ScoreBreakdownCard score={score} />
          {onViewFullBreakdown && (
            <Box sx={{ mt: 1, textAlign: 'right' }}>
              <Typography
                component="button"
                variant="body2"
                onClick={(e) => {
                  e.stopPropagation()
                  onViewFullBreakdown()
                }}
                sx={{
                  border: 0,
                  background: 'none',
                  color: 'primary.main',
                  cursor: 'pointer',
                  textDecoration: 'underline',
                }}
              >
                View score history
              </Typography>
            </Box>
          )}
        </Box>
      </Collapse>
    </Box>
  )
}

export default CollapsibleLeadScore
