/**
 * PreviouslyWarmQueue — Previously Warm queue view.
 *
 * Shows leads that had HubSpot engagement but no recent platform contact.
 * Extra columns: last HubSpot activity type (hubspot_deal_stage) and last sync date.
 * Row actions: Log Call, Log Note, Create Task, Suppress (with confirmation).
 *
 * Requirements: 6.4, 18.1
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Typography,
} from '@mui/material'
import PhoneIcon from '@mui/icons-material/Phone'
import NoteIcon from '@mui/icons-material/Note'
import AddTaskIcon from '@mui/icons-material/AddTask'
import BlockIcon from '@mui/icons-material/Block'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import {
  queueService,
  callLogService,
  leadTaskService,
  commandCenterService,
} from '@/services/api'
import type { QueueRow } from '@/types'

export function PreviouslyWarmQueue() {
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()
  const [suppressTarget, setSuppressTarget] = useState<QueueRow | null>(null)

  const { data } = useQuery({
    queryKey: ['queue-previously-warm', page],
    queryFn: () => queueService.getPreviouslyWarm(page, 20),
    refetchInterval: 60_000,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0

  const handleSuppressConfirm = async () => {
    if (!suppressTarget) return
    await commandCenterService.suppress(suppressTarget.id)
    queryClient.invalidateQueries({ queryKey: ['queue-previously-warm'] })
    setSuppressTarget(null)
  }

  const extraColumns: ExtraColumn[] = [
    {
      key: 'hubspot_deal_stage',
      label: 'Last HubSpot Activity',
      render: (row: QueueRow) => row.hubspot_deal_stage ?? '—',
    },
    {
      key: 'last_hubspot_sync_at',
      label: 'Last Sync',
      render: (row: QueueRow) =>
        row.last_hubspot_sync_at
          ? new Date(row.last_hubspot_sync_at).toLocaleDateString()
          : '—',
    },
  ]

  const rowActions: RowAction[] = [
    {
      label: 'Log Call',
      icon: <PhoneIcon fontSize="small" />,
      testId: 'action-log-call',
      onClick: async (row: QueueRow) => {
        await callLogService.logCall(row.id, { outcome: 'answered' })
        queryClient.invalidateQueries({ queryKey: ['queue-previously-warm'] })
      },
    },
    {
      label: 'Log Note',
      icon: <NoteIcon fontSize="small" />,
      testId: 'action-log-note',
      onClick: async (row: QueueRow) => {
        const body = window.prompt('Enter note:')
        if (!body || !body.trim()) return
        await callLogService.logNote(row.id, { body: body.trim() })
        queryClient.invalidateQueries({ queryKey: ['queue-previously-warm'] })
      },
    },
    {
      label: 'Create Task',
      icon: <AddTaskIcon fontSize="small" />,
      testId: 'action-create-task',
      onClick: async (row: QueueRow) => {
        await leadTaskService.createTask(row.id, { title: 'Follow up', task_type: 'call_owner_today' })
        queryClient.invalidateQueries({ queryKey: ['queue-previously-warm'] })
      },
    },
    {
      label: 'Suppress',
      icon: <BlockIcon fontSize="small" />,
      testId: 'action-suppress',
      onClick: async (row: QueueRow) => {
        setSuppressTarget(row)
      },
    },
  ]

  return (
    <Box data-testid="previously-warm-queue">
      <Typography variant="h6" gutterBottom>
        Previously Warm
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

      {/* Suppress confirmation dialog */}
      <Dialog
        open={suppressTarget !== null}
        onClose={() => setSuppressTarget(null)}
        data-testid="suppress-confirm-dialog"
      >
        <DialogTitle>Suppress Lead?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will suppress the lead and remove it from active queues. Are you sure?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSuppressTarget(null)}>Cancel</Button>
          <Button
            onClick={handleSuppressConfirm}
            color="error"
            variant="contained"
            data-testid="suppress-confirm-btn"
          >
            Suppress
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default PreviouslyWarmQueue
