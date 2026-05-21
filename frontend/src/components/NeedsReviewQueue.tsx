/**
 * NeedsReviewQueue — Needs Review queue view.
 *
 * Shows leads flagged for review. Extra columns: review reason and trigger date.
 * Row actions: context-specific "View Analysis" or "View Activity" button.
 *
 * Requirements: 6.7, 18.1
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Box, Button, Typography } from '@mui/material'
import AnalyticsIcon from '@mui/icons-material/Analytics'
import HistoryIcon from '@mui/icons-material/History'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { queueService } from '@/services/api'
import type { QueueRow } from '@/types'

export function NeedsReviewQueue() {
  const [page] = useState(1)
  const navigate = useNavigate()

  const { data } = useQuery({
    queryKey: ['queue-needs-review', page],
    queryFn: () => queueService.getNeedsReview(page, 20),
    refetchInterval: 60_000,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0

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

  const rowActions: RowAction[] = [
    {
      label: 'View Analysis',
      icon: <AnalyticsIcon fontSize="small" />,
      testId: 'action-view-analysis',
      onClick: async (row: QueueRow) => {
        // Navigate to command center — analysis tab
        navigate(`/leads/${row.id}/command-center?tab=analysis`)
      },
    },
    {
      label: 'View Activity',
      icon: <HistoryIcon fontSize="small" />,
      testId: 'action-view-activity',
      onClick: async (row: QueueRow) => {
        // Navigate to command center — timeline tab
        navigate(`/leads/${row.id}/command-center?tab=timeline`)
      },
    },
  ]

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
        rowActions={rowActions}
        extraColumns={extraColumns}
      />
    </Box>
  )
}

export default NeedsReviewQueue
