import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ReadyToMailQueue } from './ReadyToMailQueue'
import { queueService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'

vi.mock('@/services/api', () => ({
  queueService: {
    getMailCandidates: vi.fn(),
  },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {
    getQueue: vi.fn(),
    getConfig: vi.fn(),
    listCampaigns: vi.fn(),
  },
}))

vi.mock('./MailCampaignsPanel', () => ({
  MailCampaignsPanel: () => <div data-testid="mail-campaigns-panel">Recent sends</div>,
}))

const emptyCandidates = {
  rows: [{
    id: 20,
    owner_first_name: 'John',
    owner_last_name: 'Smith',
    property_street: '456 Oak Ave',
    property_city: 'Evanston',
    property_state: 'IL',
    lead_score: 72,
    lead_status: 'mailing_no_contact_made',
    recommended_action: 'mail_ready',
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
    last_mailed_at: '2024-08-01T15:00:00Z',
    last_sale_at: '2010-06-15',
  }],
  total: 1,
  page: 1,
  per_page: 20,
}

const queueSummary = {
  queued_count: 2,
  batch_minimum: 50,
  allow_send_below_minimum: false,
  can_send: false,
  estimated_cost_per_piece: 1.25,
  estimated_total: 2.5,
  items: [
    {
      id: 1,
      lead_id: 10,
      user_id: 'test-user',
      status: 'queued',
      owner_name: 'Jane Doe',
      property_street: '123 Main St',
      mailing_address: '123 Main St',
      mailing_city: 'Chicago',
      mailing_state: 'IL',
      mailing_zip: '60601',
      created_at: '2026-07-01T12:00:00Z',
      last_mailed_at: '2025-11-15T10:00:00Z',
      last_sale_at: '2025-04-11',
    },
  ],
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReadyToMailQueue />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(openLetterService.getConfig).mockResolvedValue({
    configured: true,
    token_source: 'environment',
    uses_env_token: true,
    requires_user_api_token: false,
    default_product_id: 1,
    default_template_id: 371,
  })
  vi.mocked(queueService.getMailCandidates).mockResolvedValue(emptyCandidates)
})

describe('ReadyToMailQueue', () => {
  it('renders batch summary and staged table when queue loads', async () => {
    vi.mocked(openLetterService.getQueue).mockResolvedValue(queueSummary)

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('ready-to-mail-queue')).toBeInTheDocument()
    })
    expect(screen.getByTestId('mail-batch-summary')).toBeInTheDocument()
    expect(screen.getByTestId('mail-queue-staged-table')).toBeInTheDocument()
    expect(screen.getByText('123 Main St')).toBeInTheDocument()
    expect(screen.getByText('11/15/2025')).toBeInTheDocument()
    expect(screen.getByText('4/11/2025')).toBeInTheDocument()
  })

  it('shows last mailed on recommended candidates', async () => {
    vi.mocked(openLetterService.getQueue).mockResolvedValue({
      ...queueSummary,
      items: [],
      queued_count: 0,
    })

    renderPage()

    await waitFor(() => {
      expect(screen.getAllByText('Last mailed').length).toBeGreaterThanOrEqual(1)
    })
    expect(screen.getByText('8/1/2024')).toBeInTheDocument()
    expect(screen.getByText('6/15/2010')).toBeInTheDocument()
  })

  it('shows API error message and still renders recommended section', async () => {
    vi.mocked(openLetterService.getQueue).mockRejectedValue(
      new Error('Network error. Please check your connection.'),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('mail-queue-error')).toBeInTheDocument()
    })
    expect(screen.getByText('Network error. Please check your connection.')).toBeInTheDocument()
    expect(screen.getByText('Recommended for mail')).toBeInTheDocument()
    expect(screen.getByTestId('mail-campaigns-panel')).toBeInTheDocument()
  })

  it('retry button refetches the mail queue', async () => {
    vi.mocked(openLetterService.getQueue)
      .mockRejectedValueOnce(new Error('Internal server error'))
      .mockResolvedValueOnce(queueSummary)

    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('mail-queue-error')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => {
      expect(screen.getByTestId('mail-batch-summary')).toBeInTheDocument()
    })
    expect(openLetterService.getQueue).toHaveBeenCalledTimes(2)
  })
})
