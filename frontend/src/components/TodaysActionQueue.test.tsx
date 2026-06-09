import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { TodaysActionQueue } from './TodaysActionQueue'
import { queueService, callLogService } from '@/services/api'
import type { LeadStatus } from '@/types'

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  queueService: { getTodaysAction: vi.fn() },
  callLogService: { logCall: vi.fn(), logNote: vi.fn() },
  leadTaskService: { createTask: vi.fn() },
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeQueuePage(total: number, perPage = 20, page = 1) {
  return {
    rows: [
      {
        id: 1,
        owner_first_name: 'A',
        owner_last_name: 'B',
        property_street: '1 St',
        property_city: 'C',
        property_state: 'IL',
        lead_score: 50,
        lead_status: 'mailing_no_contact_made' as LeadStatus,
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
      },
    ],
    total,
    page,
    per_page: perPage,
  }
}

function makeEmptyPage() {
  return { rows: [], total: 0, page: 1, per_page: 20 }
}

function renderComponent() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TodaysActionQueue />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TodaysActionQueue', () => {
  it('fetches with page=1 on mount', async () => {
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5))

    renderComponent()

    await waitFor(() => {
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20)
    })
  })

  it('renders pagination controls when total > per_page', async () => {
    // 41 leads with per_page=20 → 3 pages → pagination should appear
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(41, 20))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('queue-pagination')).toBeInTheDocument()
    })
  })

  it('does not render pagination when total <= per_page', async () => {
    // 15 leads with per_page=20 → 1 page → no pagination
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(15, 20))

    renderComponent()

    // Wait for the table to appear first so we know data loaded
    await waitFor(() => {
      expect(screen.getByTestId('queue-table')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('queue-pagination')).not.toBeInTheDocument()
  })

  it('does not render the table in empty state', async () => {
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeEmptyPage())

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('todays-action-empty')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('queue-table')).not.toBeInTheDocument()
  })

  it('successful Log Call action eventually refetches with page=1', async () => {
    const user = userEvent.setup()

    // First call returns 2 pages so pagination is visible
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(41, 20))
    vi.mocked(callLogService.logCall).mockResolvedValue(undefined as any)

    renderComponent()

    // Wait for the data to load and the action button to appear
    await waitFor(() => {
      expect(screen.getByTestId('action-log-call')).toBeInTheDocument()
    })

    // Clear the call count so we can check fresh calls after the action
    vi.mocked(queueService.getTodaysAction).mockClear()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(41, 20))

    // Click the Log Call action
    await user.click(screen.getByTestId('action-log-call'))

    // After the action the component calls setPage(1) and invalidates the query,
    // which triggers a refetch with page=1
    await waitFor(() => {
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20)
    })
  })

  it('failed Log Call action does not reset page or trigger a new page-1 fetch', async () => {
    const user = userEvent.setup()

    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(41, 20))
    vi.mocked(callLogService.logCall).mockRejectedValue(new Error('Network error'))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('action-log-call')).toBeInTheDocument()
    })

    // Clear mock so we can observe any subsequent calls
    vi.mocked(queueService.getTodaysAction).mockClear()

    // Click the Log Call action — it should throw
    await user.click(screen.getByTestId('action-log-call'))

    // Wait for the error to surface in the UI
    await waitFor(() => {
      expect(screen.getByTestId('row-error-1')).toBeInTheDocument()
    })

    // The service should NOT have been called again because the action failed
    // before reaching setPage(1) / invalidateQueries
    expect(queueService.getTodaysAction).not.toHaveBeenCalled()

    // The pagination should still be visible (page was not reset)
    expect(screen.getByTestId('queue-pagination')).toBeInTheDocument()
  })
})

