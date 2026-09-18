import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Typography } from '@mui/material'
import AnalyticsIcon from '@mui/icons-material/Analytics'
import HistoryIcon from '@mui/icons-material/History'
import MergeTypeIcon from '@mui/icons-material/MergeType'
import CloseIcon from '@mui/icons-material/Close'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { QueueLoadingState } from './QueueLoadingState'
import { commandCenterService, queueService } from '@/services/api'
import type { QueueRow } from '@/types'
import { resolveBulkActions } from './queueBulkActions'
import { useQueueSelection } from '@/hooks/useQueueSelection'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { queueListQueryDefaults, queuePlaceholderTableSx } from '@/utils/queueQueryDefaults'
import { formatNeedsReviewReason } from '@/utils/needsReviewReason'
import { formatDate } from '@/utils/formatters'

export function NeedsReviewQueue() {
  const [page, setPage] = useState(1)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const { data, isLoading, isPlaceholderData } = useQuery({
    queryKey: ['queue-needs-review', page],
    queryFn: () => queueService.getNeedsReview(page, 20),
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
      key: 'review_reason',
      label: 'Review Reason',
      render: (row: QueueRow) => {
        if (!row.review_reason) return '—'
        return formatNeedsReviewReason(row)
      },
    },
    {
      key: 'review_triggered_at',
      label: 'Triggered',
      render: (row: QueueRow) => formatDate(row.review_triggered_at),
    },
  ]

  const fromQueue = { key: 'needs-review', label: 'Needs Review' }

  const bulkCtx = {
    queryClient,
    queryKey: 'queue-needs-review',
    onAfterAction: () => {
      clearSelection()
      setPage(1)
    },
  }

  const refreshQueue = () => {
    void queryClient.invalidateQueries({ queryKey: ['queue-needs-review'] })
  }

  const rowActions: RowAction[] = [
    {
      label: 'Keep suggested',
      icon: <MergeTypeIcon fontSize="small" />,
      testId: 'action-merge-duplicate',
      isVisible: (row: QueueRow) => (
        row.review_reason === 'duplicate_lead_cluster'
        && Boolean(row.suggested_winner_id)
        && row.suggested_winner_id !== row.id
        && String(row.duplicate_confidence || '').toLowerCase() !== 'ambiguous'
      ),
      onClick: async (row: QueueRow) => {
        const winnerId = row.suggested_winner_id
        if (!winnerId) return
        const ok = window.confirm(
          `Merge lead #${row.id} into #${winnerId}? This soft-merges the duplicate and cannot be undone from this screen.`,
        )
        if (!ok) return
        await commandCenterService.mergeInto(row.id, winnerId)
        refreshQueue()
        navigate(`/leads/${winnerId}`)
      },
    },
    {
      label: 'Not a duplicate',
      icon: <CloseIcon fontSize="small" />,
      testId: 'action-dismiss-duplicate',
      isVisible: (row: QueueRow) => row.review_reason === 'duplicate_lead_cluster',
      onClick: async (row: QueueRow) => {
        await commandCenterService.dismissDuplicateReview(row.id)
        refreshQueue()
      },
    },
    {
      label: 'View Analysis',
      icon: <AnalyticsIcon fontSize="small" />,
      testId: 'action-view-analysis',
      onClick: async (row: QueueRow) => {
        navigate(`/leads/${row.id}?tab=analysis`)
      },
    },
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
    <Box data-testid="needs-review-queue" sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Typography variant="h6" gutterBottom>
        Needs Review
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Total: <strong>{data != null && !isPlaceholderData ? total : '—'}</strong>
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

export default NeedsReviewQueue
