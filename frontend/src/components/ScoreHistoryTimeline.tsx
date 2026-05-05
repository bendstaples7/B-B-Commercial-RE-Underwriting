/**
 * ScoreHistoryTimeline — chronological list of a lead's past score records.
 *
 * Renders on the Lead Detail page to show how a lead's score has evolved
 * over time. Each entry displays:
 *   • created_at (formatted via `toLocaleString`)
 *   • total_score with score_tier via LeadScoreBadge
 *   • data_quality_score
 *   • recommended_action (human-readable)
 *   • delta from the previous (older) score, when available
 *
 * Records are displayed newest-first so the latest score is immediately
 * visible. The delta shown on each row compares that row's total_score to
 * the next-older record's total_score.
 *
 * Satisfies Requirement 11.4.
 */
import {
  Box,
  Card,
  CardContent,
  Divider,
  List,
  ListItem,
  Stack,
  Typography,
} from '@mui/material'
import { Fragment } from 'react'
import type { LeadScoreRecord, RecommendedAction } from '@/types'
import { LeadScoreBadge } from './LeadScoreBadge'

export interface ScoreHistoryTimelineProps {
  /** All score records for a lead, in any order. */
  history: LeadScoreRecord[]
  /** Optional className passthrough. */
  className?: string
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

function humanize(snake: string): string {
  if (!snake) return ''
  return snake
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}

function actionLabel(action: RecommendedAction): string {
  return ACTION_LABELS[action] ?? humanize(action)
}

/**
 * Format an ISO timestamp via `toLocaleString`. Falls back to the raw value
 * when the input cannot be parsed (e.g. a malformed server response).
 */
function formatTimestamp(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) {
    return iso
  }
  return d.toLocaleString()
}

/** Format a signed delta like "+5" or "-3" (zero collapses to "0"). */
function formatDelta(delta: number): string {
  if (delta > 0) return `+${delta}`
  if (delta < 0) return `${delta}`
  return '0'
}

export function ScoreHistoryTimeline({
  history,
  className,
}: ScoreHistoryTimelineProps) {
  // Sort a shallow copy newest-first so consumers can pass the array in any
  // order without mutating the original reference.
  const sorted = [...history].sort(
    (a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )

  return (
    <Card
      variant="outlined"
      className={className}
      data-testid="score-history-timeline"
    >
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Score History
        </Typography>

        {sorted.length === 0 ? (
          <Typography
            variant="body2"
            color="text.secondary"
            data-testid="score-history-empty"
          >
            No score history yet. Run a recalculation to generate the first score.
          </Typography>
        ) : (
          <List dense disablePadding data-testid="score-history-list">
            {sorted.map((record, idx) => {
              const previous = sorted[idx + 1] // next item is the older record
              const delta = previous
                ? Math.round(record.total_score) -
                  Math.round(previous.total_score)
                : null
              const isLast = idx === sorted.length - 1

              return (
                <Fragment key={record.id}>
                  <ListItem
                    disableGutters
                    sx={{ display: 'block', py: 1 }}
                    data-testid="score-history-item"
                  >
                    <Stack
                      direction="row"
                      spacing={2}
                      alignItems="center"
                      flexWrap="wrap"
                      useFlexGap
                    >
                      <Typography
                        variant="h5"
                        component="span"
                        sx={{ fontVariantNumeric: 'tabular-nums' }}
                        data-testid="score-history-total"
                      >
                        {Math.round(record.total_score)}
                      </Typography>
                      <LeadScoreBadge tier={record.score_tier} size="small" />
                      {delta !== null && (
                        <Typography
                          variant="body2"
                          color={
                            delta > 0
                              ? 'success.main'
                              : delta < 0
                              ? 'error.main'
                              : 'text.secondary'
                          }
                          data-testid="score-history-delta"
                        >
                          {formatDelta(delta)} from previous
                        </Typography>
                      )}
                    </Stack>

                    <Stack
                      direction={{ xs: 'column', sm: 'row' }}
                      spacing={{ xs: 0.5, sm: 2 }}
                      sx={{ mt: 0.5 }}
                    >
                      <Typography
                        variant="body2"
                        color="text.secondary"
                        data-testid="score-history-timestamp"
                      >
                        {formatTimestamp(record.created_at)}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Data quality: {Math.round(record.data_quality_score)} / 100
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Action: {actionLabel(record.recommended_action)}
                      </Typography>
                    </Stack>
                  </ListItem>
                  {!isLast && <Divider component="li" />}
                </Fragment>
              )
            })}
          </List>
        )}
      </CardContent>
    </Card>
  )
}

export default ScoreHistoryTimeline
