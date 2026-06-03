/**
 * MissingPropertyMatchQueue — Missing Property Match queue view.
 *
 * Shows leads with no property match. Extra columns: address as entered
 * (property_street). Row actions: Research PIN (creates research_missing_pin
 * task), Suppress (with confirmation).
 *
 * Requirements: 6.9, 18.1
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
import SearchIcon from '@mui/icons-material/Search'
import BlockIcon from '@mui/icons-material/Block'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import {
  queueService,
  leadTaskService,
  commandCenterService,
} from '@/services/api'
import type { QueueRow } from '@/types'
import { computeTotalPages, clampPage } from '@/utils/pagination'

export function MissingPropertyMatchQueue() {
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()
  const [suppressTarget, setSuppressTarget] = useState<QueueRow | null>(null)

  const { data } = useQuery({
    queryKey: ['queue-missing-property-match', page],
    queryFn: () => queueService.getMissingPropertyMatch(page, 20),
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
    await commandCenterService.suppress(suppressTarget.id)
    queryClient.invalidateQueries({ queryKey: ['queue-missing-property-match'] })
    setPage(1)
    setSuppressTarget(null)
  }

  const extraColumns: ExtraColumn[] = [
    {
      key: 'property_street',
      label: 'Address as Entered',
      render: (row: QueueRow) => row.property_street ?? '—',
    },
  ]

  const rowActions: RowAction[] = [
    {
      label: 'Research PIN',
      icon: <SearchIcon fontSize="small" />,
      testId: 'action-research-pin',
      onClick: async (row: QueueRow) => {
        await leadTaskService.createTask(row.id, {
          title: 'Research missing PIN',
          task_type: 'research_missing_pin',
        })
        queryClient.invalidateQueries({ queryKey: ['queue-missing-property-match'] })
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
    <Box data-testid="missing-property-match-queue">
      <Typography variant="h6" gutterBottom>
        Missing Property Match
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

export default MissingPropertyMatchQueue
