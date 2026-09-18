/**
 * Queue advance hold chrome — draining progress before auto-advancing
 * to the next lead, with Pause to stay put.
 *
 * Visual drain is a single CSS transform 100 → 0 over QUEUE_ADVANCE_HOLD_MS
 * so it stays in lockstep with the navigation timer even if the main thread
 * hitchs. (MUI LinearProgress's default 0.4s bar transition is overridden.)
 *
 * Renders as a zero-in-flow-height overlay absolutely positioned inside its
 * sticky parent (cc-sticky-chrome) so it never pushes Property Overview down.
 */
import { useEffect, useState } from 'react'
import { Box, Button, LinearProgress, Typography } from '@mui/material'

/** Pause window before auto-advancing. Visual drain uses this same duration. */
export const QUEUE_ADVANCE_HOLD_MS = 5000

/** Above cc-sticky-chrome's own z-index so the overlay always wins the stack. */
export const QUEUE_ADVANCE_HOLD_Z_INDEX = 150

export function queueAdvanceDrainTransition(durationMs: number): string {
  return `transform ${durationMs}ms linear`
}

export interface QueueAdvanceHoldBannerProps {
  message: string
  /** Drain duration; must match the parent navigation timer. */
  durationMs?: number
  onPause: () => void
}

export function QueueAdvanceHoldBanner({
  message,
  durationMs = QUEUE_ADVANCE_HOLD_MS,
  onPause,
}: QueueAdvanceHoldBannerProps) {
  // Paint 100% first, then flip to 0 so the CSS transition actually runs.
  const [progress, setProgress] = useState(100)

  useEffect(() => {
    let inner = 0
    const outer = window.requestAnimationFrame(() => {
      inner = window.requestAnimationFrame(() => setProgress(0))
    })
    return () => {
      window.cancelAnimationFrame(outer)
      window.cancelAnimationFrame(inner)
    }
  }, [])

  return (
    <Box
      data-testid="queue-advance-hold"
      role="status"
      aria-live="polite"
      sx={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        zIndex: QUEUE_ADVANCE_HOLD_Z_INDEX,
        px: { xs: 1, sm: 2 },
        py: 0.75,
        bgcolor: 'background.paper',
        borderBottom: 1,
        borderColor: 'divider',
        boxShadow: '0 2px 8px rgba(16, 24, 40, 0.12)',
        cursor: 'auto',
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
          sx={{ minWidth: 0, flex: '1 1 auto', color: 'text.primary', cursor: 'auto' }}
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
        value={progress}
        aria-label="Advancing to next lead"
        data-testid="queue-advance-hold-bar"
        data-drain-ms={durationMs}
        sx={{
          height: 4,
          borderRadius: 1,
          cursor: 'auto',
          '& .MuiLinearProgress-bar, & .MuiLinearProgress-bar1Determinate': {
            transition: queueAdvanceDrainTransition(durationMs),
          },
        }}
      />
    </Box>
  )
}
