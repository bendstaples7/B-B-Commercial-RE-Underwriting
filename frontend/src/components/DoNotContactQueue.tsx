/**
 * DoNotContactQueue — Do Not Contact queue view.
 *
 * Shows leads marked as Do Not Contact. Extra columns: DNC date (proxy:
 * last_contact_date) and actor (proxy: review_reason).
 * Row actions: Reactivate.
 *
 * Requirements: 6.8, 18.1
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Typography } from '@mui/material'
import RestoreIcon from '@mui/icons-material/Restore'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { QueueLoadingState } from './QueueLoadingState'
import { queueService, commandCenterService } from '@/services/api'
import type { QueueRow } from '@/types'
import { resolveBulkActions } from './queueBulkActions'
import { useQueueSelection } from '@/hooks/useQueueSelection'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { queueListQueryDefaults, queuePlaceholderTableSx } from '@/utils/queueQueryDefaults'

export function DoNotContactQueue() {
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const { data, isLoading, isPlaceholderData } = useQuery({
    queryKey: ['queue-do-not-contact', page],
    queryFn: () => queueService.getDoNotContact(page, 20),
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
      key: 'dnc_date',
      label: 'DNC Date',
      render: (row: QueueRow) =>
        row.last_contact_date
          ? new Date(row.last_contact_date).toLocaleDateString()
          : '—',
    },
    {
      key: 'dnc_actor',
      label: 'Actor',
      render: (row: QueueRow) => row.review_reason ?? '—',
    },
  ]

  const fromQueue = { key: 'do-not-contact', label: 'Do Not Contact' }

  const bulkCtx = {
    queryClient,
    queryKey: 'queue-do-not-contact',
    onAfterAction: () => {
      clearSelection()
      setPage(1)
    },
  }

  const rowActions: RowAction[] = [
    {
      label: 'Reactivate',
      icon: <RestoreIcon fontSize="small" />,
      testId: 'action-reactivate',
      onClick: async (row: QueueRow) => {
        await commandCenterService.reactivate(row.id)
        queryClient.invalidateQueries({ queryKey: ['queue-do-not-contact'] })
        clearSelection()
        setPage(1)
      },
    },
  ]

  const bulkActions = resolveBulkActions(['reactivate'], bulkCtx)

  return (
    <Box data-testid="do-not-contact-queue">
      <Typography variant="h6" gutterBottom>
        Do Not Contact
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

export default DoNotContactQueue
