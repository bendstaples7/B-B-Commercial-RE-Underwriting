/**
 * ReadyToMailQueue — operational home for direct mail batching.
 */
import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Snackbar,
  Stack,
  Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailBatchSummary } from './MailBatchSummary'
import { MailQueueStagedAccordion } from './MailQueueStagedAccordion'
import { MailCampaignsPanel } from './MailCampaignsPanel'
import { QueueTable } from './QueueTable'
import type { BulkAction, RowAction, ExtraColumn } from './QueueTable'
import { queueService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { formatLastMailedDate, formatLastSaleDate } from '@/utils/formatLastMailedDate'
import {
  formatEnqueuePreview,
  formatEnqueueSummary,
  type EnqueueCounts,
} from '@/utils/formatEnqueueSummary'
import type { QueueRow } from '@/types'
import PostAddIcon from '@mui/icons-material/PostAdd'
import type { EnqueuePreviewResult } from '@/services/openLetterApi'

function invalidateMailQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
  queryClient.invalidateQueries({ queryKey: ['queue-mail-candidates'] })
  queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
}

export function ReadyToMailQueue() {
  const queryClient = useQueryClient()
  const [candidatesPage, setCandidatesPage] = useState(1)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [snackbarMessage, setSnackbarMessage] = useState<string | null>(null)
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')
  const [confirmAdd, setConfirmAdd] = useState<{
    limit?: number
    preview: EnqueuePreviewResult
  } | null>(null)

  const { data: queueData, isLoading: queueLoading, error: queueError, refetch: refetchQueue, isFetching: queueFetching } = useQuery({
    queryKey: ['mail-queue'],
    queryFn: () => openLetterService.getQueue(),
    refetchInterval: 15000,
  })

  const { data: candidatesData, isLoading: candidatesLoading } = useQuery({
    queryKey: ['queue-mail-candidates', candidatesPage],
    queryFn: () => queueService.getMailCandidates(candidatesPage, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const showEnqueueFeedback = (result: EnqueueCounts) => {
    setSnackbarSeverity('success')
    setSnackbarMessage(formatEnqueueSummary(result))
  }

  const showEnqueueError = (error: unknown) => {
    setSnackbarSeverity('error')
    setSnackbarMessage(
      error instanceof Error ? error.message : 'Failed to add leads to batch. Try again.',
    )
  }

  const enqueueMutation = useMutation({
    mutationFn: (leadIds: number[]) => openLetterService.enqueue(leadIds),
    onSuccess: (result) => {
      invalidateMailQueries(queryClient)
      setSelectedIds([])
      showEnqueueFeedback(result)
    },
    onError: showEnqueueError,
  })

  const enqueueCandidatesMutation = useMutation({
    mutationFn: (limit?: number) => openLetterService.enqueueCandidates(limit),
    onSuccess: (result) => {
      invalidateMailQueries(queryClient)
      setSelectedIds([])
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
  const neededForMinimum = batchMinimum - queuedCount

  const handleCandidatesPageChange = (newPage: number) => {
    setCandidatesPage(clampPage(newPage, candidateTotalPages))
    setSelectedIds([])
  }

  const buildBulkResult = (result: EnqueueCounts) => ({
    successes: result.added,
    failures: result.skipped + result.invalid,
    message: formatEnqueueSummary(result),
  })

  const handleAddToBatch = async (leadIds: number[]) => {
    const result = await enqueueMutation.mutateAsync(leadIds)
    return buildBulkResult(result)
  }

  const runEnqueueCandidates = async (limit?: number) => {
    setConfirmAdd(null)
    await enqueueCandidatesMutation.mutateAsync(limit)
  }

  const requestEnqueueCandidates = async (limit?: number) => {
    const preview = await previewMutation.mutateAsync(limit)
    if (preview.would_add === 0) {
      setSnackbarSeverity('success')
      setSnackbarMessage(formatEnqueuePreview(preview))
      return
    }
    setConfirmAdd({ limit, preview })
  }

  const isEnqueueing =
    enqueueMutation.isPending
    || enqueueCandidatesMutation.isPending
    || previewMutation.isPending

  const rowActions: RowAction[] = [
    {
      label: 'Add to batch',
      icon: <PostAddIcon fontSize="small" />,
      testId: 'add-to-batch-row-action',
      onClick: async (row: QueueRow) => {
        await handleAddToBatch([row.id])
      },
    },
  ]

  const bulkActions: BulkAction[] = [
    {
      label: 'Add to batch',
      testId: 'add-to-batch-bulk-action',
      onClick: handleAddToBatch,
    },
  ]

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

  const showInitialLoading = queueLoading && !queueData && !queueError

  if (showInitialLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    )
  }

  const preview = confirmAdd?.preview
  const previewWouldAdd = preview?.would_add ?? 0

  return (
    <Box data-testid="ready-to-mail-queue" sx={{ p: 2 }}>
      <Typography variant="h5" component="h1" gutterBottom>
        Ready to Mail
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Stage leads for your next Open Letter batch, send when you hit your minimum, and review recent sends.
      </Typography>

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
        <MailBatchSummary title="Next batch" queueData={queueData} isLoading={queueLoading && !queueData} />
      )}

      <Divider sx={{ my: 3 }} />

      <Typography variant="h6" gutterBottom>
        Recommended for mail
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Leads scored as mail-ready that are not yet in your batch ({candidateTotal} total).
      </Typography>

      {candidateTotal > 0 && (
        <Stack direction="row" spacing={1} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
          <Button
            variant="outlined"
            size="small"
            disabled={isEnqueueing}
            onClick={() => void requestEnqueueCandidates(undefined)}
            data-testid="add-all-candidates-button"
          >
            {isEnqueueing ? 'Checking…' : `Add all ${candidateTotal} to batch`}
          </Button>
          {neededForMinimum > 0 && neededForMinimum <= candidateTotal && (
            <Button
              variant="outlined"
              size="small"
              disabled={isEnqueueing}
              onClick={() => void requestEnqueueCandidates(neededForMinimum)}
              data-testid="add-to-minimum-button"
            >
              Add {neededForMinimum} to reach minimum
            </Button>
          )}
        </Stack>
      )}

      {candidatesLoading && candidateRows.length === 0 ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <QueueTable
          rows={candidateRows}
          total={candidateTotal}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
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
      )}

      <Divider sx={{ my: 3 }} />

      {queueError ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Staged leads are unavailable until the mail queue loads.
        </Typography>
      ) : (
        <MailQueueStagedAccordion items={queueData?.items ?? []} />
      )}

      <Divider sx={{ my: 3 }} />

      <Typography variant="h6" sx={{ mb: 2 }}>
        Recent sends
      </Typography>
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

      <Snackbar
        open={snackbarMessage !== null}
        autoHideDuration={8000}
        onClose={() => setSnackbarMessage(null)}
        data-testid="enqueue-feedback-snackbar"
      >
        <Alert
          onClose={() => setSnackbarMessage(null)}
          severity={snackbarSeverity}
          sx={{ width: '100%' }}
        >
          {snackbarMessage ?? ''}
        </Alert>
      </Snackbar>
    </Box>
  )
}

export default ReadyToMailQueue
