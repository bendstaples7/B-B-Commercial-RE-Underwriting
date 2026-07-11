/**
 * NeedsReviewQueue — Needs Review queue view.
 *
 * Shows leads flagged for review. Extra columns: review reason and trigger date.
 * Row actions: context-specific "View Analysis" or "View Activity" button.
 *
 * Requirements: 6.7, 18.1
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Typography } from '@mui/material'
import AnalyticsIcon from '@mui/icons-material/Analytics'
import HistoryIcon from '@mui/icons-material/History'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { queueService } from '@/services/api'
import type { QueueRow } from '@/types'
import { resolveBulkActions } from './queueBulkActions'
import { useQueueSelection } from '@/hooks/useQueueSelection'
import { computeTotalPages, clampPage } from '@/utils/pagination'

export function NeedsReviewQueue() {
  const [page, setPage] = useState(1)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const { data } = useQuery({
    queryKey: ['queue-needs-review', page],
    queryFn: () => queueService.getNeedsReview(page, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const handlePageChange = onPageChangeWithClear((newPage) => {
    setPage(clampPage(newPage, totalPages))
  })

  const extraColumns: ExtraColumn[] = [
    {
      key: 'review_reason',
      label: 'Review Reason',
      render: (row: QueueRow) => row.review_reason ?? '—',
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

  const rowActions: RowAction[] = [
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
    <Box data-testid="needs-review-queue">
      <Typography variant="h6" gutterBottom>
        Needs Review
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Total: <strong>{total}</strong>
      </Typography>

      <QueueTable
        rows={rows}
        total={total}
        fromQueue={fromQueue}
        selectedIds={selectedIds}
        onSelectionChange={onSelectionChange}
        rowActions={rowActions}
        bulkActions={bulkActions}
        extraColumns={extraColumns}
        {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
      />
    </Box>
  )
}

export default NeedsReviewQueue
