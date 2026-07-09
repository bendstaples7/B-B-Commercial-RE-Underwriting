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
import { queueService, commandCenterService } from '@/services/api'
import type { QueueRow } from '@/types'
import { computeTotalPages, clampPage } from '@/utils/pagination'

export function DoNotContactQueue() {
  const [page, setPage] = useState(1)
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ['queue-do-not-contact', page],
    queryFn: () => queueService.getDoNotContact(page, 20),
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

  const rowActions: RowAction[] = [
    {
      label: 'Reactivate',
      icon: <RestoreIcon fontSize="small" />,
      testId: 'action-reactivate',
      onClick: async (row: QueueRow) => {
        await commandCenterService.reactivate(row.id)
        queryClient.invalidateQueries({ queryKey: ['queue-do-not-contact'] })
        setPage(1)
      },
    },
  ]

  return (
    <Box data-testid="do-not-contact-queue">
      <Typography variant="h6" gutterBottom>
        Do Not Contact
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Total: <strong>{total}</strong>
      </Typography>

      <QueueTable
        rows={rows}
        total={total}
        fromQueue={fromQueue}
        rowActions={rowActions}
        extraColumns={extraColumns}
        {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
      />
    </Box>
  )
}

export default DoNotContactQueue
