/**
 * SkipTraceQueue — active Skip Trace work (lead_status = skip_trace).
 *
 * Same composition as NeedsReviewQueue / DoNotContactQueue (useQuery +
 * QueueTable). QueuePage in types is the API response shape, not a React page.
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

export function SkipTraceQueue() {
  const [page, setPage] = useState(1)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const { data, isLoading, isPlaceholderData } = useQuery({
    queryKey: ['queue-skip-trace', page],
    queryFn: () => queueService.getSkipTrace(page, 20),
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
      key: 'skip_trace_next_source_id',
      label: 'Assigned source',
      render: (row: QueueRow) => row.skip_trace_next_source_id ?? row.skip_tracer ?? '—',
    },
    {
      key: 'skip_tracer',
      label: 'Last source',
      render: (row: QueueRow) => row.skip_tracer ?? '—',
    },
  ]

  const fromQueue = { key: 'skip-trace', label: 'Skip Trace' }

  const bulkCtx = {
    queryClient,
    queryKey: 'queue-skip-trace',
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
      data-testid="skip-trace-queue"
      sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}
    >
      <Typography variant="h6" gutterBottom>
        Skip Trace
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Active skip-trace work (same leads as the Kanban Skip Trace column). Total:{' '}
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

export default SkipTraceQueue
