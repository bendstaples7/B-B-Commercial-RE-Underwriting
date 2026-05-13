/**
 * OMIntakePage — top-level page for the Commercial OM PDF Intake workflow.
 *
 * Handles two routes:
 *   /multifamily/om-intake          → shows OMUploadForm
 *   /multifamily/om-intake/:jobId   → shows OMStatusPoller while processing,
 *                                     then OMReviewPanel when job reaches REVIEW
 *
 * Component behavior:
 *  1. No jobId in URL → render OMUploadForm
 *  2. jobId present:
 *     - Render OMStatusPoller while job is PENDING/PARSING/EXTRACTING/RESEARCHING
 *     - When OMStatusPoller calls onReady(jobId): fetch review data and render
 *       OMReviewPanel without a page reload
 *     - Display current Intake_Status throughout (OMStatusPoller and OMReviewPanel
 *       each display the status for their respective phases)
 *  3. When OMStatusPoller calls onRetry(newJobId): navigate to the new job's page
 *
 * Requirements: 6.1, 6.6, 6.11
 */
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Alert, Box, CircularProgress, Container, Typography } from '@mui/material'
import OMUploadForm from '@/components/multifamily/OMUploadForm'
import OMStatusPoller from '@/components/multifamily/OMStatusPoller'
import OMReviewPanel from '@/components/multifamily/OMReviewPanel'
import { omIntakeService } from '@/services/api'
import type { OMIntakeReviewData } from '@/types'

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OMIntakePage() {
  const { jobId: jobIdParam } = useParams<{ jobId?: string }>()
  const navigate = useNavigate()

  // Parsed numeric job ID (undefined when on the upload route)
  const jobId = jobIdParam !== undefined ? Number(jobIdParam) : undefined

  // Review data — set when the job reaches REVIEW status
  const [reviewData, setReviewData] = useState<OMIntakeReviewData | null>(null)
  const [isLoadingReview, setIsLoadingReview] = useState(false)
  const [reviewLoadError, setReviewLoadError] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Callbacks
  // ---------------------------------------------------------------------------

  /**
   * Called by OMStatusPoller when the job transitions to REVIEW.
   * Fetches the full review data and renders OMReviewPanel without a page reload.
   */
  const handleReady = async (readyJobId: number) => {
    setIsLoadingReview(true)
    setReviewLoadError(null)

    try {
      const data = await omIntakeService.getOMJobReview(readyJobId)
      setReviewData(data)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to load review data.'
      setReviewLoadError(message)
    } finally {
      setIsLoadingReview(false)
    }
  }

  /**
   * Called by OMStatusPoller when the user clicks "Try Again" on a FAILED job.
   * Navigates to the new job's page and resets local state.
   */
  const handleRetry = (newJobId: number) => {
    setReviewData(null)
    setReviewLoadError(null)
    navigate(`/multifamily/om-intake/${newJobId}`)
  }

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const isUploadRoute = jobId === undefined || Number.isNaN(jobId)
  const pageTitle = reviewData ? 'OM Intake Review' : 'Upload OM PDF'

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Container maxWidth="lg">
      {/* Page title */}
      <Typography variant="h5" component="h1" gutterBottom sx={{ mb: 3 }}>
        {pageTitle}
      </Typography>

      {/* ── Route: no jobId → show upload form ── */}
      {isUploadRoute && <OMUploadForm />}

      {/* ── Route: jobId present ── */}
      {!isUploadRoute && jobId !== undefined && (
        <Box>
          {/* Show poller while review data hasn't loaded yet */}
          {!reviewData && !isLoadingReview && !reviewLoadError && (
            <OMStatusPoller
              jobId={jobId}
              onReady={handleReady}
              onRetry={handleRetry}
            />
          )}

          {/* Loading review data */}
          {isLoadingReview && (
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 2,
                mt: 4,
              }}
            >
              <CircularProgress />
              <Typography variant="body1" color="text.secondary">
                Loading review data…
              </Typography>
            </Box>
          )}

          {/* Review load error */}
          {reviewLoadError && !isLoadingReview && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {reviewLoadError}
            </Alert>
          )}

          {/* Review panel — shown once review data is available */}
          {reviewData && !isLoadingReview && (
            <OMReviewPanel
              reviewData={reviewData}
              jobId={jobId}
            />
          )}
        </Box>
      )}
    </Container>
  )
}

export default OMIntakePage
