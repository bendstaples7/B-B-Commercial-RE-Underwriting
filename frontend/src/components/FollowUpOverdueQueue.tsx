/**
 * FollowUpOverdueQueue — Follow-Up Overdue queue view.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Chip, Typography } from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { QueueLoadingState } from './QueueLoadingState'
import { queueService } from '@/services/api'
import type { QueueRow } from '@/types'
import {
  createCreateTaskRowAction,
  createLogCallRowAction,
  createLogNoteRowAction,
} from './queueRowActions'
import {
  createAddToMailBatchRowAction,
  resolveBulkActions,
} from './queueBulkActions'
import { useQueueSelection } from '@/hooks/useQueueSelection'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { queueListQueryDefaults, queuePlaceholderTableSx } from '@/utils/queueQueryDefaults'

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
  const queryClient = useQueryClient()
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const { data, isLoading, isPlaceholderData } = useQuery({
    queryKey: ['queue-follow-up-overdue', page],
    queryFn: () => queueService.getFollowUpOverdue(page, 20),
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

  const fromQueue = { key: 'follow-up-overdue', label: 'Follow-Up Overdue' }
  const navigateOptions = { navigate, fromQueue }
  const bulkCtx = {
    queryClient,
    queryKey: 'queue-follow-up-overdue',
    onAfterAction: () => {
      clearSelection()
      setPage(1)
    },
  }

  const rowActions: RowAction[] = [
    createAddToMailBatchRowAction(bulkCtx),
    createLogCallRowAction(navigateOptions),
    createLogNoteRowAction(navigateOptions),
    createCreateTaskRowAction({
      queryClient,
      queryKey: 'queue-follow-up-overdue',
      onAfterAction: () => {
        clearSelection()
        setPage(1)
      },
    }),
  ]

  const bulkActions = resolveBulkActions(['add_to_mail_batch', 'create_task'], bulkCtx)

  return (
    <Box data-testid="follow-up-overdue-queue" sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Typography variant="h6" gutterBottom>
        Follow-Up Overdue
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

export default FollowUpOverdueQueue
