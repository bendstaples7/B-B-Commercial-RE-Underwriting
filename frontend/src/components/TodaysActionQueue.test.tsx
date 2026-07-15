import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { TodaysActionQueue } from './TodaysActionQueue'
import { queueService, leadTaskService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import type { LeadStatus } from '@/types'

vi.mock('@/services/api', () => ({
  queueService: {
    getTodaysAction: vi.fn(),
    getTodaysActionOutreachCounts: vi.fn(),
    getTodaysActionLeadIds: vi.fn(),
  },
  leadTaskService: { createTask: vi.fn() },
  bulkActionService: { bulkCreateTask: vi.fn() },
  commandCenterService: { reactivate: vi.fn(), suppress: vi.fn() },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {
    enqueue: vi.fn(),
  },
}))

const mockNavigate = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

function makeQueuePage(total: number, perPage = 20, page = 1, rowCount = 1) {
  const baseRow = {
    owner_first_name: 'A',
    owner_last_name: 'B',
    property_street: '1 St',
    property_city: 'C',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made' as LeadStatus,
    recommended_action: 'mail_ready' as const,
    recommended_contact_method: 'direct_mail' as const,
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
  }
  const rows = Array.from({ length: rowCount }, (_, i) => ({
    ...baseRow,
    id: i + 1,
    owner_first_name: String.fromCharCode(65 + i),
    property_street: `${i + 1} St`,
  }))
  return {
    rows,
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
  vi.mocked(queueService.getTodaysActionOutreachCounts).mockResolvedValue({
    all: 5,
    direct_mail: 2,
    call_now: 1,
    email_now: 0,
    text_now: 0,
  })
})

describe('TodaysActionQueue', () => {
  it('shows loading state instead of empty copy while the first fetch is in flight', async () => {
    let resolveFetch: (value: ReturnType<typeof makeQueuePage>) => void = () => {}
    vi.mocked(queueService.getTodaysAction).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve
        }),
    )

    renderComponent()

    expect(await screen.findByTestId('queue-loading')).toBeInTheDocument()
    expect(screen.getByLabelText('Loading queue')).toBeInTheDocument()
    expect(screen.queryByTestId('todays-action-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('todays-action-total')).toHaveTextContent('—')

    resolveFetch(makeQueuePage(5))

    await waitFor(() => {
      expect(screen.getByTestId('queue-table')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('queue-loading')).not.toBeInTheDocument()
    expect(screen.getByTestId('todays-action-total')).toHaveTextContent('5')
  })

  it('keeps prior rows visible while next-action filter refetch is in flight', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(2, 20, 1, 2))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('queue-table')).toBeInTheDocument()
    })

    let resolveFilter: (value: ReturnType<typeof makeEmptyPage>) => void = () => {}
    vi.mocked(queueService.getTodaysAction).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFilter = resolve
        }),
    )

    await user.click(screen.getByLabelText('Next action'))
    await user.click(await screen.findByText('Email Now (0)'))

    await waitFor(() => {
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20, 'email_now')
    })

    expect(screen.getByTestId('queue-table')).toBeInTheDocument()
    expect(screen.getByTestId('queue-table')).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByTestId('row-action-view-1')).toBeDisabled()
    expect(screen.queryByTestId('todays-action-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('todays-action-total')).toHaveTextContent('—')

    resolveFilter(makeEmptyPage())

    await waitFor(() => {
      expect(screen.getByTestId('todays-action-empty')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('queue-table')).not.toBeInTheDocument()
  })

  it('fetches with page=1 on mount', async () => {
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5))

    renderComponent()

    await waitFor(() => {
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20, null)
    })
  })

  it('renders next-action filter and selects all Direct Mail leads', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(2, 20, 1, 2))
    vi.mocked(queueService.getTodaysActionLeadIds).mockResolvedValue({
      lead_ids: [1, 2],
      total: 2,
      outreach: 'direct_mail',
    })

    renderComponent()

    await waitFor(() => {
      expect(screen.getByLabelText('Next action')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Next action'))
    await user.click(await screen.findByText('Direct Mail (2)'))

    await waitFor(() => {
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20, 'direct_mail')
    })

    await user.click(screen.getByTestId('todays-action-select-all-matching'))

    await waitFor(() => {
      expect(queueService.getTodaysActionLeadIds).toHaveBeenCalledWith('direct_mail')
      expect(screen.getByTestId('bulk-action-bar')).toBeInTheDocument()
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

  it('renders selection checkboxes and bulk add-to-mail-batch action', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5, 20, 1, 2))
    vi.mocked(openLetterService.enqueue).mockResolvedValue({
      added: 2,
      skipped: 0,
      invalid: 0,
      queued_count: 2,
      batch_minimum: 50,
      allow_send_below_minimum: false,
      can_send: false,
      items: [],
    })

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('queue-table')).toBeInTheDocument()
    })

    expect(screen.getByTestId('select-all-checkbox')).toBeInTheDocument()

    await user.click(screen.getByTestId('select-all-checkbox'))

    await waitFor(() => {
      expect(screen.getByTestId('bulk-action-bar')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('add-to-batch-bulk-action'))

    await waitFor(() => {
      expect(openLetterService.enqueue).toHaveBeenCalledWith(
        [1, 2],
        'queue-todays-action',
      )
    })
  })

  it('Log Call navigates to lead detail with log=call deep link', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('action-log-call')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('action-log-call'))

    expect(mockNavigate).toHaveBeenCalledWith('/leads/1?log=call&queue=todays-action', {
      state: { fromQueue: { key: 'todays-action', label: "Today's Action" } },
    })
  })

  it('Log Note navigates to lead detail with log=note deep link', async () => {
    const user = userEvent.setup()
    vi.mocked(queueService.getTodaysAction).mockResolvedValue(makeQueuePage(5))

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('action-log-note')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('action-log-note'))

    expect(mockNavigate).toHaveBeenCalledWith('/leads/1?log=note&queue=todays-action', {
      state: { fromQueue: { key: 'todays-action', label: "Today's Action" } },
    })
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
        task_type: 'add_to_mail_batch',
      })
      expect(queueService.getTodaysAction).toHaveBeenCalledWith(1, 20, null)
    })
  })
})
