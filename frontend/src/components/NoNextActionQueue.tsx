/**
 * NoNextActionQueue — No Next Action queue view.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Chip, Typography } from '@mui/material'
import BlockIcon from '@mui/icons-material/Block'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { queueService, commandCenterService } from '@/services/api'
import type { QueueRow } from '@/types'
import { createLogNoteRowAction } from './queueRowActions'
import { SuppressLeadDialog } from './SuppressLeadDialog'
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
  const navigate = useNavigate()
  const [suppressTarget, setSuppressTarget] = useState<QueueRow | null>(null)
  const [suppressError, setSuppressError] = useState<string | null>(null)

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
    setSuppressError(null)
    try {
      await commandCenterService.suppress(suppressTarget.id)
      queryClient.invalidateQueries({ queryKey: ['queue-no-next-action'] })
      setPage(1)
      setSuppressTarget(null)
    } catch (err) {
      console.error('[NoNextActionQueue] Suppress failed:', err)
      setSuppressError(err instanceof Error ? err.message : 'Suppress failed. Please try again.')
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

  const fromQueue = { key: 'no-next-action', label: 'No Next Action' }
  const navigateOptions = { navigate, fromQueue }

  const rowActions: RowAction[] = [
    createLogNoteRowAction(navigateOptions),
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
        fromQueue={fromQueue}
        rowActions={rowActions}
        extraColumns={extraColumns}
        {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
      />

      <SuppressLeadDialog
        open={suppressTarget !== null}
        error={suppressError}
        onClose={() => {
          setSuppressTarget(null)
          setSuppressError(null)
        }}
        onConfirm={handleSuppressConfirm}
      />
    </Box>
  )
}

export default NoNextActionQueue
