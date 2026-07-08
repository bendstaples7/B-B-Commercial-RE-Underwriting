/**
 * QueueTable — reusable sortable table for queue views.
 *
 * Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
 */
import { useState, Fragment } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Checkbox,
  IconButton,
  Link,
  Pagination,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TableSortLabel,
  Tooltip,
  Typography,
  Button,
  Stack,
} from '@mui/material'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import type { QueueRow, BulkActionResult } from '@/types'
import type { FromQueueState } from '@/utils/fromQueue'
import { buildLeadUrl } from '@/utils/queueLogNavigation'
import { LeadStatusChip } from './LeadStatusChip'
import { OutreachContactCallout } from './OutreachContactCallout'
import { outreachDisplayLabel } from '@/constants/scoringRecommendedActions'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RowAction {
  label: string
  icon: React.ReactNode
  onClick: (row: QueueRow) => Promise<void>
  testId?: string
}

export interface BulkAction {
  label: string
  onClick: (ids: number[]) => Promise<BulkActionResult>
  testId?: string
}

export interface ExtraColumn {
  key: string
  label: string
  render: (row: QueueRow) => React.ReactNode
}

export interface QueueTableProps {
  rows: QueueRow[]
  total: number
  /** When set, lead opens preserve HubSpot-style queue work session. */
  fromQueue?: FromQueueState
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
  onSort?: (column: string) => void
  selectedIds?: number[]
  onSelectionChange?: (ids: number[]) => void
  rowActions?: RowAction[]
  bulkActions?: BulkAction[]
  extraColumns?: ExtraColumn[]
  /** Current 1-based page number. Required when totalPages is provided. */
  page?: number
  /** Total number of pages, computed as Math.ceil(total / per_page). */
  totalPages?: number
  /** Called with the new page number when the user changes page. */
  onPageChange?: (page: number) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getOwnerName(row: QueueRow): string {
  return [row.owner_first_name, row.owner_last_name].filter(Boolean).join(' ') || '—'
}

function getAddress(row: QueueRow): string {
  return [row.property_street, row.property_city, row.property_state]
    .filter(Boolean)
    .join(', ') || '—'
}

// ---------------------------------------------------------------------------
// Sortable column definitions
// ---------------------------------------------------------------------------

const SORTABLE_COLUMNS = [
  { key: 'owner_name', label: 'Lead Name' },
  { key: 'lead_score', label: 'Score' },
  { key: 'lead_status', label: 'Status' },
  { key: 'property_street', label: 'Address' },
  { key: 'recommended_action', label: 'Next Action' },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * QueueTable renders a sortable, selectable table of QueueRow items with
 * optimistic UI updates on row actions, bulk selection, and inline error display.
 */
export function QueueTable({
  rows,
  total,
  fromQueue,
  sortBy,
  sortOrder = 'asc',
  onSort,
  selectedIds = [],
  onSelectionChange,
  rowActions = [],
  bulkActions = [],
  extraColumns = [],
  page,
  totalPages,
  onPageChange,
}: QueueTableProps) {
  // Per-row optimistic state: 'pending' | 'error' | null
  const [rowStates, setRowStates] = useState<Record<number, { pending: boolean; error: string | null }>>({})
  // Bulk action result message
  const [bulkMessage, setBulkMessage] = useState<string | null>(null)
  const [isBulkProcessing, setIsBulkProcessing] = useState(false)
  const navigate = useNavigate()
  const leadNavState = fromQueue ? { fromQueue } : undefined
  const leadTo = (id: number) => buildLeadUrl(id, fromQueue?.key)

  // ---------------------------------------------------------------------------
  // Selection helpers
  // ---------------------------------------------------------------------------

  const allSelected = rows.length > 0 && rows.every((r) => selectedIds.includes(r.id))
  const someSelected = rows.some((r) => selectedIds.includes(r.id)) && !allSelected

  const handleSelectAll = () => {
    if (!onSelectionChange) return
    if (allSelected) {
      onSelectionChange([])
    } else {
      onSelectionChange(rows.map((r) => r.id))
    }
  }

  const handleSelectRow = (id: number) => {
    if (!onSelectionChange) return
    if (selectedIds.includes(id)) {
      onSelectionChange(selectedIds.filter((sid) => sid !== id))
    } else {
      onSelectionChange([...selectedIds, id])
    }
  }

  // ---------------------------------------------------------------------------
  // Row action handler — optimistic update
  // ---------------------------------------------------------------------------

  const handleRowAction = async (action: RowAction, row: QueueRow) => {
    // Mark row as pending
    setRowStates((prev) => ({
      ...prev,
      [row.id]: { pending: true, error: null },
    }))

    try {
      await action.onClick(row)
      // Clear pending state on success
      setRowStates((prev) => {
        const next = { ...prev }
        delete next[row.id]
        return next
      })
    } catch (err) {
      // Revert: show inline error
      setRowStates((prev) => ({
        ...prev,
        [row.id]: {
          pending: false,
          error: err instanceof Error ? err.message : 'Action failed. Please try again.',
        },
      }))
    }
  }

  // ---------------------------------------------------------------------------
  // Bulk action handler
  // ---------------------------------------------------------------------------

  const handleBulkAction = async (action: BulkAction) => {
    if (isBulkProcessing) return
    setBulkMessage(null)
    setIsBulkProcessing(true)
    try {
      const result = await action.onClick(selectedIds)
      if (result.failures > 0) {
        setBulkMessage(
          result.message ?? `${result.successes} succeeded, ${result.failures} failed`,
        )
      }
      if (onSelectionChange) {
        onSelectionChange([])
      }
    } catch (err) {
      setBulkMessage(err instanceof Error ? err.message : 'Bulk action failed.')
    } finally {
      setIsBulkProcessing(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Sort handler
  // ---------------------------------------------------------------------------

  const handleSort = (column: string) => {
    if (onSort) {
      onSort(column)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const hasSelection = onSelectionChange !== undefined
  // Always show the actions column — at minimum the built-in View button is shown
  const hasActions = true

  return (
    <Box data-testid="queue-table">
      {/* Bulk action bar */}
      {bulkActions.length > 0 && selectedIds.length > 0 && (
        <Stack
          direction="row"
          spacing={1}
          alignItems="center"
          sx={{ mb: 1, p: 1, bgcolor: 'action.selected', borderRadius: 1 }}
          data-testid="bulk-action-bar"
        >
          <Typography variant="body2" sx={{ mr: 1 }}>
            {selectedIds.length} selected
          </Typography>
          {bulkActions.map((action) => (
            <Button
              key={action.label}
              size="small"
              variant="outlined"
              onClick={() => handleBulkAction(action)}
              disabled={isBulkProcessing}
              data-testid={action.testId ?? `bulk-action-${action.label.toLowerCase().replace(/\s+/g, '-')}`}
            >
              {action.label}
            </Button>
          ))}
        </Stack>
      )}

      {/* Bulk action result message */}
      {bulkMessage && (
        <Alert
          severity="warning"
          sx={{ mb: 1 }}
          onClose={() => setBulkMessage(null)}
          data-testid="bulk-action-message"
        >
          {bulkMessage}
        </Alert>
      )}

      {/* Empty state */}
      {rows.length === 0 ? (
        <Box
          sx={{ py: 6, textAlign: 'center' }}
          data-testid="queue-table-empty"
        >
          <Typography variant="body1" color="text.secondary">
            No leads in this queue
          </Typography>
        </Box>
      ) : (
        <Table size="small" data-testid="queue-table-table">
          <TableHead>
            <TableRow>
              {/* Select-all checkbox */}
              {hasSelection && (
                <TableCell padding="checkbox">
                  <Checkbox
                    checked={allSelected}
                    indeterminate={someSelected}
                    onChange={handleSelectAll}
                    inputProps={{ 'aria-label': 'Select all rows', 'data-testid': 'select-all-checkbox' } as React.InputHTMLAttributes<HTMLInputElement>}
                  />
                </TableCell>
              )}

              {/* Sortable columns */}
              {SORTABLE_COLUMNS.map((col) => (
                <TableCell key={col.key} sortDirection={sortBy === col.key ? sortOrder : false}>
                  {onSort ? (
                    <TableSortLabel
                      active={sortBy === col.key}
                      direction={sortBy === col.key ? sortOrder : 'asc'}
                      onClick={() => handleSort(col.key)}
                      data-testid={`sort-${col.key}`}
                    >
                      {col.label}
                    </TableSortLabel>
                  ) : (
                    col.label
                  )}
                </TableCell>
              ))}

              {/* Extra columns */}
              {extraColumns.map((col) => (
                <TableCell key={col.key}>{col.label}</TableCell>
              ))}

              {/* Actions column */}
              {hasActions && <TableCell align="right">Actions</TableCell>}
            </TableRow>
          </TableHead>

          <TableBody>
            {rows.map((row) => {
              const rowState = rowStates[row.id]
              const isPending = rowState?.pending ?? false
              const rowError = rowState?.error ?? null
              const isSelected = selectedIds.includes(row.id)

              return (
                <Fragment key={row.id}>
                  <TableRow
                    selected={isSelected}
                    sx={{ opacity: isPending ? 0.5 : 1, cursor: 'pointer' }}
                    data-testid={`queue-row-${row.id}`}
                    onClick={(e) => {
                      // Don't navigate if clicking a checkbox or action button
                      const target = e.target as HTMLElement
                      if (target.closest('input[type="checkbox"]') || target.closest('button') || target.closest('a')) return
                      navigate(leadTo(row.id), leadNavState ? { state: leadNavState } : undefined)
                    }}
                  >
                    {/* Row checkbox */}
                    {hasSelection && (
                      <TableCell padding="checkbox">
                        <Checkbox
                          checked={isSelected}
                          onChange={() => handleSelectRow(row.id)}
                          disabled={isPending}
                          inputProps={{ 'aria-label': `Select row ${row.id}`, 'data-testid': `select-row-${row.id}` } as React.InputHTMLAttributes<HTMLInputElement>}
                        />
                      </TableCell>
                    )}

                    {/* Lead name — links to Command Center */}
                    <TableCell data-testid={`row-name-${row.id}`}>
                      <Link
                        component={RouterLink}
                        to={leadTo(row.id)}
                        state={leadNavState}
                        underline="hover"
                        color="primary"
                        fontWeight={500}
                      >
                        {getOwnerName(row)}
                      </Link>
                    </TableCell>

                    {/* Lead score */}
                    <TableCell data-testid={`row-score-${row.id}`}>
                      {row.lead_score}
                    </TableCell>

                    {/* Lead status */}
                    <TableCell data-testid={`row-status-${row.id}`}>
                      {row.lead_status
                        ? <LeadStatusChip status={row.lead_status} />
                        : '—'
                      }
                    </TableCell>

                    {/* Property address */}
                    <TableCell data-testid={`row-address-${row.id}`}>
                      {getAddress(row)}
                    </TableCell>

                    {/* Recommended action */}
                    <TableCell data-testid={`row-action-${row.id}`}>
                      {row.recommended_action ? (
                        <Box>
                          <Typography variant="body2" component="span">
                            {row.outreach_action_label
                              ?? outreachDisplayLabel(row.recommended_action, row.recommended_contact_method)}
                          </Typography>
                          <OutreachContactCallout contact={row.outreach_contact} compact />
                        </Box>
                      ) : (
                        '—'
                      )}
                    </TableCell>

                    {/* Extra columns */}
                    {extraColumns.map((col) => (
                      <TableCell key={col.key}>
                        {col.render(row)}
                      </TableCell>
                    ))}

                    {/* Row actions */}
                    {hasActions && (
                      <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                        {/* Built-in: open Command Center */}
                        <Tooltip title="Open lead detail">
                          <IconButton
                            size="small"
                            component={RouterLink}
                            to={leadTo(row.id)}
                            state={leadNavState}
                            aria-label="Open lead detail"
                            data-testid={`row-action-view-${row.id}`}
                          >
                            <OpenInNewIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        {rowActions.map((action) => (
                          <Tooltip key={action.label} title={action.label}>
                            <span>
                              <IconButton
                                size="small"
                                onClick={() => handleRowAction(action, row)}
                                disabled={isPending}
                                aria-label={action.label}
                                data-testid={action.testId ?? `row-action-${action.label.toLowerCase().replace(/\s+/g, '-')}-${row.id}`}
                              >
                                {action.icon}
                              </IconButton>
                            </span>
                          </Tooltip>
                        ))}
                      </TableCell>
                    )}
                  </TableRow>

                  {/* Inline error row */}
                  {rowError && (
                    <TableRow key={`${row.id}-error`} data-testid={`row-error-${row.id}`}>
                      <TableCell
                        colSpan={
                          (hasSelection ? 1 : 0) +
                          SORTABLE_COLUMNS.length +
                          extraColumns.length +
                          (hasActions ? 1 : 0)
                        }
                        sx={{ py: 0 }}
                      >
                        <Alert
                          severity="error"
                          sx={{ py: 0 }}
                          onClose={() =>
                            setRowStates((prev) => {
                              const next = { ...prev }
                              delete next[row.id]
                              return next
                            })
                          }
                        >
                          {rowError}
                        </Alert>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      )}

      {/* Total count */}
      {rows.length > 0 && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ mt: 1, display: 'block' }}
          data-testid="queue-table-total"
        >
          {total} total
        </Typography>
      )}

      {/* Pagination controls */}
      {(totalPages ?? 0) > 1 && (
        <Box
          sx={{ mt: 2, display: 'flex', alignItems: 'center', gap: 2 }}
          aria-label="queue pagination"
          data-testid="queue-pagination"
        >
          <Typography variant="caption" color="text.secondary" data-testid="queue-page-label">
            Page {page} of {totalPages}
          </Typography>
          <Pagination
            count={totalPages}
            page={page}
            shape="rounded"
            color="primary"
            onChange={(_event, value) => onPageChange?.(value)}
            aria-label="queue pagination"
          />
        </Box>
      )}
    </Box>
  )
}

export default QueueTable
