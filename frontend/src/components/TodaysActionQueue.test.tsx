import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { TodaysActionQueue } from './TodaysActionQueue'
import { queueService, leadTaskService } from '@/services/api'
import type { LeadStatus } from '@/types'

vi.mock('@/services/api', () => ({
  queueService: { getTodaysAction: vi.fn() },
  leadTaskService: { createTask: vi.fn() },
}))

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

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
      <MemoryRouter initialEntries={['/queues/todays-action']}>
        <Routes>
          <Route path="/queues/todays-action" element={<TodaysActionQueue />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('TodaysActionQueue', () => {
  it('fetches with page=1 on mount', async () => {
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5))

    renderComponent()

    await waitFor(() => {
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20)
    })
  })

  it('renders pagination controls when total > per_page', async () => {
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(41, 20))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('queue-pagination')).toBeInTheDocument()
    })
  })

  it('does not render pagination when total <= per_page', async () => {
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(15, 20))

    renderComponent()

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

  it('Log Call navigates to lead detail with log=call deep link', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('action-log-call')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('action-log-call'))

    expect(mockNavigate).toHaveBeenCalledWith('/leads/1?log=call')
  })

  it('Log Note navigates to lead detail with log=note deep link', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('action-log-note')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('action-log-note'))

    expect(mockNavigate).toHaveBeenCalledWith('/leads/1?log=note')
  })

  it('Create Task calls API and refetches queue', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(41, 20))
    vi.mocked(leadTaskService.createTask).mockResolvedValue(undefined as never)

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('action-create-task')).toBeInTheDocument()
    })

    vi.mocked(queueService.getTodaysAction).mockClear()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(41, 20))

    await user.click(screen.getByTestId('action-create-task'))

    await waitFor(() => {
      expect(leadTaskService.createTask).toHaveBeenCalledWith(1, {
        title: 'Follow up',
        task_type: 'call_owner_today',
      })
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20)
    })
  })
})
