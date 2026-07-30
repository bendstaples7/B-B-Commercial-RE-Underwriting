/**
 * ScoreBreakdownDialog — modal score breakdown opened from the command center header.
 * Clear open/close affordances: X button, Close button, backdrop click, Escape.
 */
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import type { PropertyScoreRecord } from '@/types'
import { LeadScoreBadge } from './LeadScoreBadge'
import { getDimensionMeta, getScoreVersionMeta } from '@/utils/scoreDimensionMeta'
import {
  ATTRIBUTION_ONLY_KEYS,
  buildScorePathSummary,
  formatSignedPoints,
  partitionScoreDetails,
} from '@/utils/scoreBreakdownSummary'

export interface ScoreBreakdownDialogProps {
  score: PropertyScoreRecord
  open: boolean
  onClose: () => void
  onViewFullBreakdown?: () => void
}

function DimensionRow({
  dimension,
  points,
  scoreVersion,
  isAdjustment,
}: {
  dimension: string
  points: number
  scoreVersion: string
  isAdjustment?: boolean
}) {
  const meta = getDimensionMeta(dimension, scoreVersion)
  const negative = points < 0
  return (
    <Box
      component="li"
      sx={{
        py: 1.25,
        borderTop: 1,
        borderColor: 'divider',
        '&:first-of-type': { borderTop: 0 },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          gap: 2,
          mb: 0.5,
        }}
      >
        <Typography variant="body2" fontWeight={600}>
          {meta.label}
        </Typography>
        <Typography
          variant="body2"
          fontWeight={700}
          color={negative ? 'error.main' : 'text.primary'}
          sx={{ fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}
        >
          {ATTRIBUTION_ONLY_KEYS.has(dimension) ? formatSignedPoints(points).replace(/^[+−]/, '') : formatSignedPoints(points)}
          {!isAdjustment && meta.maxPoints > 0 && (
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
      </Box>
      <Typography variant="caption" color="text.secondary" display="block">
        {meta.description}
      </Typography>
      {ATTRIBUTION_ONLY_KEYS.has(dimension) && (
        <Typography variant="caption" color="text.secondary" display="block">
          Included in Structured Motivation (not added again)
        </Typography>
      )}
      <Typography variant="caption" color="text.disabled" display="block">
        Data: {meta.dataSource}
      </Typography>
    </Box>
  )
}

export function ScoreBreakdownDialog({
  score,
  open,
  onClose,
  onViewFullBreakdown,
}: ScoreBreakdownDialogProps) {
  const versionMeta = getScoreVersionMeta(score.score_version)
  const path = buildScorePathSummary(score.score_details, score.total_score)
  const { helps, adjustments, attribution } = partitionScoreDetails(score.score_details)
  const hasRows = helps.length + adjustments.length + attribution.length > 0

  const handleViewHistory = () => {
    onClose()
    onViewFullBreakdown?.()
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      aria-labelledby="score-breakdown-dialog-title"
      data-testid="score-breakdown-dialog"
    >
      <DialogTitle
        id="score-breakdown-dialog-title"
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 1,
          pr: 1,
        }}
      >
        <Box>
          <Typography variant="overline" color="text.secondary" display="block">
            Lead score breakdown
          </Typography>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mt: 0.5 }}>
            <Typography variant="h4" component="span" fontWeight={700}>
              {Math.round(score.total_score)}
            </Typography>
            <Typography variant="body1" color="text.secondary" component="span">
              / 100
            </Typography>
            <LeadScoreBadge tier={score.score_tier} size="medium" />
          </Stack>
        </Box>
        <IconButton
          onClick={onClose}
          aria-label="Close score breakdown"
          data-testid="score-breakdown-close"
          sx={{ mt: -0.5 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers sx={{ pt: 2 }}>
        <Stack
          direction="row"
          spacing={3}
          sx={{ mb: 2 }}
          divider={<Divider orientation="vertical" flexItem />}
        >
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">
              Data quality
            </Typography>
            <Typography variant="body2" fontWeight={600}>
              {Math.round(score.data_quality_score)} / 100
            </Typography>
          </Box>
          <Box>
            <Stack direction="row" spacing={0.5} alignItems="center">
              <Typography variant="caption" color="text.secondary">
                Scoring model
              </Typography>
              <Tooltip title={versionMeta.description} arrow>
                <InfoOutlinedIcon sx={{ fontSize: 14, color: 'text.disabled' }} />
              </Tooltip>
            </Stack>
            <Typography variant="body2" fontWeight={600}>
              {versionMeta.shortLabel}
            </Typography>
          </Box>
        </Stack>

        <Box
          data-testid="score-how-we-got-to"
          sx={{
            mb: 2.5,
            p: 1.5,
            borderRadius: 1,
            bgcolor: 'action.hover',
            border: 1,
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
            sx={{ fontVariantNumeric: 'tabular-nums', lineHeight: 1.4 }}
            data-testid="score-how-we-got-to-equation"
          >
            {path.equation}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
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
              <Box sx={{ mb: adjustments.length || attribution.length ? 2 : 0 }}>
                <Typography
                  component="h2"
                  variant="subtitle2"
                  sx={{ mb: 0.5 }}
                  data-testid="score-what-helps"
                >
                  What helps
                </Typography>
                <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
                  {helps.map(([dimension, points]) => (
                    <DimensionRow
                      key={dimension}
                      dimension={dimension}
                      points={points}
                      scoreVersion={score.score_version}
                    />
                  ))}
                </Box>
              </Box>
            )}

            {adjustments.length > 0 && (
              <Box sx={{ mb: attribution.length ? 2 : 0 }}>
                <Typography
                  component="h2"
                  variant="subtitle2"
                  sx={{ mb: 0.5 }}
                  data-testid="score-adjustments"
                >
                  Adjustments
                </Typography>
                <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
                  {adjustments.map(([dimension, points]) => (
                    <DimensionRow
                      key={dimension}
                      dimension={dimension}
                      points={points}
                      scoreVersion={score.score_version}
                      isAdjustment
                    />
                  ))}
                </Box>
              </Box>
            )}

            {attribution.length > 0 && (
              <Box>
                <Typography component="h2" variant="subtitle2" sx={{ mb: 0.5 }}>
                  Attribution
                </Typography>
                <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }}>
                  {attribution.map(([dimension, points]) => (
                    <DimensionRow
                      key={dimension}
                      dimension={dimension}
                      points={points}
                      scoreVersion={score.score_version}
                    />
                  ))}
                </Box>
              </Box>
            )}
          </Box>
        )}
      </DialogContent>

      <DialogActions sx={{ px: 3, py: 2, justifyContent: 'space-between' }}>
        {onViewFullBreakdown ? (
          <Button onClick={handleViewHistory} data-testid="score-breakdown-view-history">
            View score history
          </Button>
        ) : (
          <span />
        )}
        <Button variant="contained" onClick={onClose} data-testid="score-breakdown-done">
          Close
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default ScoreBreakdownDialog
