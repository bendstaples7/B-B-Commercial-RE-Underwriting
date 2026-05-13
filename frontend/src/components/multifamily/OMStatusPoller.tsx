/**
 * OMStatusPoller — polls job status every 3 seconds.
 *
 * Uses setTimeout (not setInterval) to prevent overlapping requests.
 * Surfaces poll errors to the user after 3 consecutive failures.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { Alert, Box, Button, CircularProgress, Typography } from '@mui/material'
import { omIntakeService } from '@/services/api'
import { IntakeStatus } from '@/types'

interface OMStatusPollerProps {
  jobId: number
  onReady: (jobId: number) => void
  onRetry?: (newJobId: number) => void
}

const POLL_INTERVAL_MS = 3000
const MAX_CONSECUTIVE_ERRORS = 3

const STATUS_MESSAGES: Partial<Record<IntakeStatus, string>> = {
  [IntakeStatus.PENDING]: 'Preparing…',
  [IntakeStatus.PARSING]: 'Reading PDF…',
  [IntakeStatus.EXTRACTING]: 'Extracting deal data with AI…',
  [IntakeStatus.RESEARCHING]: 'Researching market rents…',
}

export default function OMStatusPoller({ jobId, onReady, onRetry }: OMStatusPollerProps) {
  const [status, setStatus] = useState<IntakeStatus | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)

  // Use refs to avoid stale closures in the recursive setTimeout
  const activeRef = useRef(true)
  const consecutiveErrorsRef = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const stopPolling = useCallback(() => {
    activeRef.current = false
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  const scheduleNextPoll = useCallback((pollFn: () => Promise<void>) => {
    if (!activeRef.current) return
    timeoutRef.current = setTimeout(pollFn, POLL_INTERVAL_MS)
  }, [])

  useEffect(() => {
    activeRef.current = true
    consecutiveErrorsRef.current = 0

    const poll = async () => {
      if (!activeRef.current) return

      try {
        const job = await omIntakeService.getOMJobStatus(jobId)
        consecutiveErrorsRef.current = 0
        setPollError(null)

        if (!activeRef.current) return
        setStatus(job.intake_status)

        if (job.intake_status === IntakeStatus.REVIEW) {
          stopPolling()
          onReady(jobId)
        } else if (job.intake_status === IntakeStatus.FAILED) {
          stopPolling()
          setErrorMessage(job.error_message ?? 'An unknown error occurred.')
        } else if (job.intake_status === IntakeStatus.CONFIRMED) {
          stopPolling()
        } else {
          scheduleNextPoll(poll)
        }
      } catch (err) {
        consecutiveErrorsRef.current += 1
        console.error('OMStatusPoller: poll error', err)

        if (consecutiveErrorsRef.current >= MAX_CONSECUTIVE_ERRORS) {
          stopPolling()
          setPollError(
            `Lost connection to the server after ${MAX_CONSECUTIVE_ERRORS} attempts. ` +
            'Please refresh the page to check the status.'
          )
        } else {
          scheduleNextPoll(poll)
        }
      }
    }

    poll()
    return () => stopPolling()
  }, [jobId, onReady, stopPolling, scheduleNextPoll])

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

  if (pollError) {
    return (
      <Box sx={{ mt: 2 }}>
        <Alert severity="warning">{pollError}</Alert>
      </Box>
    )
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
