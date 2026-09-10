import React, { useEffect, useMemo, useState } from 'react'
import {
  Box,
  Button,
  Checkbox,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link as RouterLink } from 'react-router-dom'
import { globalNotify } from '@/context/NotificationContext'
import openLetterService, {
  type MailQueueItem,
  type MailQueueSummary,
} from '@/services/openLetterApi'
import { formatLastMailedDate, formatLastSaleDate } from '@/utils/formatLastMailedDate'

/** Matches backend MAX_MAIL_ENQUEUE_LEADS for bulk remove. */
export const MAIL_QUEUE_BULK_REMOVE_LIMIT = 1000

export interface MailQueueStagedTableProps {
  items: MailQueueItem[]
  emptyMessage?: string
}

function withDerivedSummaryFields(
  summary: MailQueueSummary,
  queuedCount: number,
): MailQueueSummary {
  const canSend = Boolean(
    queuedCount > 0
    && (queuedCount >= summary.batch_minimum || summary.allow_send_below_minimum),
  )
  const estimatedTotal =
    summary.estimated_cost_per_piece != null
      ? summary.estimated_cost_per_piece * queuedCount
      : summary.estimated_total
  return {
    ...summary,
    queued_count: queuedCount,
    can_send: canSend,
    estimated_total: estimatedTotal,
  }
}

function dropItemsFromSummary(
  current: MailQueueSummary | undefined,
  itemIds: number[],
): MailQueueSummary | undefined {
  if (!current?.items) return current
  const removeSet = new Set(itemIds)
  const nextItems = current.items.filter((row) => !removeSet.has(row.id))
  const removed = current.items.length - nextItems.length
  if (removed === 0) return current
  const queuedCount = Math.max(0, current.queued_count - removed)
  return withDerivedSummaryFields(
    {
      ...current,
      items: nextItems,
      total: typeof current.total === 'number'
        ? Math.max(0, current.total - removed)
        : current.total,
    },
    queuedCount,
  )
}

function chunkIds(ids: number[], size: number): number[][] {
  const chunks: number[][] = []
  for (let i = 0; i < ids.length; i += size) {
    chunks.push(ids.slice(i, i + size))
  }
  return chunks
}

async function removeManyInChunks(ids: number[]) {
  const uniqueIds = [...new Set(ids)]
  const chunks = chunkIds(uniqueIds, MAIL_QUEUE_BULK_REMOVE_LIMIT)
  let removed = 0
  let alreadyRemoved = 0
  const blocked: Array<{ item_id: number; lead_id: number; status: string; error: string }> = []
  let summary: MailQueueSummary | null = null

  for (const chunk of chunks) {
    const result = await openLetterService.removeManyFromQueue(chunk)
    removed += result.removed
    alreadyRemoved += result.already_removed
    blocked.push(...(result.blocked ?? []))
    summary = result
  }

  if (!summary) {
    throw new Error('No queue items were selected to remove.')
  }
  return {
    ...summary,
    removed,
    already_removed: alreadyRemoved,
    blocked,
  }
}

export const MailQueueStagedTable: React.FC<MailQueueStagedTableProps> = ({
  items,
  emptyMessage = 'No leads staged for the next batch.',
}) => {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<number[]>([])

  const itemIds = useMemo(() => items.map((item) => item.id), [items])

  useEffect(() => {
    setSelectedIds((prev) => prev.filter((id) => itemIds.includes(id)))
  }, [itemIds])

  const allSelected = items.length > 0 && items.every((item) => selectedIds.includes(item.id))
  const someSelected = selectedIds.length > 0 && !allSelected

  const invalidateMailQueries = () => {
    queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
    queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    queryClient.invalidateQueries({ queryKey: ['queue-mail-candidates'] })
  }

  const removeOneMutation = useMutation({
    mutationFn: (itemId: number) => openLetterService.removeFromQueue(itemId),
    onSuccess: (_data, itemId) => {
      queryClient.setQueryData<MailQueueSummary>(['mail-queue'], (current) =>
        dropItemsFromSummary(current, [itemId]),
      )
      setSelectedIds((prev) => prev.filter((id) => id !== itemId))
      invalidateMailQueries()
    },
  })

  const removeManyMutation = useMutation({
    mutationFn: removeManyInChunks,
    onSuccess: (data, ids) => {
      const blockedIds = new Set((data.blocked ?? []).map((row) => row.item_id))
      const droppedIds = ids.filter((id) => !blockedIds.has(id))
      queryClient.setQueryData<MailQueueSummary>(['mail-queue'], (current) =>
        dropItemsFromSummary(current, droppedIds),
      )
      setSelectedIds((prev) => prev.filter((id) => blockedIds.has(id)))
      if (data.blocked?.length) {
        const reasons = data.blocked
          .map((row) => row.error)
          .filter(Boolean)
        const uniqueReasons = [...new Set(reasons)]
        globalNotify.showError(
          uniqueReasons.length === 1
            ? uniqueReasons[0]
            : `Could not remove ${data.blocked.length} selected item(s): ${uniqueReasons.join('; ')}`,
        )
      }
      invalidateMailQueries()
    },
  })

  const busy = removeOneMutation.isPending || removeManyMutation.isPending

  const toggleAll = () => {
    if (allSelected) {
      setSelectedIds([])
      return
    }
    setSelectedIds(items.map((item) => item.id))
  }

  const toggleOne = (id: number) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((value) => value !== id) : [...prev, id],
    )
  }

  return (
    <Box>
      {selectedIds.length > 0 && (
        <Stack
          direction="row"
          spacing={1}
          alignItems="center"
          sx={{ px: 1.5, py: 1, bgcolor: 'action.selected' }}
          data-testid="mail-queue-staged-bulk-bar"
        >
          <Typography variant="body2">{selectedIds.length} selected</Typography>
          <Button
            size="small"
            variant="outlined"
            color="error"
            startIcon={<DeleteIcon />}
            disabled={busy}
            onClick={() => removeManyMutation.mutate(selectedIds)}
            data-testid="mail-queue-staged-bulk-remove"
          >
            Remove selected
          </Button>
        </Stack>
      )}
      <TableContainer
        component={Paper}
        data-testid="mail-queue-staged-table"
        sx={{ overflowX: 'auto' }}
      >
        <Table size="small" sx={{ minWidth: 640 }}>
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  size="small"
                  checked={allSelected}
                  indeterminate={someSelected}
                  disabled={items.length === 0 || busy}
                  onChange={toggleAll}
                  inputProps={{
                    'aria-label': 'Select all staged leads',
                    'data-testid': 'mail-queue-staged-select-all',
                  } as React.InputHTMLAttributes<HTMLInputElement>}
                />
              </TableCell>
              <TableCell>Owner</TableCell>
              <TableCell>Property</TableCell>
              <TableCell>Mailing address</TableCell>
              <TableCell>Last mailed</TableCell>
              <TableCell>Last sale</TableCell>
              <TableCell>Added</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center">
                  <Typography color="text.secondary" sx={{ py: 3 }}>
                    {emptyMessage}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              items.map((item) => {
                const selected = selectedIds.includes(item.id)
                return (
                  <TableRow key={item.id} selected={selected}>
                    <TableCell padding="checkbox">
                      <Checkbox
                        size="small"
                        checked={selected}
                        disabled={busy}
                        onChange={() => toggleOne(item.id)}
                        inputProps={{
                          'aria-label': `Select staged lead ${item.lead_id}`,
                          'data-testid': `mail-queue-staged-select-${item.id}`,
                        } as React.InputHTMLAttributes<HTMLInputElement>}
                      />
                    </TableCell>
                    <TableCell sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                      {item.owner_name || '—'}
                    </TableCell>
                    <TableCell sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                      <RouterLink to={`/leads/${item.lead_id}`}>
                        {item.property_street || `#${item.lead_id}`}
                      </RouterLink>
                    </TableCell>
                    <TableCell sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
                      {[item.mailing_address, item.mailing_city, item.mailing_state, item.mailing_zip]
                        .filter(Boolean)
                        .join(', ') || '—'}
                    </TableCell>
                    <TableCell>{formatLastMailedDate(item.last_mailed_at)}</TableCell>
                    <TableCell>{formatLastSaleDate(item.last_sale_at)}</TableCell>
                    <TableCell>{formatLastMailedDate(item.created_at)}</TableCell>
                    <TableCell align="right">
                      <IconButton
                        size="small"
                        aria-label="Remove from batch"
                        onClick={() => removeOneMutation.mutate(item.id)}
                        disabled={busy}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}
