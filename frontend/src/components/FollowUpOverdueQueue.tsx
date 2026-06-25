/**
 * FollowUpOverdueQueue — Follow-Up Overdue queue view.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Box, Chip, Typography } from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { queueService } from '@/services/api'
import type { QueueRow } from '@/types'
import { createLogCallRowAction, createLogNoteRowAction } from './queueRowActions'
import { computeTotalPages, clampPage } from '@/utils/pagination'

function computeDaysOverdue(lastContactDate: string | null): number | null {
  if (!lastContactDate) return null
  const last = new Date(lastContactDate)
  const now = new Date()
  const diffMs = now.getTime() - last.getTime()
  return Math.floor(diffMs / (1000 * 60 * 60 * 24))
}

export function FollowUpOverdueQueue() {
  const [page, setPage] = useState(1)
  const navigate = useNavigate()

  const { data } = useQuery({
    queryKey: ['queue-follow-up-overdue', page],
    queryFn: () => queueService.getFollowUpOverdue(page, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const handlePageChange = (newPage: number) => {
    setPage(clampPage(newPage, totalPages))
  }

  const extraColumns: ExtraColumn[] = [
    {
      key: 'days_overdue',
      label: 'Days Overdue',
      render: (row: QueueRow) => {
        const days = computeDaysOverdue(row.last_contact_date)
        if (days === null) return '—'
        return (
          <Chip
            label={`${days}d`}
            size="small"
            color={days > 14 ? 'error' : days > 7 ? 'warning' : 'default'}
          />
        )
      },
    },
    {
      key: 'follow_up_overdue',
      label: 'Overdue Flag',
      render: (row: QueueRow) =>
        row.follow_up_overdue ? (
          <Chip label="Overdue" size="small" color="error" />
        ) : (
          '—'
        ),
    },
  ]

  const rowActions: RowAction[] = [
    createLogCallRowAction({ navigate }),
    createLogNoteRowAction({ navigate }),
  ]

  return (
    <Box data-testid="follow-up-overdue-queue">
      <Typography variant="h6" gutterBottom>
        Follow-Up Overdue
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Total: <strong>{total}</strong>
      </Typography>

      <QueueTable
        rows={rows}
        total={total}
        rowActions={rowActions}
        extraColumns={extraColumns}
        {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
      />
    </Box>
  )
}

export default FollowUpOverdueQueue
