/**
 * ReadyToMailQueue — operational home for direct mail batching.
 */
import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Skeleton,
  Stack,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailBatchSummary } from './MailBatchSummary'
import { MailQueueStagedAccordion } from './MailQueueStagedAccordion'
import { MailCampaignsPanel } from './MailCampaignsPanel'
import { AppSnackbar } from './AppSnackbar'
import { QueueTable } from './QueueTable'
import type { ExtraColumn, RowAction } from './QueueTable'
import { queueService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { formatLastMailedDate, formatLastSaleDate } from '@/utils/formatLastMailedDate'
import { useShellStatus } from '@/context/ShellStatusContext'
import {
  enqueueResultSeverity,
  formatEnqueuePreview,
  formatEnqueueSummary,
  type EnqueueCounts,
} from '@/utils/formatEnqueueSummary'
import type { EnqueuePreviewResult } from '@/services/openLetterApi'
import {
  bumpMailQueueAfterEnqueue,
  createAddToMailBatchRowAction,
  enqueueLeadsAsBulkResult,
  invalidateMailQueries,
  addedLeadIds,
  resolveBulkActions,
  stripMailCandidatesFromCache,
} from './queueBulkActions'
import { useQueueSelection } from '@/hooks/useQueueSelection'
import { useAuth } from '@/context/AuthContext'
import {
  isMailCampaignSubmitting,
  isRecentMailCampaignSubmitted,
} from '@/utils/mailCampaignStatusColor'

export function ReadyToMailQueue() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [candidatesPage, setCandidatesPage] = useState(1)
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()
  const [snackbarMessage, setSnackbarMessage] = useState<string | null>(null)
  const [snackbarSeverity, setSnackbarSeverity] =
    useState<'success' | 'warning' | 'error'>('success')
  const [isAddingPage, setIsAddingPage] = useState(false)
  const [confirmAdd, setConfirmAdd] = useState<{
    limit?: number
    preview: EnqueuePreviewResult
  } | null>(null)

  const { setStatusLabel } = useShellStatus()

  const { data: queueData, isLoading: queueLoading, error: queueError, refetch: refetchQueue, isFetching: queueFetching } = useQuery({
    queryKey: ['mail-queue'],
    // Fetch the full staged batch (all pages) — the accordion shows every item.
    queryFn: () => openLetterService.getAllQueued(),
    refetchInterval: 60_000,
  })

  const { data: candidatesData, isLoading: candidatesLoading, isFetching: candidatesFetching } = useQuery({
    queryKey: ['queue-mail-candidates', candidatesPage],
    queryFn: () => queueService.getMailCandidates(candidatesPage, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  useEffect(() => {
    // Background refresh only — first paint uses in-card skeletons, not the AppBar.
    let label: string | null = null
    if (queueFetching && queueData) {
      label = 'Refreshing mail batch…'
    } else if (candidatesFetching && candidatesData) {
      label = 'Refreshing mail recommendations…'
    }
    setStatusLabel('ready-to-mail', label)
    return () => setStatusLabel('ready-to-mail', null)
  }, [
    queueFetching,
    queueData,
    candidatesFetching,
    candidatesData,
    setStatusLabel,
  ])

  const { data: campaignsData } = useQuery({
    queryKey: ['mail-campaigns'],
    queryFn: () => openLetterService.listCampaigns(1, 100),
    refetchInterval: (query) => {
      const list = query.state.data?.campaigns ?? []
      const submitting = list.some((c) => isMailCampaignSubmitting(c.status))
      return submitting ? 5_000 : 60_000
    },
    refetchIntervalInBackground: false,
  })
  const campaigns = campaignsData?.campaigns ?? []
  const submittingCampaigns = campaigns.filter((c) => isMailCampaignSubmitting(c.status))
  const submittedCampaigns = campaigns
    .filter((c) => isRecentMailCampaignSubmitted(c))
    .sort((a, b) => {
      const ta = new Date(a.submitted_at || a.created_at || 0).getTime()
      const tb = new Date(b.submitted_at || b.created_at || 0).getTime()
      return tb - ta
    })

  const showEnqueueFeedback = (result: EnqueueCounts) => {
    setSnackbarSeverity(enqueueResultSeverity(result))
    setSnackbarMessage(formatEnqueueSummary(result))
  }

  const showEnqueueError = (error: unknown) => {
    setSnackbarSeverity('error')
    setSnackbarMessage(
      error instanceof Error ? error.message : 'Failed to add leads to batch. Try again.',
    )
  }

  const enqueueCandidatesMutation = useMutation({
    mutationFn: (limit?: number) => openLetterService.enqueueCandidates(limit),
    onSuccess: (result) => {
      // Candidates enqueue has no stable requested ID list (limit-based); strip from results only.
      stripMailCandidatesFromCache(queryClient, addedLeadIds(result, []))
      bumpMailQueueAfterEnqueue(queryClient, result)
      invalidateMailQueries(queryClient)
      clearSelection()
      setCandidatesPage(1)
      showEnqueueFeedback(result)
    },
    onError: showEnqueueError,
  })

  const previewMutation = useMutation({
    mutationFn: (limit?: number) => openLetterService.previewEnqueueCandidates(limit),
    onError: showEnqueueError,
  })

  const candidateRows = candidatesData?.rows ?? []
  const candidateTotal = candidatesData?.total ?? 0
  const candidateTotalPages = computeTotalPages(candidateTotal, candidatesData?.per_page ?? 20)
  const queuedCount = queueData?.queued_count ?? 0
  const batchMinimum = queueData?.batch_minimum ?? 50
  const neededForMinimum = Math.max(0, batchMinimum - queuedCount)

  const handleCandidatesPageChange = onPageChangeWithClear((newPage) => {
    setCandidatesPage(clampPage(newPage, candidateTotalPages))
  })

  const runEnqueueCandidates = async (limit?: number) => {
    setConfirmAdd(null)
    try {
      await enqueueCandidatesMutation.mutateAsync(limit)
    } catch {
      // Error is surfaced by enqueueCandidatesMutation.onError.
    }
  }

  const requestEnqueueCandidates = async (limit?: number) => {
    try {
      const preview = await previewMutation.mutateAsync(limit)
      if (preview.would_add === 0) {
        setSnackbarSeverity('success')
        setSnackbarMessage(formatEnqueuePreview(preview))
        return
      }
      setConfirmAdd({ limit, preview })
    } catch {
      // Error is surfaced by previewMutation.onError.
    }
  }

  const isEnqueueing =
    enqueueCandidatesMutation.isPending
    || previewMutation.isPending

  const fromQueue = { key: 'mail-candidates', label: 'Ready to Mail' }

  const bulkCtx = {
    queryClient,
    queryKey: 'queue-mail-candidates',
    onAfterAction: () => {
      clearSelection()
      setCandidatesPage(1)
    },
    onEnqueueResult: showEnqueueFeedback,
    onEnqueueError: showEnqueueError,
  }

  const rowActions: RowAction[] = [createAddToMailBatchRowAction(bulkCtx)]
  const bulkActions = resolveBulkActions(['add_to_mail_batch'], bulkCtx)

  const addDisplayedPage = async () => {
    if (candidateRows.length === 0) return
    setIsAddingPage(true)
    try {
      await enqueueLeadsAsBulkResult(candidateRows.map((row) => row.id), bulkCtx)
    } catch {
      // Error is surfaced through bulkCtx.onEnqueueError.
    } finally {
      setIsAddingPage(false)
    }
  }

  const lastMailedColumn: ExtraColumn = {
    key: 'last_mailed_at',
    label: 'Last mailed',
    render: (row) => formatLastMailedDate(row.last_mailed_at),
  }

  const lastSaleColumn: ExtraColumn = {
    key: 'last_sale_at',
    label: 'Last sale',
    render: (row) => formatLastSaleDate(row.last_sale_at),
  }

  const queueErrorMessage =
    queueError instanceof Error ? queueError.message : 'Failed to load mail queue.'

  const preview = confirmAdd?.preview
  const previewWouldAdd = preview?.would_add ?? 0

  return (
    <Box
      data-testid="ready-to-mail-queue"
      sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
    >
      <Typography variant="h5" component="h1" gutterBottom sx={{ overflowWrap: 'anywhere' }}>
        Ready to Mail
      </Typography>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ mb: 2, overflowWrap: 'anywhere', wordBreak: 'break-word' }}
      >
        Batch queue for your next Open Letter send. Marketing / outreach lists are audience membership
        only — add members here (or via &quot;Add to mail queue&quot;) when they are ready to mail.
        Stage leads, send when you hit your minimum, and review recent sends.
      </Typography>

      {submittingCampaigns.length > 0 && (
        <Alert
          severity="info"
          sx={{ mb: 2 }}
          data-testid="mail-submitting-banner"
          action={user?.is_admin ? (
            <Button
              color="inherit"
              size="small"
              component={RouterLink}
              to="/admin/background-jobs"
            >
              View queue
            </Button>
          ) : undefined}
        >
          Sending {submittingCampaigns.length === 1 ? 'campaign' : `${submittingCampaigns.length} campaigns`}
          {submittingCampaigns[0] ? ` #${submittingCampaigns[0].id}` : ''} to Open Letter…
        </Alert>
      )}

      {submittedCampaigns.length > 0 && (
        <Alert
          severity="success"
          sx={{ mb: 2 }}
          data-testid="mail-submitted-banner"
          action={(
            <Button
              color="inherit"
              size="small"
              component={RouterLink}
              to="/marketing/direct-mail/batches"
            >
              View batches
            </Button>
          )}
        >
          {submittedCampaigns.length === 1 ? (
            <>
              Submitted to Open Letter — order accepted (#{submittedCampaigns[0].id}
              {submittedCampaigns[0].olc_order_id
                ? `, OLC ${submittedCampaigns[0].olc_order_id}`
                : ''}
              )
              {submittedCampaigns[0].staged_count != null
                && submittedCampaigns[0].submitted_count != null
                && submittedCampaigns[0].staged_count !== submittedCampaigns[0].submitted_count
                ? ` · Staged ${submittedCampaigns[0].staged_count} → submitted ${submittedCampaigns[0].submitted_count}`
                  + (submittedCampaigns[0].invalid_at_submit_count
                    ? ` (${submittedCampaigns[0].invalid_at_submit_count} invalid locally)`
                    : '')
                  + (submittedCampaigns[0].submit_drop_summary
                    ? ` · ${Object.entries(submittedCampaigns[0].submit_drop_summary)
                      .map(([reason, n]) => `${n}× ${reason}`)
                      .join(', ')}`
                    : '')
                : ''}
              .
            </>
          ) : (
            <>
              {submittedCampaigns.length} campaigns submitted to Open Letter
              (latest #{submittedCampaigns[0].id}).
            </>
          )}
        </Alert>
      )}

      {queueError ? (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={() => refetchQueue()} disabled={queueFetching}>
              Retry
            </Button>
          }
          data-testid="mail-queue-error"
        >
          {queueErrorMessage}
        </Alert>
      ) : (
        <MailBatchSummary title="Next batch" queueData={queueData} isLoading={queueLoading} />
      )}

      <Divider sx={{ my: 3 }} />

      <Box
        sx={{
          display: 'flex',
          alignItems: { xs: 'stretch', md: 'center' },
          justifyContent: 'space-between',
          flexDirection: { xs: 'column', md: 'row' },
          gap: 1.5,
          mb: 2,
        }}
      >
        <Box>
          <Typography variant="h6">Recommended for mail</Typography>
          <Typography variant="body2" color="text.secondary">
            Leads scored as mail-ready that are not yet in your batch ({candidateTotal} total).
          </Typography>
        </Box>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          sx={{ justifyContent: 'flex-end' }}
        >
          <Button
            variant="outlined"
            size="small"
            disabled={isEnqueueing || neededForMinimum === 0 || candidateTotal === 0}
            onClick={() => void requestEnqueueCandidates(neededForMinimum)}
            data-testid="add-to-minimum-button"
          >
            Add {neededForMinimum} to reach minimum
          </Button>
          <Button
            variant="outlined"
            size="small"
            disabled={isEnqueueing || isAddingPage || candidateRows.length === 0}
            onClick={() => void addDisplayedPage()}
            data-testid="add-page-candidates-button"
          >
            Add {candidateRows.length} from this page
          </Button>
          <Button
            variant="contained"
            size="small"
            disabled={isEnqueueing || candidateTotal === 0}
            onClick={() => void requestEnqueueCandidates(undefined)}
            data-testid="add-all-candidates-button"
          >
            {isEnqueueing ? 'Checking…' : `Add all ${candidateTotal} to batch`}
          </Button>
        </Stack>
      </Box>

      <QueueTable
        rows={candidateRows}
        total={candidateTotal}
        disabled={candidatesLoading && candidateRows.length === 0}
        fromQueue={fromQueue}
        selectedIds={selectedIds}
        onSelectionChange={onSelectionChange}
        rowActions={rowActions}
        bulkActions={bulkActions}
        extraColumns={[lastMailedColumn, lastSaleColumn]}
        {...(candidateTotalPages > 1
          ? {
              page: candidatesPage,
              totalPages: candidateTotalPages,
              onPageChange: handleCandidatesPageChange,
            }
          : {})}
      />

      <Divider sx={{ my: 3 }} />

      {queueLoading && !queueData ? (
        <Skeleton variant="rounded" height={64} sx={{ mb: 2 }} data-testid="mail-staged-skeleton" />
      ) : queueError ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Staged leads are unavailable until the mail queue loads.
        </Typography>
      ) : (
        <MailQueueStagedAccordion items={queueData?.items ?? []} />
      )}

      <Divider sx={{ my: 3 }} />

      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 1,
          mb: 2,
        }}
      >
        <Typography variant="h6" component="h2" sx={{ m: 0 }}>
          Recent sends
        </Typography>
        <Button
          size="small"
          component={RouterLink}
          to="/marketing/direct-mail/batches"
          data-testid="view-all-mail-batches"
        >
          View all mail batches
        </Button>
      </Box>
      <MailCampaignsPanel embedded />

      <Dialog
        open={confirmAdd !== null}
        onClose={() => setConfirmAdd(null)}
        data-testid="enqueue-preflight-dialog"
      >
        <DialogTitle>
          {previewWouldAdd > 0
            ? `Add ${previewWouldAdd} leads to batch?`
            : 'Nothing to add'}
        </DialogTitle>
        <DialogContent>
          {preview && (
            <DialogContentText component="div">
              <Typography variant="body2" sx={{ mb: 1 }}>
                {formatEnqueuePreview(preview)}
              </Typography>
              {preview.would_add > batchMinimum && (
                <Typography variant="body2" color="text.secondary">
                  This is more than your batch minimum of {batchMinimum}. You can review
                  addresses in the staged list before sending.
                </Typography>
              )}
              {preview.would_fail > 0 && (
                <Typography variant="body2" color="warning.main" sx={{ mt: 1 }}>
                  {preview.would_fail} lead{preview.would_fail === 1 ? '' : 's'} will be
                  skipped due to incomplete addresses.
                </Typography>
              )}
            </DialogContentText>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmAdd(null)}>Cancel</Button>
          {previewWouldAdd > 0 && (
            <Button
              variant="contained"
              onClick={() => void runEnqueueCandidates(confirmAdd?.limit)}
              disabled={isEnqueueing}
              data-testid="enqueue-preflight-confirm"
            >
              Add to batch
            </Button>
          )}
        </DialogActions>
      </Dialog>

      <AppSnackbar
        open={snackbarMessage !== null}
        onClose={() => setSnackbarMessage(null)}
        message={snackbarMessage ?? ''}
        severity={snackbarSeverity}
        autoHideDuration={
          snackbarSeverity === 'error'
            ? null
            : snackbarSeverity === 'warning'
              ? 8000
              : undefined
        }
        data-testid="enqueue-feedback-snackbar"
      />
    </Box>
  )
}

export default ReadyToMailQueue
