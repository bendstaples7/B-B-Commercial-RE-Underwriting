/**
 * NoNextActionQueue — No Next Action queue view with bulk status updates.
 */
import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  Button,
  Chip,
  Stack,
  Typography,
} from '@mui/material'
import BlockIcon from '@mui/icons-material/Block'
import EditIcon from '@mui/icons-material/Edit'
import { useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction, ExtraColumn } from './QueueTable'
import { QueueLoadingState } from './QueueLoadingState'
import {
  queueService,
  commandCenterService,
  bulkActionService,
} from '@/services/api'
import type { LeadStatus, QueueRow } from '@/types'
import { createLogNoteRowAction } from './queueRowActions'
import { resolveBulkActions } from './queueBulkActions'
import { useQueueSelection } from '@/hooks/useQueueSelection'
import { SuppressLeadDialog } from './SuppressLeadDialog'
import { BulkStatusUpdateDialog } from './BulkStatusUpdateDialog'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { queueListQueryDefaults, queuePlaceholderTableSx } from '@/utils/queueQueryDefaults'
import { ALL_LEAD_STATUSES } from '@/constants/leadStatuses'
import { LEAD_STATUS_LABELS } from '@/components/LeadStatusChip'

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
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()
  const [suppressTarget, setSuppressTarget] = useState<QueueRow | null>(null)
  const [suppressError, setSuppressError] = useState<string | null>(null)
  const [selectError, setSelectError] = useState<string | null>(null)
  const [statusDialogOpen, setStatusDialogOpen] = useState(false)
  const [queueWideSourceStatus, setQueueWideSourceStatus] = useState<LeadStatus | null>(null)
  const [bulkError, setBulkError] = useState<string | null>(null)

  const { data, isLoading, isPlaceholderData } = useQuery({
    queryKey: ['queue-no-next-action', page],
    queryFn: () => queueService.getNoNextAction(page, 20),
    ...queueListQueryDefaults,
  })

  const { data: statusCounts = {} } = useQuery({
    queryKey: ['queue-no-next-action-status-counts'],
    queryFn: () => queueService.getNoNextActionStatusCounts(),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const isInitialLoading = isLoading && !data
  const showRefetchIndicator = isPlaceholderData
  const handlePageChange = onPageChangeWithClear((newPage) => {
    setPage(clampPage(newPage, totalPages))
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['queue-no-next-action'] })
    queryClient.invalidateQueries({ queryKey: ['queue-no-next-action-status-counts'] })
    queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
  }

  const handleSuppressConfirm = async () => {
    if (!suppressTarget) return
    setSuppressError(null)
    try {
      await commandCenterService.suppress(suppressTarget.id)
      invalidate()
      setPage(1)
      clearSelection()
      setSuppressTarget(null)
    } catch (err) {
      console.error('[NoNextActionQueue] Suppress failed:', err)
      setSuppressError(err instanceof Error ? err.message : 'Suppress failed. Please try again.')
      throw err
    }
  }

  const statusChips = useMemo(
    () => Object.entries(statusCounts).filter(([, count]) => count > 0),
    [statusCounts],
  )

  const selectAllOnPageForStatus = (status: string) => {
    const ids = rows.filter((r) => r.lead_status === status).map((r) => r.id)
    onSelectionChange(ids)
  }

  const selectAllInQueueForStatus = async (status: string) => {
    try {
      const result = await queueService.getNoNextActionLeadIds(status)
      onSelectionChange(result.lead_ids)
      setSelectError(null)
    } catch (err) {
      console.error('[NoNextActionQueue] Failed to load queue lead IDs:', err)
      setSelectError(
        err instanceof Error ? err.message : 'Failed to select leads in queue. Please try again.',
      )
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

  const bulkCtx = {
    queryClient,
    queryKey: 'queue-no-next-action',
    extraQueryKeys: ['queue-no-next-action-status-counts', 'queue-counts'],
    onAfterAction: () => {
      clearSelection()
      setPage(1)
      setBulkError(null)
    },
  }

  const bulkActions = resolveBulkActions(['suppress'], bulkCtx).map((action) => ({
    ...action,
    onClick: async (ids: number[]) => {
      setBulkError(null)
      try {
        return await action.onClick(ids)
      } catch (err) {
        console.error('[NoNextActionQueue] Bulk suppress failed:', err)
        setBulkError(
          err instanceof Error ? err.message : 'Bulk suppress failed. Please try again.',
        )
        throw err
      }
    },
  }))

  const handleBulkStatusConfirm = async (status: LeadStatus, reason: string) => {
    setBulkError(null)
    try {
      if (queueWideSourceStatus) {
        await queueService.bulkUpdateNoNextActionStatus({
          source_status: queueWideSourceStatus,
          status,
          reason,
        })
      } else if (selectedIds.length > 0) {
        await bulkActionService.bulkUpdateStatus(selectedIds, status, reason)
      }
      invalidate()
      clearSelection()
      setPage(1)
      setQueueWideSourceStatus(null)
      setStatusDialogOpen(false)
    } catch (err) {
      console.error('[NoNextActionQueue] Bulk status update failed:', err)
      setBulkError(
        err instanceof Error ? err.message : 'Bulk status update failed. Please try again.',
      )
      throw err
    }
  }

  return (
    <Box data-testid="no-next-action-queue">
      <Typography variant="h6" gutterBottom>
        No Next Action
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Total: <strong>{data != null && !isPlaceholderData ? total : '—'}</strong>
      </Typography>

      {bulkError && (
        <Typography variant="caption" color="error" display="block" sx={{ mb: 1 }} data-testid="bulk-action-error">
          {bulkError}
        </Typography>
      )}

      {statusChips.length > 0 && (
        <Box
          sx={{
            mb: 2,
            ...(showRefetchIndicator ? { pointerEvents: 'none', opacity: 0.6 } : {}),
          }}
          data-testid="status-shortcuts-toolbar"
        >
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            Select all by status
          </Typography>
          {selectError && (
            <Typography variant="caption" color="error" display="block" sx={{ mb: 1 }} data-testid="select-queue-error">
              {selectError}
            </Typography>
          )}
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {statusChips.map(([status, count]) => (
              <Stack key={status} direction="row" spacing={0.5} alignItems="center">
                <Chip
                  size="small"
                  label={`${LEAD_STATUS_LABELS[status as LeadStatus] ?? status} (${count})`}
                  onClick={showRefetchIndicator ? undefined : () => selectAllOnPageForStatus(status)}
                  disabled={showRefetchIndicator}
                  data-testid={`select-page-${status}`}
                />
                <Button
                  size="small"
                  onClick={() => selectAllInQueueForStatus(status)}
                  disabled={showRefetchIndicator}
                  data-testid={`select-queue-${status}`}
                >
                  All {count}
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => {
                    setQueueWideSourceStatus(status as LeadStatus)
                    setStatusDialogOpen(true)
                  }}
                  disabled={showRefetchIndicator}
                  data-testid={`bulk-queue-${status}`}
                >
                  Update all
                </Button>
              </Stack>
            ))}
          </Stack>
        </Box>
      )}

      {selectedIds.length > 0 && !showRefetchIndicator && (
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <Button
            size="small"
            variant="contained"
            startIcon={<EditIcon />}
            onClick={() => {
              setQueueWideSourceStatus(null)
              setStatusDialogOpen(true)
            }}
            data-testid="bulk-update-status-selected"
          >
            Update status ({selectedIds.length})
          </Button>
        </Stack>
      )}

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
            rowActions={rowActions}
            extraColumns={extraColumns}
            selectedIds={selectedIds}
            onSelectionChange={onSelectionChange}
            bulkActions={bulkActions}
            {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
          />
        </Box>
      )}

      <BulkStatusUpdateDialog
        open={statusDialogOpen}
        selectedCount={
          queueWideSourceStatus
            ? (statusCounts[queueWideSourceStatus] ?? 0)
            : selectedIds.length
        }
        allStatuses={ALL_LEAD_STATUSES}
        defaultStatus={queueWideSourceStatus === 'awaiting_skip_trace' ? 'skip_trace' : null}
        onClose={() => {
          setStatusDialogOpen(false)
          setQueueWideSourceStatus(null)
        }}
        onConfirm={handleBulkStatusConfirm}
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
