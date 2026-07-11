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

const ATTRIBUTION_ONLY_KEYS = new Set(['notes_keywords'])

export interface ScoreBreakdownDialogProps {
  score: PropertyScoreRecord
  open: boolean
  onClose: () => void
  onViewFullBreakdown?: () => void
}

function formatPoints(points: number): string {
  const rounded = Math.round(points * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

export function ScoreBreakdownDialog({
  score,
  open,
  onClose,
  onViewFullBreakdown,
}: ScoreBreakdownDialogProps) {
  const versionMeta = getScoreVersionMeta(score.score_version)
  const breakdownEntries = Object.entries(score.score_details).sort(([, a], [, b]) => b - a)

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

        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          How this score was calculated
        </Typography>

        {breakdownEntries.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No score details available.
          </Typography>
        ) : (
          <Box component="ul" sx={{ listStyle: 'none', m: 0, p: 0 }} data-testid="score-breakdown-details">
            {breakdownEntries.map(([dimension, points], index) => {
              const meta = getDimensionMeta(dimension, score.score_version)
              return (
                <Box
                  component="li"
                  key={dimension}
                  sx={{
                    py: 1.25,
                    borderTop: index > 0 ? 1 : 0,
                    borderColor: 'divider',
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
                      sx={{ fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}
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
            })}
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
