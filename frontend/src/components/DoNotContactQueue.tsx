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

export function DoNotContactQueue() {
  const [page] = useState(1)
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ['queue-do-not-contact', page],
    queryFn: () => queueService.getDoNotContact(page, 20),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0

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

  const rowActions: RowAction[] = [
    {
      label: 'Reactivate',
      icon: <RestoreIcon fontSize="small" />,
      testId: 'action-reactivate',
      onClick: async (row: QueueRow) => {
        await commandCenterService.reactivate(row.id)
        queryClient.invalidateQueries({ queryKey: ['queue-do-not-contact'] })
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
        rowActions={rowActions}
        extraColumns={extraColumns}
      />
    </Box>
  )
}

export default DoNotContactQueue
