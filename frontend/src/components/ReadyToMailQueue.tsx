/**
 * ReadyToMailQueue — operational home for direct mail batching.
 */
import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailBatchSummary } from './MailBatchSummary'
import { MailQueueStagedTable } from './MailQueueStagedTable'
import { MailCampaignsPanel } from './MailCampaignsPanel'
import { QueueTable } from './QueueTable'
import type { BulkAction, RowAction, ExtraColumn } from './QueueTable'
import { queueService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { formatLastMailedDate, formatLastSaleDate } from '@/utils/formatLastMailedDate'
import type { QueueRow } from '@/types'
import PostAddIcon from '@mui/icons-material/PostAdd'

export function ReadyToMailQueue() {
  const queryClient = useQueryClient()
  const [candidatesPage, setCandidatesPage] = useState(1)
  const [selectedIds, setSelectedIds] = useState<number[]>([])

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

  const enqueueMutation = useMutation({
    mutationFn: (leadIds: number[]) => openLetterService.enqueue(leadIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
      queryClient.invalidateQueries({ queryKey: ['queue-mail-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
      setSelectedIds([])
      setCandidatesPage(1)
    },
  })

  const candidateRows = candidatesData?.rows ?? []
  const candidateTotal = candidatesData?.total ?? 0
  const candidateTotalPages = computeTotalPages(candidateTotal, candidatesData?.per_page ?? 20)
  const handleCandidatesPageChange = (newPage: number) => {
    setCandidatesPage(clampPage(newPage, candidateTotalPages))
    setSelectedIds([])
  }

  const handleAddToBatch = async (leadIds: number[]) => {
    const result = await enqueueMutation.mutateAsync(leadIds)
    return {
      successes: result.added,
      failures: result.skipped + result.invalid,
    }
  }

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

      <Typography variant="h6" sx={{ mb: 1 }}>
        Staged for next batch
      </Typography>
      {queueError ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Staged leads are unavailable until the mail queue loads.
        </Typography>
      ) : (
        <MailQueueStagedTable items={queueData?.items ?? []} />
      )}

      <Divider sx={{ my: 3 }} />

      <Typography variant="h6" gutterBottom>
        Recommended for mail
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Leads scored as mail-ready that are not yet in your batch ({candidateTotal} total).
      </Typography>

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

      <Typography variant="h6" sx={{ mb: 2 }}>
        Recent sends
      </Typography>
      <MailCampaignsPanel embedded />
    </Box>
  )
}

export default ReadyToMailQueue
