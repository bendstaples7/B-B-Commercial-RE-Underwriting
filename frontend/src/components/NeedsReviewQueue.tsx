/**
 * NeedsReviewQueue — Needs Review queue view.
 *
 * Shows leads flagged for review. Extra columns: review reason and trigger date.
 * Soft-merge for ``duplicate_lead_cluster``: Merge into suggested winner / Dismiss.
 *
 * Requirements: 6.7, 18.1
 */
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
        if (row.review_reason === 'duplicate_lead_cluster') {
          const twin = row.suggested_winner_id
          const ids = (row.duplicate_cluster_ids ?? []).filter((id) => id !== row.id)
          return twin
            ? `Duplicate cluster → #${twin}${ids.length ? ` (+${ids.length})` : ''}`
            : 'Duplicate cluster'
        }
        return row.review_reason ?? '—'
      },
    },
    {
      key: 'review_triggered_at',
      label: 'Triggered',
      render: (row: QueueRow) =>
        row.review_triggered_at
          ? new Date(row.review_triggered_at).toLocaleDateString()
          : '—',
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
      label: 'Merge into winner',
      icon: <MergeTypeIcon fontSize="small" />,
      testId: 'action-merge-duplicate',
      isVisible: (row: QueueRow) => (
        row.review_reason === 'duplicate_lead_cluster'
        && Boolean(row.suggested_winner_id)
        && row.suggested_winner_id !== row.id
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
      label: 'Dismiss duplicate',
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
