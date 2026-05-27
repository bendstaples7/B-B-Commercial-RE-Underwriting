/**
 * TodaysActionQueue — Today's Action queue view.
 *
 * Fetches leads that need action today: follow_up_now recommended action or
 * open tasks due today. Shows summary header with overdue and follow-up counts.
 *
 * Requirements: 6.3, 18.1
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Link, Typography } from '@mui/material'
import PhoneIcon from '@mui/icons-material/Phone'
import NoteIcon from '@mui/icons-material/Note'
import AddTaskIcon from '@mui/icons-material/AddTask'
import { Link as RouterLink } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction } from './QueueTable'
import {
  queueService,
  callLogService,
  leadTaskService,
} from '@/services/api'
import type { QueueRow } from '@/types'

export function TodaysActionQueue() {
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ['queue-todays-action'],
    queryFn: () => queueService.getTodaysAction(1, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0

  const overdueCount = rows.filter((r) => r.follow_up_overdue).length
  const followUpNowCount = rows.filter((r) => r.recommended_action === 'follow_up_now').length

  const rowActions: RowAction[] = [
    {
      label: 'Log Call',
      icon: <PhoneIcon fontSize="small" />,
      testId: 'action-log-call',
      onClick: async (row: QueueRow) => {
        await callLogService.logCall(row.id, { outcome: 'answered' })
        queryClient.invalidateQueries({ queryKey: ['queue-todays-action'] })
      },
    },
    {
      label: 'Log Note',
      icon: <NoteIcon fontSize="small" />,
      testId: 'action-log-note',
      onClick: async (row: QueueRow) => {
        await callLogService.logNote(row.id, { body: '' })
        queryClient.invalidateQueries({ queryKey: ['queue-todays-action'] })
      },
    },
    {
      label: 'Create Task',
      icon: <AddTaskIcon fontSize="small" />,
      testId: 'action-create-task',
      onClick: async (row: QueueRow) => {
        await leadTaskService.createTask(row.id, { title: 'Follow up', task_type: 'call_owner_today' })
        queryClient.invalidateQueries({ queryKey: ['queue-todays-action'] })
      },
    },
  ]

  return (
    <Box data-testid="todays-action-queue">
      <Typography variant="h6" gutterBottom>
        Today's Action
      </Typography>

      {/* Summary header */}
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

      {/* Empty state */}
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
        />
      )}
    </Box>
  )
}

export default TodaysActionQueue
