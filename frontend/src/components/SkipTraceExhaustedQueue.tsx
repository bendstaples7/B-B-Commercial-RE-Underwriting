/**
 * SkipTraceExhaustedQueue — leads where every connected skip-trace source
 * has been tried after undeliverable mail. Investigate new vendors when this grows.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Typography } from '@mui/material'
import HistoryIcon from '@mui/icons-material/History'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { QueueLoadingState } from './QueueLoadingState'
import { queueService } from '@/services/api'
import type { QueueRow } from '@/types'
import { resolveBulkActions } from './queueBulkActions'
import { useQueueSelection } from '@/hooks/useQueueSelection'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { queueListQueryDefaults, queuePlaceholderTableSx } from '@/utils/queueQueryDefaults'

export function SkipTraceExhaustedQueue() {
  const [page, setPage] = useState(1)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const { data, isLoading, isPlaceholderData } = useQuery({
    queryKey: ['queue-skip-trace-exhausted', page],
    queryFn: () => queueService.getSkipTraceExhausted(page, 20),
    ...queueListQueryDefaults,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const isInitialLoading = isLoading && !data
  const showRefetchIndicator = isPlaceholderData
  const handlePageChange = onPageChangeWithClear((newPage) => {
    setPage(clampPage(newPage, totalPages))
  })

  const extraColumns: ExtraColumn[] = [
    {
      key: 'skip_tracer',
      label: 'Last source',
      render: (row: QueueRow) => row.skip_tracer ?? '—',
    },
    {
      key: 'skip_trace_exhausted_at',
      label: 'Exhausted',
      render: (row: QueueRow) =>
        row.skip_trace_exhausted_at
          ? new Date(row.skip_trace_exhausted_at).toLocaleDateString()
          : '—',
    },
  ]

  const fromQueue = { key: 'skip-trace-exhausted', label: 'Skip Trace Exhausted' }

  const bulkCtx = {
    queryClient,
    queryKey: 'queue-skip-trace-exhausted',
    onAfterAction: () => {
      clearSelection()
      setPage(1)
    },
  }

  const rowActions: RowAction[] = [
    {
      label: 'View Activity',
      icon: <HistoryIcon fontSize="small" />,
      testId: 'action-view-activity',
      onClick: async (row: QueueRow) => {
        navigate(`/leads/${row.id}?tab=timeline`)
      },
    },
  ]

  const bulkActions = resolveBulkActions(['create_task'], bulkCtx)

  return (
    <Box
      data-testid="skip-trace-exhausted-queue"
      sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
    >
      <Typography variant="h6" gutterBottom>
        Skip Trace Exhausted
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Every connected skip-trace source has been tried after undeliverable mail.
        Use this list when evaluating additional skip-trace vendors. Total:{' '}
        <strong>{data != null && !isPlaceholderData ? total : '—'}</strong>
      </Typography>
      {isInitialLoading ? (
        <QueueLoadingState />
      ) : (
        <Box sx={queuePlaceholderTableSx(showRefetchIndicator)}>
          <QueueTable
            rows={rows}
            total={total}
            disabled={showRefetchIndicator}
            isPlaceholderData={showRefetchIndicator}
            fromQueue={fromQueue}
            selectedIds={selectedIds}
            onSelectionChange={onSelectionChange}
            rowActions={rowActions}
            bulkActions={bulkActions}
            extraColumns={extraColumns}
            {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
          />
        </Box>
      )}
    </Box>
  )
}

export default SkipTraceExhaustedQueue
