/**
 * MissingPropertyMatchQueue — Missing Property Match queue view.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Typography } from '@mui/material'
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
import { SuppressLeadDialog } from './SuppressLeadDialog'
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

  const fromQueue = { key: 'missing-property-match', label: 'Missing Property Match' }

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
        fromQueue={fromQueue}
        rowActions={rowActions}
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

export default MissingPropertyMatchQueue
