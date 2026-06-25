/**
 * TodaysActionQueue — Today's Action queue view.
 *
 * Fetches leads that need action today: follow_up_now recommended action or
 * open tasks due today. Shows summary header with overdue and follow-up counts.
 *
 * Requirements: 6.3, 18.1
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Link, Typography } from '@mui/material'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction } from './QueueTable'
import { queueService } from '@/services/api'
import {
  createCreateTaskRowAction,
  createLogCallRowAction,
  createLogNoteRowAction,
} from './queueRowActions'
import { computeTotalPages, clampPage } from '@/utils/pagination'

export interface TodaysActionQueueProps {
  extraQueryKeys?: string[]
}

export function TodaysActionQueue({ extraQueryKeys }: TodaysActionQueueProps = {}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)

  const { data } = useQuery({
    queryKey: ['queue-todays-action', page],
    queryFn: () => queueService.getTodaysAction(page, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const handlePageChange = (newPage: number) => {
    setPage(clampPage(newPage, totalPages))
  }

  const overdueCount = rows.filter((r) => r.follow_up_overdue).length
  const followUpNowCount = rows.filter((r) => r.recommended_action === 'follow_up_now').length

  const navigateOptions = { navigate }
  const taskOptions = {
    queryClient,
    queryKey: 'queue-todays-action',
    extraQueryKeys,
    onAfterAction: () => setPage(1),
  }

  const rowActions: RowAction[] = [
    createLogCallRowAction(navigateOptions),
    createLogNoteRowAction(navigateOptions),
    createCreateTaskRowAction(taskOptions),
  ]

  return (
    <Box data-testid="todays-action-queue">
      <Typography variant="h6" gutterBottom>
        Today's Action
      </Typography>

      <Box sx={{ display: 'flex', gap: 3, mb: 2 }}>
        <Typography variant="body2" color="text.secondary">
          Total: <strong>{total}</strong>
        </Typography>
        <Typography variant="body2" color="error.main">
          Overdue: <strong>{overdueCount}</strong>
        </Typography>
        <Typography variant="body2" color="warning.main">
          Follow Up Now: <strong>{followUpNowCount}</strong>
        </Typography>
      </Box>

      {rows.length === 0 && total === 0 ? (
        <Box sx={{ py: 4, textAlign: 'center' }} data-testid="todays-action-empty">
          <Typography variant="body1" color="text.secondary" gutterBottom>
            You're all caught up!
          </Typography>
          <Link component={RouterLink} to="/queues/no-next-action" variant="body2">
            View leads with no next action →
          </Link>
        </Box>
      ) : (
        <QueueTable
          rows={rows}
          total={total}
          rowActions={rowActions}
          {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
        />
      )}
    </Box>
  )
}

export default TodaysActionQueue
