/**
 * ScoreBreakdownCard — full score detail display for a single LeadScoreRecord.
 */
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import type { PropertyScoreRecord, RecommendedAction } from '@/types'
import { SCORING_ACTION_LABELS, outreachDisplayLabel } from '@/constants/scoringRecommendedActions'
import { humanize } from '@/utils/formatters'
import { LeadScoreBadge } from './LeadScoreBadge'
import { getDimensionMeta, getScoreVersionMeta } from '@/utils/scoreDimensionMeta'

/** Keys that attribute a slice already counted in another dimension (do not look additive). */
const ATTRIBUTION_ONLY_KEYS = new Set(['notes_keywords'])

export interface ScoreBreakdownCardProps {
  score: PropertyScoreRecord
  className?: string
  /** Hide the large headline when score is already shown in a parent header. */
  compact?: boolean
}

function humanizeField(snake: string): string {
  if (!snake) return ''
  return snake
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}

const FIELD_LABEL_OVERRIDES: Record<string, string> = {
  pin: 'PIN',
  property_sqft: 'Property Square Footage',
  building_sqft: 'Building Square Footage',
}

function fieldLabel(field: string): string {
  return FIELD_LABEL_OVERRIDES[field] ?? humanizeField(field)
}

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
  hold: 'default',
  suppress: 'error',
  do_not_contact: 'error',
  follow_up_now: 'info',
  ready_for_outreach: 'success',
  add_contact_info: 'warning',
  create_task: 'info',
  resolve_match: 'warning',
  analyze_property: 'info',
}

function formatPoints(points: number): string {
  const rounded = Math.round(points * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

export function ScoreBreakdownCard({ score, className, compact = false }: ScoreBreakdownCardProps) {
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

  const inferredMethod =
    recommended_action === 'call_ready'
      ? 'phone'
      : recommended_action === 'mail_ready'
        ? 'direct_mail'
        : null
  const actionLabel =
    outreachDisplayLabel(recommended_action, inferredMethod) ??
    SCORING_ACTION_LABELS[recommended_action] ??
    humanize(recommended_action)
  const actionColor = ACTION_COLORS[recommended_action] ?? 'default'
  const versionMeta = getScoreVersionMeta(score_version)

  const breakdownEntries = Object.entries(score_details).sort(([, a], [, b]) => b - a)

  return (
    <Card
      variant={compact ? 'elevation' : 'outlined'}
      elevation={compact ? 0 : undefined}
      className={className}
      data-testid="score-breakdown-card"
      sx={compact ? { boxShadow: 'none', bgcolor: 'transparent' } : undefined}
    >
      <CardContent sx={compact ? { px: 0, py: 0, '&:last-child': { pb: 0 } } : undefined}>
        {!compact && (
          <>
            <Typography variant="h6" gutterBottom>
              Lead Score
            </Typography>

            <Stack direction="row" spacing={2} alignItems="baseline" sx={{ mb: 2 }}>
              <Typography variant="h3" component="span" data-testid="score-breakdown-total">
                {Math.round(total_score)}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                / 100
              </Typography>
              <LeadScoreBadge tier={score_tier} size="medium" />
            </Stack>
          </>
        )}

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          divider={compact ? undefined : <Divider orientation="vertical" flexItem />}
          sx={{ mb: compact ? 1.5 : 2 }}
        >
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">
              Data Quality
            </Typography>
            <Typography variant="body2" data-testid="score-breakdown-data-quality">
              {Math.round(data_quality_score)} / 100
            </Typography>
          </Box>
          {!compact && (
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
          )}
          <Box>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Typography variant="caption" color="text.secondary">
                Scoring Model
              </Typography>
              <Tooltip title={versionMeta.description} arrow placement="top">
                <InfoOutlinedIcon sx={{ fontSize: 14, color: 'text.disabled', cursor: 'help' }} />
              </Tooltip>
            </Stack>
            <Typography variant="body2" data-testid="score-breakdown-version">
              {versionMeta.shortLabel}
            </Typography>
          </Box>
        </Stack>

        {!compact && <Divider sx={{ my: 2 }} />}

        <Typography variant="subtitle2" gutterBottom>
          Score Breakdown
        </Typography>

        {breakdownEntries.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No score details available.
          </Typography>
        ) : (
          <Box
            component="ul"
            sx={{
              listStyle: 'none',
              m: 0,
              p: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 1.25,
            }}
            data-testid="score-breakdown-details"
          >
            {breakdownEntries.map(([dimension, points]) => {
              const meta = getDimensionMeta(dimension, score_version)
              return (
                <Box
                  component="li"
                  key={dimension}
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: { xs: '1fr auto', sm: 'minmax(0, 1fr) 72px' },
                    columnGap: 2,
                    rowGap: 0.25,
                    alignItems: 'start',
                    py: 1.25,
                    borderTop: 1,
                    borderColor: 'divider',
                    '&:first-of-type': { borderTop: 0, pt: 0 },
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" fontWeight={600}>
                      {meta.label}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                      {meta.description}
                    </Typography>
                    <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 0.25 }}>
                      Data: {meta.dataSource}
                    </Typography>
                  </Box>
                  <Typography
                    variant="body2"
                    fontWeight={700}
                    sx={{
                      fontVariantNumeric: 'tabular-nums',
                      textAlign: 'right',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {ATTRIBUTION_ONLY_KEYS.has(dimension) ? '' : '+'}
                    {formatPoints(points)}
                    {meta.maxPoints > 0 && (
                      <Typography
                        component="span"
                        variant="caption"
                        color="text.secondary"
                        fontWeight={400}
                      >
                        {' '}
                        / {meta.maxPoints}
                      </Typography>
                    )}
                  </Typography>
                  {ATTRIBUTION_ONLY_KEYS.has(dimension) && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ gridColumn: '1 / -1' }}
                    >
                      Included in Structured Motivation (not added again)
                    </Typography>
                  )}
                </Box>
              )
            })}
          </Box>
        )}

        {!compact && (
          <>
            <Divider sx={{ my: 2 }} />

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
                {top_signals.map((signal) => {
                  const meta = getDimensionMeta(signal.dimension, score_version)
                  return (
                    <Chip
                      key={signal.dimension}
                      label={`${meta.label} (+${formatPoints(signal.points)})`}
                      size="small"
                      variant="outlined"
                      color="primary"
                    />
                  )
                })}
              </Stack>
            )}

            <Divider sx={{ my: 2 }} />

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
          </>
        )}
      </CardContent>
    </Card>
  )
}

export default ScoreBreakdownCard
