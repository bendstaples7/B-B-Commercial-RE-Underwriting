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
import {
  buildScorePathSummary,
  formatSignedPoints,
  partitionScoreDetails,
} from '@/utils/scoreBreakdownSummary'

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

  const path = buildScorePathSummary(score_details, total_score)
  const { helps, adjustments, attribution } = partitionScoreDetails(score_details)
  const hasRows = helps.length + adjustments.length + attribution.length > 0

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

        <Box
          data-testid="score-how-we-got-to"
          sx={{
            mb: 2,
            p: compact ? 1 : 1.5,
            borderRadius: 1,
            bgcolor: compact ? 'transparent' : 'action.hover',
            border: compact ? 0 : 1,
            borderColor: 'divider',
          }}
        >
          <Typography
            component="h2"
            variant="subtitle2"
            sx={{ mb: 0.5 }}
            data-testid="score-how-we-got-to-title"
          >
            {path.title}
          </Typography>
          <Typography
            variant="body2"
            fontWeight={600}
            sx={{ fontVariantNumeric: 'tabular-nums' }}
            data-testid="score-how-we-got-to-equation"
          >
            {path.equation}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {path.caption}
          </Typography>
        </Box>

        {!hasRows ? (
          <Typography variant="body2" color="text.secondary">
            No score details available.
          </Typography>
        ) : (
          <Box data-testid="score-breakdown-details">
            {helps.length > 0 && (
              <Box sx={{ mb: 2 }}>
                <Typography
                  component="h2"
                  variant="subtitle2"
                  gutterBottom
                  data-testid="score-what-helps"
                >
                  What helps
                </Typography>
                <Box
                  component="ul"
                  sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexDirection: 'column', gap: 1.25 }}
                >
                  {helps.map(([dimension, points]) => {
                    const meta = getDimensionMeta(dimension, score_version)
                    return (
                      <Box
                        component="li"
                        key={dimension}
                        sx={{
                          display: 'grid',
                          gridTemplateColumns: { xs: '1fr auto', sm: 'minmax(0, 1fr) 72px' },
                          columnGap: 2,
                          alignItems: 'start',
                          py: 1,
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
                        </Box>
                        <Typography
                          variant="body2"
                          fontWeight={700}
                          sx={{ fontVariantNumeric: 'tabular-nums', textAlign: 'right', whiteSpace: 'nowrap' }}
                        >
                          {formatSignedPoints(points)}
                          {meta.maxPoints > 0 && (
                            <Typography component="span" variant="caption" color="text.secondary" fontWeight={400}>
                              {' '}
                              / {meta.maxPoints}
                            </Typography>
                          )}
                        </Typography>
                      </Box>
                    )
                  })}
                </Box>
              </Box>
            )}

            {adjustments.length > 0 && (
              <Box sx={{ mb: attribution.length ? 2 : 0 }}>
                <Typography
                  component="h2"
                  variant="subtitle2"
                  gutterBottom
                  data-testid="score-adjustments"
                >
                  Adjustments
                </Typography>
                <Box
                  component="ul"
                  sx={{ listStyle: 'none', m: 0, p: 0, display: 'flex', flexDirection: 'column', gap: 1.25 }}
                >
                  {adjustments.map(([dimension, points]) => {
                    const meta = getDimensionMeta(dimension, score_version)
                    const negative = points < 0
                    return (
                      <Box
                        component="li"
                        key={dimension}
                        sx={{
                          display: 'grid',
                          gridTemplateColumns: { xs: '1fr auto', sm: 'minmax(0, 1fr) 72px' },
                          columnGap: 2,
                          alignItems: 'start',
                          py: 1,
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
                        </Box>
                        <Typography
                          variant="body2"
                          fontWeight={700}
                          color={negative ? 'error.main' : 'text.primary'}
                          sx={{ fontVariantNumeric: 'tabular-nums', textAlign: 'right', whiteSpace: 'nowrap' }}
                        >
                          {formatSignedPoints(points)}
                        </Typography>
                      </Box>
                    )
                  })}
                </Box>
              </Box>
            )}

            {attribution.length > 0 && (
              <Box>
                <Typography variant="subtitle2" gutterBottom>
                  Attribution
                </Typography>
                {attribution.map(([dimension, points]) => {
                  const meta = getDimensionMeta(dimension, score_version)
                  return (
                    <Box key={dimension} sx={{ py: 1, borderTop: 1, borderColor: 'divider' }}>
                      <Typography variant="body2" fontWeight={600}>
                        {meta.label}{' '}
                        <Typography component="span" variant="body2" fontWeight={700}>
                          {formatPoints(points)}
                        </Typography>
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        Included in Structured Motivation (not added again)
                      </Typography>
                    </Box>
                  )
                })}
              </Box>
            )}
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
