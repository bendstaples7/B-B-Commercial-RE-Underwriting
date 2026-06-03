/**
 * NoNextActionQueue — No Next Action queue view.
 *
 * Shows leads with no recommended action and no open tasks.
 * Extra columns: days since last activity (computed from last_contact_date).
 * Row actions: Log Note, Suppress (with confirmation).
 *
 * Requirements: 6.6, 18.1
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Typography,
} from '@mui/material'
import NoteIcon from '@mui/icons-material/Note'
import BlockIcon from '@mui/icons-material/Block'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { queueService, callLogService, commandCenterService } from '@/services/api'
import type { QueueRow } from '@/types'
import { computeTotalPages, clampPage } from '@/utils/pagination'

function computeDaysSinceActivity(lastContactDate: string | null): number | null {
  if (!lastContactDate) return null
  const last = new Date(lastContactDate)
  const now = new Date()
  const diffMs = now.getTime() - last.getTime()
  return Math.floor(diffMs / (1000 * 60 * 60 * 24))
}

export function NoNextActionQueue() {
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()
  const [suppressTarget, setSuppressTarget] = useState<QueueRow | null>(null)

  const { data } = useQuery({
    queryKey: ['queue-no-next-action', page],
    queryFn: () => queueService.getNoNextAction(page, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const handlePageChange = (newPage: number) => {
    setPage(clampPage(newPage, totalPages))
  }

  const handleSuppressConfirm = async () => {
    if (!suppressTarget) return
    try {
      await commandCenterService.suppress(suppressTarget.id)
      queryClient.invalidateQueries({ queryKey: ['queue-no-next-action'] })
      setPage(1)
    } catch {
      // Suppress failed — page remains unchanged, dialog still closes
    } finally {
      setSuppressTarget(null)
    }
  }

  const extraColumns: ExtraColumn[] = [
    {
      key: 'days_since_activity',
      label: 'Days Since Activity',
      render: (row: QueueRow) => {
        const days = computeDaysSinceActivity(row.last_contact_date)
        if (days === null) return <Chip label="Never" size="small" color="default" />
        return (
          <Chip
            label={`${days}d`}
            size="small"
            color={days > 90 ? 'error' : days > 30 ? 'warning' : 'default'}
          />
        )
      },
    },
  ]

  const rowActions: RowAction[] = [
    {
      label: 'Log Note',
      icon: <NoteIcon fontSize="small" />,
      testId: 'action-log-note',
      onClick: async (row: QueueRow) => {
        const body = window.prompt('Enter note:')
        if (!body || !body.trim()) return
        await callLogService.logNote(row.id, { body: body.trim() })
        queryClient.invalidateQueries({ queryKey: ['queue-no-next-action'] })
        setPage(1)
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
    <Box data-testid="no-next-action-queue">
      <Typography variant="h6" gutterBottom>
        No Next Action
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

export default NoNextActionQueue
