/**
 * ScoreBreakdownCard — full score detail display for a single LeadScoreRecord.
 *
 * Renders on the Lead Detail page to explain how a lead earned its score.
 * Shows:
 *   • total_score (prominent) with score_tier via LeadScoreBadge
 *   • data_quality_score, recommended_action, score_version
 *   • full score_details breakdown (dimension name + points)
 *   • top_signals list
 *   • missing_data list with human-readable labels
 *
 * Satisfies Requirements 11.1, 11.2, 11.3.
 */
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from '@mui/material'
import type { LeadScoreRecord, RecommendedAction } from '@/types'
import { LeadScoreBadge } from './LeadScoreBadge'

export interface ScoreBreakdownCardProps {
  /** The score record to display. */
  score: LeadScoreRecord
  /** Optional className passthrough. */
  className?: string
}

/**
 * Convert a snake_case identifier into a human-readable Title Case label.
 *
 * Examples:
 *   "owner_mailing_address" -> "Owner Mailing Address"
 *   "mail_ready"            -> "Mail Ready"
 *   "pin"                   -> "Pin"
 */
function humanize(snake: string): string {
  if (!snake) return ''
  return snake
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}

/** Domain-specific overrides for fields where the generic humanize() is awkward. */
const FIELD_LABEL_OVERRIDES: Record<string, string> = {
  pin: 'PIN',
  property_sqft: 'Property Square Footage',
  building_sqft: 'Building Square Footage',
}

function fieldLabel(field: string): string {
  return FIELD_LABEL_OVERRIDES[field] ?? humanize(field)
}

/** Human-readable labels for the constrained set of recommended actions. */
const ACTION_LABELS: Record<RecommendedAction, string> = {
  review_now: 'Review Now',
  enrich_data: 'Enrich Data',
  mail_ready: 'Mail Ready',
  call_ready: 'Call Ready',
  valuation_needed: 'Valuation Needed',
  suppress: 'Suppress',
  nurture: 'Nurture',
  needs_manual_review: 'Needs Manual Review',
}

/** Chip color per action, matching workflow urgency. */
const ACTION_COLORS: Record<
  RecommendedAction,
  'success' | 'info' | 'warning' | 'error' | 'default'
> = {
  mail_ready: 'success',
  call_ready: 'success',
  review_now: 'info',
  enrich_data: 'warning',
  valuation_needed: 'warning',
  needs_manual_review: 'warning',
  nurture: 'default',
  suppress: 'error',
}

export function ScoreBreakdownCard({ score, className }: ScoreBreakdownCardProps) {
  const {
    total_score,
    score_tier,
    data_quality_score,
    recommended_action,
    score_version,
    score_details,
    top_signals,
    missing_data,
  } = score

  const actionLabel = ACTION_LABELS[recommended_action] ?? humanize(recommended_action)
  const actionColor = ACTION_COLORS[recommended_action] ?? 'default'

  // Sort the full score_details breakdown by points (desc) so the highest
  // contributors appear first. Preserves the dimension key for stable keys.
  const breakdownEntries = Object.entries(score_details).sort(
    ([, a], [, b]) => b - a,
  )

  return (
    <Card
      variant="outlined"
      className={className}
      data-testid="score-breakdown-card"
    >
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Lead Score
        </Typography>

        {/* Headline: total score + tier badge */}
        <Stack direction="row" spacing={2} alignItems="baseline" sx={{ mb: 2 }}>
          <Typography
            variant="h3"
            component="span"
            data-testid="score-breakdown-total"
          >
            {Math.round(total_score)}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            / 100
          </Typography>
          <LeadScoreBadge tier={score_tier} size="medium" />
        </Stack>

        {/* Secondary metrics row */}
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          divider={<Divider orientation="vertical" flexItem />}
          sx={{ mb: 2 }}
        >
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">
              Data Quality
            </Typography>
            <Typography variant="body1" data-testid="score-breakdown-data-quality">
              {Math.round(data_quality_score)} / 100
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">
              Recommended Action
            </Typography>
            <Chip
              label={actionLabel}
              color={actionColor}
              size="small"
              variant="filled"
              data-testid="score-breakdown-action"
            />
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">
              Score Version
            </Typography>
            <Typography
              variant="body2"
              sx={{ fontFamily: 'monospace' }}
              data-testid="score-breakdown-version"
            >
              {score_version}
            </Typography>
          </Box>
        </Stack>

        <Divider sx={{ my: 2 }} />

        {/* Full score_details breakdown */}
        <Typography variant="subtitle2" gutterBottom>
          Score Breakdown
        </Typography>
        {breakdownEntries.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No score details available.
          </Typography>
        ) : (
          <List dense disablePadding data-testid="score-breakdown-details">
            {breakdownEntries.map(([dimension, points]) => (
              <ListItem
                key={dimension}
                disableGutters
                sx={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  py: 0.25,
                }}
              >
                <ListItemText
                  primary={fieldLabel(dimension)}
                  primaryTypographyProps={{ variant: 'body2' }}
                />
                <Typography
                  variant="body2"
                  sx={{ fontVariantNumeric: 'tabular-nums' }}
                >
                  {points}
                </Typography>
              </ListItem>
            ))}
          </List>
        )}

        <Divider sx={{ my: 2 }} />

        {/* Top signals */}
        <Typography variant="subtitle2" gutterBottom>
          Top Signals
        </Typography>
        {top_signals.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No contributing signals.
          </Typography>
        ) : (
          <Stack
            direction="row"
            spacing={1}
            flexWrap="wrap"
            useFlexGap
            data-testid="score-breakdown-top-signals"
          >
            {top_signals.map((signal) => (
              <Chip
                key={signal.dimension}
                label={`${fieldLabel(signal.dimension)} (+${signal.points})`}
                size="small"
                variant="outlined"
                color="primary"
              />
            ))}
          </Stack>
        )}

        <Divider sx={{ my: 2 }} />

        {/* Missing data */}
        <Typography variant="subtitle2" gutterBottom>
          Missing Data
        </Typography>
        {missing_data.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No missing data — this lead is fully populated.
          </Typography>
        ) : (
          <Stack
            direction="row"
            spacing={1}
            flexWrap="wrap"
            useFlexGap
            data-testid="score-breakdown-missing-data"
          >
            {missing_data.map((field) => (
              <Chip
                key={field}
                label={fieldLabel(field)}
                size="small"
                variant="outlined"
                color="warning"
              />
            ))}
          </Stack>
        )}
      </CardContent>
    </Card>
  )
}

export default ScoreBreakdownCard
