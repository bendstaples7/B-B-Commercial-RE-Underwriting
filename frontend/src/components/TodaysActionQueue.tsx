/**
 * TodaysActionQueue — Today's Action queue view.
 *
 * Due open tasks (due today or earlier), sorted by lead score.
 * Optional next-action (outreach) filter for Mail Now / Call Now bulk workflows.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  Link,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material'
import type { SelectChangeEvent } from '@mui/material/Select'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { QueueTable } from './QueueTable'
import type { RowAction } from './QueueTable'
import { QueueLoadingState } from './QueueLoadingState'
import { queueService } from '@/services/api'
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
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { queueListQueryDefaults, queuePlaceholderTableSx } from '@/utils/queueQueryDefaults'

export interface TodaysActionQueueProps {
  extraQueryKeys?: string[]
}

type OutreachFilter = '' | 'mail_now' | 'call_now' | 'email_now' | 'text_now'

const OUTREACH_OPTIONS: { value: OutreachFilter; label: string }[] = [
  { value: '', label: 'All next actions' },
  { value: 'mail_now', label: 'Mail Now' },
  { value: 'call_now', label: 'Call Now' },
  { value: 'email_now', label: 'Email Now' },
  { value: 'text_now', label: 'Text Now' },
]

export function TodaysActionQueue({ extraQueryKeys }: TodaysActionQueueProps = {}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [outreach, setOutreach] = useState<OutreachFilter>('')
  const [selectError, setSelectError] = useState<string | null>(null)
  const { selectedIds, onSelectionChange, onPageChangeWithClear, clearSelection } =
    useQueueSelection()

  const outreachParam = outreach || null

  const { data, isLoading, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['queue-todays-action', page, outreach],
    queryFn: () => queueService.getTodaysAction(page, 20, outreachParam),
    ...queueListQueryDefaults,
  })

  const { data: outreachCounts } = useQuery({
    queryKey: ['queue-todays-action-outreach-counts'],
    queryFn: () => queueService.getTodaysActionOutreachCounts(),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const totalPages = computeTotalPages(data?.total ?? 0, data?.per_page ?? 20)
  const isInitialLoading = isLoading && !data
  const showEmpty = data != null && rows.length === 0 && total === 0
  const showRefetchIndicator = isFetching && isPlaceholderData
  const disablePlaceholderInteractions = isPlaceholderData

  const handlePageChange = onPageChangeWithClear((newPage) => {
    setPage(clampPage(newPage, totalPages))
  })

  const handleOutreachChange = (event: SelectChangeEvent) => {
    setOutreach(event.target.value as OutreachFilter)
    setPage(1)
    clearSelection()
    setSelectError(null)
  }

  const selectAllMatching = async () => {
    try {
      const result = await queueService.getTodaysActionLeadIds(outreachParam)
      onSelectionChange(result.lead_ids)
      setSelectError(null)
    } catch (err) {
      console.error('[TodaysActionQueue] Failed to load matching lead IDs:', err)
      setSelectError(
        err instanceof Error ? err.message : 'Failed to select matching leads. Please try again.',
      )
    }
  }

  const fromQueue = {
    key: 'todays-action',
    label: "Today's Action",
    ...(outreach ? { outreach } : {}),
  }
  const navigateOptions = { navigate, fromQueue }
  const actionExtraQueryKeys = [
    ...(extraQueryKeys ?? []),
    'queue-todays-action-outreach-counts',
  ]
  const bulkCtx = {
    queryClient,
    queryKey: 'queue-todays-action',
    extraQueryKeys: actionExtraQueryKeys,
    onAfterAction: () => {
      clearSelection()
      setPage(1)
    },
  }
  const taskOptions = {
    queryClient,
    queryKey: 'queue-todays-action',
    extraQueryKeys: actionExtraQueryKeys,
    onAfterAction: () => {
      clearSelection()
      setPage(1)
    },
  }

  const rowActions: RowAction[] = [
    createAddToMailBatchRowAction(bulkCtx),
    createLogCallRowAction(navigateOptions),
    createLogNoteRowAction(navigateOptions),
    createCreateTaskRowAction(taskOptions),
  ]

  const bulkActions = resolveBulkActions(['add_to_mail_batch', 'create_task'], bulkCtx)

  const optionLabel = (value: OutreachFilter, label: string) => {
    if (!outreachCounts) return label
    if (value === '') {
      const count = outreachCounts.all ?? total
      return `${label} (${count})`
    }
    const count = outreachCounts[value] ?? 0
    return `${label} (${count})`
  }

  return (
    <Box data-testid="todays-action-queue" sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Typography variant="h6" gutterBottom>
        Today's Action
      </Typography>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ xs: 'stretch', sm: 'center' }}
        sx={{ mb: 2, width: '100%' }}
        flexWrap="wrap"
        useFlexGap
      >
        <Typography variant="body2" color="text.secondary">
          Total:{' '}
          <strong data-testid="todays-action-total">
            {data != null && !isPlaceholderData ? total : '—'}
          </strong>
          {showRefetchIndicator && (
            <CircularProgress size={14} sx={{ ml: 1, verticalAlign: 'middle' }} />
          )}
        </Typography>
        <FormControl size="small" sx={{ minWidth: { xs: 0, sm: 220 }, width: { xs: '100%', sm: 'auto' } }}>
          <InputLabel id="todays-action-outreach-label">Next action</InputLabel>
          <Select
            labelId="todays-action-outreach-label"
            label="Next action"
            value={outreach}
            onChange={handleOutreachChange}
            data-testid="todays-action-outreach-filter"
          >
            {OUTREACH_OPTIONS.map((opt) => (
              <MenuItem key={opt.value || 'all'} value={opt.value}>
                {optionLabel(opt.value, opt.label)}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {outreach !== '' && total > 0 && data != null && !isPlaceholderData && (
          <Button
            size="small"
            variant="outlined"
            onClick={selectAllMatching}
            data-testid="todays-action-select-all-matching"
            sx={{ width: { xs: '100%', sm: 'auto' } }}
          >
            Select all {OUTREACH_OPTIONS.find((o) => o.value === outreach)?.label ?? 'matching'}
          </Button>
        )}
      </Stack>

      {selectError && (
        <Typography variant="body2" color="error" sx={{ mb: 1 }} data-testid="todays-action-select-error">
          {selectError}
        </Typography>
      )}

      {isInitialLoading ? (
        <QueueLoadingState />
      ) : showEmpty ? (
        <Box sx={{ py: 4, textAlign: 'center' }} data-testid="todays-action-empty">
          <Typography variant="body1" color="text.secondary" gutterBottom>
            {outreach
              ? `No leads with that next action in Today's Action.`
              : "You're all caught up!"}
          </Typography>
          {outreach ? (
            <Button size="small" onClick={() => setOutreach('')}>
              Clear filter
            </Button>
          ) : (
            <Link component={RouterLink} to="/queues/no-next-action" variant="body2">
              View leads with no next action →
            </Link>
          )}
        </Box>
      ) : (
        <Box sx={queuePlaceholderTableSx(disablePlaceholderInteractions)}>
          <QueueTable
            rows={rows}
            total={total}
            disabled={disablePlaceholderInteractions}
            isPlaceholderData={disablePlaceholderInteractions}
            fromQueue={fromQueue}
            selectedIds={selectedIds}
            onSelectionChange={onSelectionChange}
            rowActions={rowActions}
            bulkActions={bulkActions}
            {...(totalPages > 1 ? { page, totalPages, onPageChange: handlePageChange } : {})}
          />
        </Box>
      )}
    </Box>
  )
}

export default TodaysActionQueue
