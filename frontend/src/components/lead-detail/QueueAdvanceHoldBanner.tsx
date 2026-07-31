/**
 * Queue advance hold chrome — brief draining progress before auto-advancing
 * to the next lead, with Pause to stay put.
 */
import { Box, Button, LinearProgress, Typography } from '@mui/material'

export const QUEUE_ADVANCE_HOLD_MS = 2000

export interface QueueAdvanceHoldBannerProps {
  message: string
  /** Determinate progress 100 → 0 (draining). */
  progress: number
  onPause: () => void
}

export function QueueAdvanceHoldBanner({
  message,
  progress,
  onPause,
}: QueueAdvanceHoldBannerProps) {
  const clamped = Math.max(0, Math.min(100, progress))

  return (
    <Box
      data-testid="queue-advance-hold"
      sx={{
        px: { xs: 1, sm: 2 },
        py: 0.75,
        bgcolor: 'background.paper',
        borderBottom: 1,
        borderColor: 'divider',
        overflow: 'visible',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1,
          flexWrap: 'wrap',
          mb: 0.5,
        }}
      >
        <Typography
          variant="body2"
          sx={{ minWidth: 0, flex: '1 1 auto', color: 'text.primary' }}
        >
          {message}
          <Typography
            component="span"
            variant="body2"
            color="text.secondary"
            sx={{ ml: 1 }}
          >
            Next lead…
          </Typography>
        </Typography>
        <Button
          size="small"
          variant="outlined"
          onClick={onPause}
          data-testid="queue-advance-pause"
          aria-label="Pause and stay on this lead"
          sx={{ cursor: 'pointer', flexShrink: 0 }}
        >
          Pause
        </Button>
      </Box>
      <LinearProgress
        variant="determinate"
        value={clamped}
        aria-label="Advancing to next lead"
        sx={{
          height: 4,
          borderRadius: 1,
          transition: 'none',
        }}
      />
    </Box>
  )
}
