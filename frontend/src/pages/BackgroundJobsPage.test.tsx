import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import BackgroundJobsPage from './BackgroundJobsPage'

vi.mock('@/services/adminApi', () => ({
  adminService: {
    getBackgroundJobs: vi.fn(),
  },
}))

import { adminService } from '@/services/adminApi'

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BackgroundJobsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('BackgroundJobsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows idle state when no jobs', async () => {
    vi.mocked(adminService.getBackgroundJobs).mockResolvedValue({
      celery_inspect_ok: true,
      active: [],
      reserved: [],
      scheduled: [],
      queued: [],
      queue_depth: 0,
      hubspot_pipeline: {
        stage: 'idle',
        stage_index: 0,
        stage_total: 8,
        label: 'Idle',
        updated_at: null,
        pipeline_running: false,
      },
      mail_campaigns_in_flight: [],
      busy: false,
    })
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('bg-jobs-idle')).toBeInTheDocument()
    })
  })

  it('highlights HubSpot stage and mail submit in the queue', async () => {
    vi.mocked(adminService.getBackgroundJobs).mockResolvedValue({
      celery_inspect_ok: true,
      active: [{
        id: 'a1',
        name: 'hubspot.post_import_pipeline',
        args: [],
        kwargs: {},
        state: 'active',
        worker: 'w1',
        time_start: null,
        is_mail_submit: false,
        is_hubspot_pipeline: true,
      }],
      reserved: [{
        id: 'r1',
        name: 'open_letter.submit_campaign',
        args: [1],
        kwargs: {},
        state: 'reserved',
        worker: 'w1',
        time_start: null,
        is_mail_submit: true,
        is_hubspot_pipeline: false,
      }],
      scheduled: [],
      queued: [],
      queue_depth: 0,
      hubspot_pipeline: {
        stage: 'enrich',
        stage_index: 2,
        stage_total: 7,
        label: 'Enriching leads',
        updated_at: null,
        pipeline_running: true,
      },
      mail_campaigns_in_flight: [{
        id: 1,
        status: 'pending',
        lead_count: 506,
        olc_order_id: null,
        created_at: '2026-07-22T13:45:57Z',
        created_by: 'u1',
        error_message: null,
        orphan: true,
      }],
      busy: true,
    })
    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('bg-jobs-hubspot-stage')).toHaveTextContent('Enriching leads')
      expect(screen.getByText('Direct mail')).toBeInTheDocument()
      expect(screen.getByText('HubSpot pipeline')).toBeInTheDocument()
      expect(screen.getByText('#1')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Re-queue' })).toBeInTheDocument()
    })
  })

  it('hides Re-queue when Celery inspect failed', async () => {
    vi.mocked(adminService.getBackgroundJobs).mockResolvedValue({
      celery_inspect_ok: false,
      active: [],
      reserved: [],
      scheduled: [],
      queued: [],
      queue_depth: 0,
      hubspot_pipeline: {
        stage: 'idle',
        stage_index: 0,
        stage_total: 7,
        label: 'Idle',
        updated_at: null,
        pipeline_running: false,
      },
      mail_campaigns_in_flight: [{
        id: 2,
        status: 'pending',
        lead_count: 10,
        olc_order_id: null,
        created_at: null,
        created_by: 'u1',
        error_message: null,
        orphan: false,
      }],
      busy: true,
    })
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('#2')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: 'Re-queue' })).not.toBeInTheDocument()
  })
})
