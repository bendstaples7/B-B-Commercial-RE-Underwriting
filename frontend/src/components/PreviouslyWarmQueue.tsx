/**
 * PreviouslyWarmQueue — Previously Warm queue view.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Typography } from '@mui/material'
import BlockIcon from '@mui/icons-material/Block'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { queueService, commandCenterService } from '@/services/api'
import { computeTotalPages, clampPage } from '@/utils/pagination'
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
import { SuppressLeadDialog } from './SuppressLeadDialog'

export function PreviouslyWarmQueue() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [suppressTarget, setSuppressTarget] = useState<QueueRow | null>(null)
  const [page, setPage] = useState(1)
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const { data } = useQuery({
    queryKey: ['queue-previously-warm', page],
    queryFn: () => queueService.getPreviouslyWarm(page, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const handlePageChange = onPageChangeWithClear((newPage) => {
    setPage(clampPage(newPage, totalPages))
  })

  const handleSuppressConfirm = async () => {
    if (!suppressTarget) return
    await commandCenterService.suppress(suppressTarget.id)
    queryClient.invalidateQueries({ queryKey: ['queue-previously-warm'] })
    clearSelection()
    setPage(1)
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

  const fromQueue = { key: 'previously-warm', label: 'Previously Warm' }
  const navigateOptions = { navigate, fromQueue }
  const bulkCtx = {
    queryClient,
    queryKey: 'queue-previously-warm',
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
      queryKey: 'queue-previously-warm',
      onAfterAction: () => {
        clearSelection()
        setPage(1)
      },
    }),
    {
      label: 'Suppress',
      icon: <BlockIcon fontSize="small" />,
      testId: 'action-suppress',
      onClick: async (row: QueueRow) => {
        setSuppressTarget(row)
      },
    },
  ]

  const bulkActions = resolveBulkActions(
    ['add_to_mail_batch', 'create_task', 'suppress'],
    bulkCtx,
  )

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
        fromQueue={fromQueue}
        selectedIds={selectedIds}
        onSelectionChange={onSelectionChange}
        rowActions={rowActions}
        bulkActions={bulkActions}
        extraColumns={extraColumns}
        {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
      />

      <SuppressLeadDialog
        open={suppressTarget !== null}
        onClose={() => setSuppressTarget(null)}
        onConfirm={handleSuppressConfirm}
      />
    </Box>
  )
}

export default PreviouslyWarmQueue
