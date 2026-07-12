/**
 * Shared initial-load spinner for work queues.
 */
import { Box, CircularProgress } from '@mui/material'

export function QueueLoadingState() {
  return (
    <Box
      sx={{ display: 'flex', justifyContent: 'center', p: 4 }}
      data-testid="queue-loading"
    >
      <CircularProgress />
    </Box>
  )
}
