/**
 * OMStatusPoller — polls job status every 3 seconds.
 *
 * Uses the standard GET /api/om-intake/jobs/{id} endpoint which has a
 * 2000/hour rate limit — well above what 3-second polling requires.
 */
import { useEffect, useRef, useState } from 'react'
import { Alert, Box, Button, CircularProgress, Typography } from '@mui/material'
import { omIntakeService } from '@/services/api'
import { IntakeStatus } from '@/types'

interface OMStatusPollerProps {
  jobId: number
  onReady: (jobId: number) => void
  onRetry?: (newJobId: number) => void
}

const POLL_INTERVAL_MS = 3000

const STATUS_MESSAGES: Partial<Record<IntakeStatus, string>> = {
  [IntakeStatus.PENDING]: 'Preparing…',
  [IntakeStatus.PARSING]: 'Reading PDF…',
  [IntakeStatus.EXTRACTING]: 'Extracting deal data with AI…',
  [IntakeStatus.RESEARCHING]: 'Researching market rents…',
}

export default function OMStatusPoller({ jobId, onReady, onRetry }: OMStatusPollerProps) {
  const [status, setStatus] = useState<IntakeStatus | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = () => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }

  const poll = async () => {
    try {
      const job = await omIntakeService.getOMJobStatus(jobId)
      setStatus(job.intake_status)

      if (job.intake_status === IntakeStatus.REVIEW) {
        stopPolling()
        onReady(jobId)
      } else if (job.intake_status === IntakeStatus.FAILED) {
        stopPolling()
        setErrorMessage(job.error_message ?? 'An unknown error occurred.')
      } else if (job.intake_status === IntakeStatus.CONFIRMED) {
        stopPolling()
      }
    } catch (err) {
      console.error('OMStatusPoller: poll error', err)
    }
  }

  useEffect(() => {
    poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)
    return () => stopPolling()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  const handleTryAgain = async () => {
    setRetrying(true)
    try {
      const result = await omIntakeService.retryOMJob(jobId)
      if (onRetry) onRetry(result.intake_job_id)
    } catch (err) {
      console.error('OMStatusPoller: retry error', err)
    } finally {
      setRetrying(false)
    }
  }

  if (status === IntakeStatus.FAILED) {
    return (
      <Box sx={{ mt: 2 }}>
        <Alert severity="error" sx={{ mb: 2 }}>{errorMessage}</Alert>
        <Button variant="contained" color="primary" onClick={handleTryAgain} disabled={retrying}>
          {retrying ? 'Retrying…' : 'Try Again'}
        </Button>
      </Box>
    )
  }

  if (status === IntakeStatus.CONFIRMED) return null

  const message = status !== null ? (STATUS_MESSAGES[status] ?? 'Processing…') : 'Preparing…'

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, mt: 4 }}>
      <CircularProgress />
      <Typography variant="body1" color="text.secondary">{message}</Typography>
    </Box>
  )
}
