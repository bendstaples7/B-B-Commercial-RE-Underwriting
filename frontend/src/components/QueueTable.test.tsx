/**
 * Tests for QueueTable component
 *
 * Covers:
 * - sortable columns: clicking sort labels calls onSort with correct column key
 * - bulk selection: select-all, per-row, deselect
 * - optimistic update revert on failure: row shows error, pending state clears
 * - empty state: "No leads in this queue" shown when rows is empty
 * - bulk partial failure summary: "X succeeded, Y failed" message shown
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { QueueTable } from './QueueTable'
import type { QueueRow, BulkActionResult } from '@/types'
import PhoneIcon from '@mui/icons-material/Phone'

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeRow(id: number, overrides: Partial<QueueRow> = {}): QueueRow {
  return {
    id,
    owner_first_name: `First${id}`,
    owner_last_name: `Last${id}`,
    property_street: `${id} Main St`,
    property_city: 'Springfield',
    property_state: 'IL',
    lead_score: 50 + id,
    lead_status: 'active',
    recommended_action: null,
    has_property_match: true,
    last_contact_date: null,
    last_hubspot_sync_at: null,
    hubspot_deal_stage: null,
    follow_up_overdue: false,
    review_required: false,
    review_reason: null,
    review_triggered_at: null,
    unanswered_call_count: 0,
    is_warm: false,
    ...overrides,
  }
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('QueueTable', () => {
  // -------------------------------------------------------------------------
  // Empty state
  // -------------------------------------------------------------------------

  describe('empty state', () => {
    it('shows "No leads in this queue" when rows is empty', () => {
      render(<QueueTable rows={[]} total={0} />)

      expect(screen.getByTestId('queue-table-empty')).toBeInTheDocument()
      expect(screen.getByText('No leads in this queue')).toBeInTheDocument()
    })

    it('does not show the table when rows is empty', () => {
      render(<QueueTable rows={[]} total={0} />)

      expect(screen.queryByTestId('queue-table-table')).not.toBeInTheDocument()
    })

    it('does not show empty state when rows exist', () => {
      render(<QueueTable rows={[makeRow(1)]} total={1} />)

      expect(screen.queryByTestId('queue-table-empty')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Sortable columns
  // -------------------------------------------------------------------------

  describe('sortable columns', () => {
    it('renders sort labels for all four sortable columns', () => {
      const onSort = vi.fn()
      render(<QueueTable rows={[makeRow(1)]} total={1} onSort={onSort} />)

      expect(screen.getByTestId('sort-owner_name')).toBeInTheDocument()
      expect(screen.getByTestId('sort-lead_score')).toBeInTheDocument()
      expect(screen.getByTestId('sort-lead_status')).toBeInTheDocument()
      expect(screen.getByTestId('sort-property_street')).toBeInTheDocument()
    })

    it('calls onSort with "owner_name" when Lead Name header is clicked', async () => {
      const onSort = vi.fn()
      render(<QueueTable rows={[makeRow(1)]} total={1} onSort={onSort} />)

      await user.click(screen.getByTestId('sort-owner_name'))

      expect(onSort).toHaveBeenCalledWith('owner_name')
    })

    it('calls onSort with "lead_score" when Score header is clicked', async () => {
      const onSort = vi.fn()
      render(<QueueTable rows={[makeRow(1)]} total={1} onSort={onSort} />)

      await user.click(screen.getByTestId('sort-lead_score'))

      expect(onSort).toHaveBeenCalledWith('lead_score')
    })

    it('calls onSort with "lead_status" when Status header is clicked', async () => {
      const onSort = vi.fn()
      render(<QueueTable rows={[makeRow(1)]} total={1} onSort={onSort} />)

      await user.click(screen.getByTestId('sort-lead_status'))

      expect(onSort).toHaveBeenCalledWith('lead_status')
    })

    it('calls onSort with "property_street" when Address header is clicked', async () => {
      const onSort = vi.fn()
      render(<QueueTable rows={[makeRow(1)]} total={1} onSort={onSort} />)

      await user.click(screen.getByTestId('sort-property_street'))

      expect(onSort).toHaveBeenCalledWith('property_street')
    })

    it('marks the active sort column with the correct direction', () => {
      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          onSort={vi.fn()}
          sortBy="lead_score"
          sortOrder="desc"
        />
      )

      // The active TableSortLabel should have aria-sort="descending"
      const sortLabel = screen.getByTestId('sort-lead_score')
      const sortEl = sortLabel.closest('[aria-sort]') ?? sortLabel
      expect(sortEl).toHaveAttribute('aria-sort', 'descending')
    })

    it('does not render sort labels when onSort is not provided', () => {
      render(<QueueTable rows={[makeRow(1)]} total={1} />)

      expect(screen.queryByTestId('sort-owner_name')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Bulk selection
  // -------------------------------------------------------------------------

  describe('bulk selection', () => {
    it('renders per-row checkboxes when onSelectionChange is provided', () => {
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          onSelectionChange={vi.fn()}
        />
      )

      expect(screen.getByTestId('select-row-1')).toBeInTheDocument()
      expect(screen.getByTestId('select-row-2')).toBeInTheDocument()
    })

    it('renders select-all checkbox in header', () => {
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          onSelectionChange={vi.fn()}
        />
      )

      expect(screen.getByTestId('select-all-checkbox')).toBeInTheDocument()
    })

    it('does not render checkboxes when onSelectionChange is not provided', () => {
      render(<QueueTable rows={[makeRow(1)]} total={1} />)

      expect(screen.queryByTestId('select-all-checkbox')).not.toBeInTheDocument()
      expect(screen.queryByTestId('select-row-1')).not.toBeInTheDocument()
    })

    it('calls onSelectionChange with all row ids when select-all is clicked', async () => {
      const onSelectionChange = vi.fn()
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2), makeRow(3)]}
          total={3}
          selectedIds={[]}
          onSelectionChange={onSelectionChange}
        />
      )

      await user.click(screen.getByTestId('select-all-checkbox'))

      expect(onSelectionChange).toHaveBeenCalledWith([1, 2, 3])
    })

    it('calls onSelectionChange with empty array when all are selected and select-all is clicked', async () => {
      const onSelectionChange = vi.fn()
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          selectedIds={[1, 2]}
          onSelectionChange={onSelectionChange}
        />
      )

      await user.click(screen.getByTestId('select-all-checkbox'))

      expect(onSelectionChange).toHaveBeenCalledWith([])
    })

    it('calls onSelectionChange with the row id added when a row checkbox is clicked', async () => {
      const onSelectionChange = vi.fn()
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          selectedIds={[]}
          onSelectionChange={onSelectionChange}
        />
      )

      await user.click(screen.getByTestId('select-row-1'))

      expect(onSelectionChange).toHaveBeenCalledWith([1])
    })

    it('calls onSelectionChange with the row id removed when a selected row checkbox is clicked', async () => {
      const onSelectionChange = vi.fn()
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          selectedIds={[1, 2]}
          onSelectionChange={onSelectionChange}
        />
      )

      await user.click(screen.getByTestId('select-row-1'))

      expect(onSelectionChange).toHaveBeenCalledWith([2])
    })

    it('shows bulk action bar when rows are selected and bulkActions provided', () => {
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          selectedIds={[1]}
          onSelectionChange={vi.fn()}
          bulkActions={[{ label: 'Suppress', onClick: vi.fn() }]}
        />
      )

      expect(screen.getByTestId('bulk-action-bar')).toBeInTheDocument()
    })

    it('does not show bulk action bar when no rows are selected', () => {
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          selectedIds={[]}
          onSelectionChange={vi.fn()}
          bulkActions={[{ label: 'Suppress', onClick: vi.fn() }]}
        />
      )

      expect(screen.queryByTestId('bulk-action-bar')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Optimistic update revert on failure
  // -------------------------------------------------------------------------

  describe('optimistic update revert on failure', () => {
    it('shows inline error when row action fails', async () => {
      const failingAction = {
        label: 'Call',
        icon: <PhoneIcon />,
        onClick: vi.fn().mockRejectedValue(new Error('Network error')),
        testId: 'action-call-1',
      }

      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          rowActions={[failingAction]}
        />
      )

      await user.click(screen.getByTestId('action-call-1'))

      await waitFor(() => {
        expect(screen.getByTestId('row-error-1')).toBeInTheDocument()
        expect(screen.getByText('Network error')).toBeInTheDocument()
      })
    })

    it('shows generic error message when rejection is not an Error instance', async () => {
      const failingAction = {
        label: 'Call',
        icon: <PhoneIcon />,
        onClick: vi.fn().mockRejectedValue('string error'),
        testId: 'action-call-1',
      }

      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          rowActions={[failingAction]}
        />
      )

      await user.click(screen.getByTestId('action-call-1'))

      await waitFor(() => {
        expect(screen.getByTestId('row-error-1')).toBeInTheDocument()
        expect(screen.getByText('Action failed. Please try again.')).toBeInTheDocument()
      })
    })

    it('clears error when close button on inline error is clicked', async () => {
      const failingAction = {
        label: 'Call',
        icon: <PhoneIcon />,
        onClick: vi.fn().mockRejectedValue(new Error('Network error')),
        testId: 'action-call-1',
      }

      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          rowActions={[failingAction]}
        />
      )

      await user.click(screen.getByTestId('action-call-1'))

      await waitFor(() => {
        expect(screen.getByTestId('row-error-1')).toBeInTheDocument()
      })

      // Click the close button on the Alert
      const closeButton = within(screen.getByTestId('row-error-1')).getByRole('button')
      await user.click(closeButton)

      await waitFor(() => {
        expect(screen.queryByTestId('row-error-1')).not.toBeInTheDocument()
      })
    })

    it('does not show error row when action succeeds', async () => {
      const successAction = {
        label: 'Call',
        icon: <PhoneIcon />,
        onClick: vi.fn().mockResolvedValue(undefined),
        testId: 'action-call-1',
      }

      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          rowActions={[successAction]}
        />
      )

      await user.click(screen.getByTestId('action-call-1'))

      await waitFor(() => {
        expect(screen.queryByTestId('row-error-1')).not.toBeInTheDocument()
      })
    })

    it('disables row action buttons while action is pending', async () => {
      let resolveAction: () => void
      const pendingAction = {
        label: 'Call',
        icon: <PhoneIcon />,
        onClick: vi.fn().mockImplementation(
          () => new Promise<void>((resolve) => { resolveAction = resolve })
        ),
        testId: 'action-call-1',
      }

      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          rowActions={[pendingAction]}
        />
      )

      await user.click(screen.getByTestId('action-call-1'))

      // Button should be disabled while pending
      expect(screen.getByTestId('action-call-1')).toBeDisabled()

      // Resolve the action
      resolveAction!()

      await waitFor(() => {
        expect(screen.getByTestId('action-call-1')).not.toBeDisabled()
      })
    })
  })

  // -------------------------------------------------------------------------
  // Bulk partial failure summary
  // -------------------------------------------------------------------------

  describe('bulk partial failure summary', () => {
    it('shows "X succeeded, Y failed" message on partial bulk action failure', async () => {
      const partialBulkAction = {
        label: 'Suppress',
        onClick: vi.fn().mockResolvedValue({ successes: 3, failures: 2 } as BulkActionResult),
        testId: 'bulk-suppress',
      }

      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2), makeRow(3), makeRow(4), makeRow(5)]}
          total={5}
          selectedIds={[1, 2, 3, 4, 5]}
          onSelectionChange={vi.fn()}
          bulkActions={[partialBulkAction]}
        />
      )

      await user.click(screen.getByTestId('bulk-suppress'))

      await waitFor(() => {
        expect(screen.getByTestId('bulk-action-message')).toBeInTheDocument()
        expect(screen.getByText('3 succeeded, 2 failed')).toBeInTheDocument()
      })
    })

    it('does not show bulk message when all succeed (failures = 0)', async () => {
      const successBulkAction = {
        label: 'Suppress',
        onClick: vi.fn().mockResolvedValue({ successes: 3, failures: 0 } as BulkActionResult),
        testId: 'bulk-suppress',
      }

      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2), makeRow(3)]}
          total={3}
          selectedIds={[1, 2, 3]}
          onSelectionChange={vi.fn()}
          bulkActions={[successBulkAction]}
        />
      )

      await user.click(screen.getByTestId('bulk-suppress'))

      await waitFor(() => {
        expect(screen.queryByTestId('bulk-action-message')).not.toBeInTheDocument()
      })
    })

    it('shows error message when bulk action throws', async () => {
      const failingBulkAction = {
        label: 'Suppress',
        onClick: vi.fn().mockRejectedValue(new Error('Server error')),
        testId: 'bulk-suppress',
      }

      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          selectedIds={[1]}
          onSelectionChange={vi.fn()}
          bulkActions={[failingBulkAction]}
        />
      )

      await user.click(screen.getByTestId('bulk-suppress'))

      await waitFor(() => {
        expect(screen.getByTestId('bulk-action-message')).toBeInTheDocument()
        expect(screen.getByText('Server error')).toBeInTheDocument()
      })
    })

    it('clears selection after bulk action completes', async () => {
      const onSelectionChange = vi.fn()
      const bulkAction = {
        label: 'Suppress',
        onClick: vi.fn().mockResolvedValue({ successes: 2, failures: 0 } as BulkActionResult),
        testId: 'bulk-suppress',
      }

      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          selectedIds={[1, 2]}
          onSelectionChange={onSelectionChange}
          bulkActions={[bulkAction]}
        />
      )

      await user.click(screen.getByTestId('bulk-suppress'))

      await waitFor(() => {
        expect(onSelectionChange).toHaveBeenCalledWith([])
      })
    })

    it('dismisses bulk message when close button is clicked', async () => {
      const partialBulkAction = {
        label: 'Suppress',
        onClick: vi.fn().mockResolvedValue({ successes: 1, failures: 1 } as BulkActionResult),
        testId: 'bulk-suppress',
      }

      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={2}
          selectedIds={[1, 2]}
          onSelectionChange={vi.fn()}
          bulkActions={[partialBulkAction]}
        />
      )

      await user.click(screen.getByTestId('bulk-suppress'))

      await waitFor(() => {
        expect(screen.getByTestId('bulk-action-message')).toBeInTheDocument()
      })

      const closeButton = within(screen.getByTestId('bulk-action-message')).getByRole('button')
      await user.click(closeButton)

      await waitFor(() => {
        expect(screen.queryByTestId('bulk-action-message')).not.toBeInTheDocument()
      })
    })
  })

  // -------------------------------------------------------------------------
  // Row rendering
  // -------------------------------------------------------------------------

  describe('row rendering', () => {
    it('renders owner name from first and last name', () => {
      render(
        <QueueTable
          rows={[makeRow(1, { owner_first_name: 'John', owner_last_name: 'Doe' })]}
          total={1}
        />
      )

      expect(screen.getByTestId('row-name-1')).toHaveTextContent('John Doe')
    })

    it('renders "—" when owner name is missing', () => {
      render(
        <QueueTable
          rows={[makeRow(1, { owner_first_name: null, owner_last_name: null })]}
          total={1}
        />
      )

      expect(screen.getByTestId('row-name-1')).toHaveTextContent('—')
    })

    it('renders property address', () => {
      render(
        <QueueTable
          rows={[makeRow(1, { property_street: '123 Oak Ave', property_city: 'Chicago', property_state: 'IL' })]}
          total={1}
        />
      )

      expect(screen.getByTestId('row-address-1')).toHaveTextContent('123 Oak Ave, Chicago, IL')
    })

    it('renders lead score', () => {
      render(
        <QueueTable
          rows={[makeRow(1, { lead_score: 85 })]}
          total={1}
        />
      )

      expect(screen.getByTestId('row-score-1')).toHaveTextContent('85')
    })

    it('renders lead status', () => {
      render(
        <QueueTable
          rows={[makeRow(1, { lead_status: 'follow_up' })]}
          total={1}
        />
      )

      expect(screen.getByTestId('row-status-1')).toHaveTextContent('follow_up')
    })

    it('renders total count', () => {
      render(
        <QueueTable
          rows={[makeRow(1), makeRow(2)]}
          total={42}
        />
      )

      expect(screen.getByTestId('queue-table-total')).toHaveTextContent('42 total')
    })

    it('renders extra columns', () => {
      const extraColumns = [
        {
          key: 'days_overdue',
          label: 'Days Overdue',
          render: (row: QueueRow) => <span data-testid={`extra-${row.id}`}>5 days</span>,
        },
      ]

      render(
        <QueueTable
          rows={[makeRow(1)]}
          total={1}
          extraColumns={extraColumns}
        />
      )

      expect(screen.getByText('Days Overdue')).toBeInTheDocument()
      expect(screen.getByTestId('extra-1')).toHaveTextContent('5 days')
    })
  })
})
