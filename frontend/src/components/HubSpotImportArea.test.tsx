/**
 * Tests for HubSpotImportArea component
 *
 * Covers:
 * - config save: renders token input, calls saveHubSpotConfig on submit, shows success state
 * - test connection: calls testHubSpotConnection, displays account name/portal ID on success, displays error on failure
 * - trigger import: calls triggerHubSpotImport with selected object types, shows progress indicator
 * - progress display: SSE events update progress bar per object type
 * - import history: renders HubSpotImportRun list with status badges and counts
 * - Read-Only Mode badge visible when config present
 * - Review Queue badge shows pending count
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { HubSpotImportArea } from './HubSpotImportArea'
import { hubSpotService } from '@/services/api'
import type { HubSpotConfig, HubSpotImportRun } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  hubSpotService: {
    getHubSpotConfig: vi.fn(),
    saveHubSpotConfig: vi.fn(),
    testHubSpotConnection: vi.fn(),
    triggerHubSpotImport: vi.fn(),
    listImportRuns: vi.fn(),
    getImportRun: vi.fn(),
    getReviewQueue: vi.fn(),
    confirmMatch: vi.fn(),
    rejectMatch: vi.fn(),
    markMatchAsNewRecord: vi.fn(),
    triggerBackupExport: vi.fn(),
    downloadBackupExport: vi.fn(),
    getPipelineStatus: vi.fn(),
    getWebhookLog: vi.fn(),
    getWebhookLogSummary: vi.fn(),
    retryWebhookEvent: vi.fn(),
    saveClientSecret: vi.fn(),
  },
}))

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { is_admin: true } }),
}))

// ---------------------------------------------------------------------------
// Mock EventSource for SSE tests
// ---------------------------------------------------------------------------

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readyState = 1

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  close() {
    this.readyState = 2
  }

  // Helper to simulate receiving a message
  simulateMessage(data: object) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) } as MessageEvent)
    }
  }

  // Helper to simulate an error
  simulateError() {
    if (this.onerror) {
      this.onerror(new Event('error'))
    }
  }
}

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockConfig: HubSpotConfig = {
  id: 1,
  portal_id: '12345',
  account_name: 'Test Account',
  configured: true,
}

const mockRuns: HubSpotImportRun[] = [
  {
    id: 1,
    object_type: 'deals',
    status: 'success',
    start_time: '2024-01-01T10:00:00Z',
    end_time: '2024-01-01T10:05:00Z',
    total_fetched: 100,
    created_count: 80,
    updated_count: 20,
    skipped_count: 0,
    error_count: 0,
    error_message: null,
  },
  {
    id: 2,
    object_type: 'contacts',
    status: 'failed',
    start_time: '2024-01-01T10:00:00Z',
    end_time: '2024-01-01T10:02:00Z',
    total_fetched: 50,
    created_count: 30,
    updated_count: 10,
    skipped_count: 0,
    error_count: 10,
    error_message: 'Rate limit exceeded',
  },
]

const user = userEvent.setup({ pointerEventsCheck: 0 })

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
  MockEventSource.instances = []
  // @ts-ignore
  global.EventSource = MockEventSource

  // Default: no config, empty runs, empty review queue
  vi.mocked(hubSpotService.getHubSpotConfig).mockRejectedValue(new Error('Not configured'))
  vi.mocked(hubSpotService.listImportRuns).mockResolvedValue({
    runs: [],
    total: 0,
    page: 1,
    per_page: 20,
  })
  vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
    matches: [],
    total: 0,
    page: 1,
    per_page: 1,
  })
  // Pipeline status — non-critical, always return idle so the context query
  // resolves immediately and doesn't trigger unguarded state updates in tests.
  vi.mocked(hubSpotService.getPipelineStatus).mockResolvedValue({
    pipeline_running: false,
    matches: { total: 0, high: 0, medium: 0, unmatched: 0 },
    interactions: 0,
    tasks: 0,
    signals: 0,
  })
  // Webhook panel calls — return empty data so sub-component queries settle cleanly
  vi.mocked(hubSpotService.getWebhookLog).mockResolvedValue({
    logs: [],
    total: 0,
    page: 1,
    pages: 1,
    per_page: 20,
  })
  vi.mocked(hubSpotService.getWebhookLogSummary).mockResolvedValue({
    processed_count: 0,
    failed_count: 0,
    deduplicated_count: 0,
    last_synced_at: null,
  })
})

afterEach(() => {
  // @ts-ignore
  delete global.EventSource
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('HubSpotImportArea', () => {
  describe('config save', () => {
    it('renders the token input field', async () => {
      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('HubSpot private app token')).toBeInTheDocument()
      })
    })

    it('calls saveHubSpotConfig on form submit with token value', async () => {
      vi.mocked(hubSpotService.saveHubSpotConfig).mockResolvedValue(mockConfig)

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('HubSpot private app token')).toBeInTheDocument()
      })

      const tokenInput = screen.getByLabelText('HubSpot private app token')
      await user.type(tokenInput, 'pat-na1-test-token')

      const saveButton = screen.getByRole('button', { name: /save token/i })
      await user.click(saveButton)

      await waitFor(() => {
        expect(hubSpotService.saveHubSpotConfig).toHaveBeenCalledWith(
          'pat-na1-test-token',
          undefined
        )
      })
    })

    it('shows success state after saving token', async () => {
      vi.mocked(hubSpotService.saveHubSpotConfig).mockResolvedValue(mockConfig)

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('HubSpot private app token')).toBeInTheDocument()
      })

      const tokenInput = screen.getByLabelText('HubSpot private app token')
      await user.type(tokenInput, 'pat-na1-test-token')

      const saveButton = screen.getByRole('button', { name: /save token/i })
      await user.click(saveButton)

      await waitFor(() => {
        expect(screen.getByText('Token saved successfully.')).toBeInTheDocument()
      })
    })

    it('disables save button when token input is empty', async () => {
      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /save token/i })).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: /save token/i })).toBeDisabled()
    })
  })

  describe('test connection', () => {
    it('calls testHubSpotConnection when Test Connection button is clicked', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.testHubSpotConnection).mockResolvedValue({
        success: true,
        account_name: 'Test Account',
        portal_id: '12345',
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /test connection/i })).toBeEnabled()
      })

      await user.click(screen.getByRole('button', { name: /test connection/i }))

      await waitFor(() => {
        expect(hubSpotService.testHubSpotConnection).toHaveBeenCalledOnce()
      })
    })

    it('displays account name and portal ID on successful connection test', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.testHubSpotConnection).mockResolvedValue({
        success: true,
        account_name: 'My HubSpot Account',
        portal_id: '99999',
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /test connection/i })).toBeEnabled()
      })

      await user.click(screen.getByRole('button', { name: /test connection/i }))

      await waitFor(() => {
        expect(screen.getByText(/My HubSpot Account/)).toBeInTheDocument()
        expect(screen.getByText(/Portal 99999/)).toBeInTheDocument()
      })
    })

    it('displays error message on failed connection test', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.testHubSpotConnection).mockRejectedValue(
        new Error('Invalid API token')
      )

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /test connection/i })).toBeEnabled()
      })

      await user.click(screen.getByRole('button', { name: /test connection/i }))

      await waitFor(() => {
        expect(screen.getByText('Invalid API token')).toBeInTheDocument()
      })
    })
  })

  describe('trigger import', () => {
    it('calls triggerHubSpotImport with selected object types', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.triggerHubSpotImport).mockResolvedValue({
        run_ids: [42],
        status: 'running',
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('Start HubSpot import')).toBeEnabled()
      })

      await user.click(screen.getByLabelText('Start HubSpot import'))

      await waitFor(() => {
        expect(hubSpotService.triggerHubSpotImport).toHaveBeenCalledWith(
          expect.arrayContaining(['deals', 'contacts', 'companies', 'engagements'])
        )
      })
    })

    it('calls triggerHubSpotImport with only selected types when some are unchecked', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.triggerHubSpotImport).mockResolvedValue({
        run_ids: [43],
        status: 'running',
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('Start HubSpot import')).toBeEnabled()
      })

      // Uncheck "Companies" and "Engagements"
      const companiesCheckbox = screen.getByRole('checkbox', { name: /companies/i })
      const engagementsCheckbox = screen.getByRole('checkbox', { name: /engagements/i })
      await user.click(companiesCheckbox)
      await user.click(engagementsCheckbox)

      await user.click(screen.getByLabelText('Start HubSpot import'))

      await waitFor(() => {
        expect(hubSpotService.triggerHubSpotImport).toHaveBeenCalledWith(
          expect.arrayContaining(['deals', 'contacts'])
        )
        const callArgs = vi.mocked(hubSpotService.triggerHubSpotImport).mock.calls[0][0]
        expect(callArgs).not.toContain('companies')
        expect(callArgs).not.toContain('engagements')
      })
    })

    it('shows progress indicator after import is triggered', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.triggerHubSpotImport).mockResolvedValue({
        run_ids: [44],
        status: 'running',
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('Start HubSpot import')).toBeEnabled()
      })

      await user.click(screen.getByLabelText('Start HubSpot import'))

      // Simulate SSE progress event
      await waitFor(() => {
        expect(MockEventSource.instances.length).toBeGreaterThan(0)
      })

      const es = MockEventSource.instances[MockEventSource.instances.length - 1]
      es.simulateMessage({
        object_type: 'deals',
        total_fetched: 100,
        created_count: 50,
        updated_count: 10,
        error_count: 0,
        status: 'running',
        percent: 60,
      })

      await waitFor(() => {
        expect(screen.getByText(/Import Progress/i)).toBeInTheDocument()
      })
    })
  })

  describe('progress display', () => {
    it('updates progress bar per object type from SSE events', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.triggerHubSpotImport).mockResolvedValue({
        run_ids: [45],
        status: 'running',
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('Start HubSpot import')).toBeEnabled()
      })

      await user.click(screen.getByLabelText('Start HubSpot import'))

      await waitFor(() => {
        expect(MockEventSource.instances.length).toBeGreaterThan(0)
      })

      const es = MockEventSource.instances[MockEventSource.instances.length - 1]

      // Simulate progress for deals
      es.simulateMessage({
        object_type: 'deals',
        total_fetched: 200,
        created_count: 100,
        updated_count: 50,
        error_count: 0,
        status: 'running',
        percent: 75,
      })

      await waitFor(() => {
        expect(screen.getByLabelText('deals import progress 75%')).toBeInTheDocument()
      })

      // Simulate progress for contacts
      es.simulateMessage({
        object_type: 'contacts',
        total_fetched: 50,
        created_count: 25,
        updated_count: 5,
        error_count: 0,
        status: 'success',
        percent: 100,
      })

      await waitFor(() => {
        expect(screen.getByLabelText('contacts import progress 100%')).toBeInTheDocument()
      })
    })
  })

  describe('import history', () => {
    it('renders HubSpotImportRun list with status badges and counts', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.listImportRuns).mockResolvedValue({
        runs: mockRuns,
        total: 2,
        page: 1,
        per_page: 20,
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByText('deals')).toBeInTheDocument()
        expect(screen.getByText('contacts')).toBeInTheDocument()
      })

      // Check status badges
      expect(screen.getByLabelText('Status: success')).toBeInTheDocument()
      expect(screen.getByLabelText('Status: failed')).toBeInTheDocument()

      // Check counts
      expect(screen.getByText('100')).toBeInTheDocument() // total_fetched for deals
      expect(screen.getByText('80')).toBeInTheDocument()  // created_count for deals
    })

    it('shows "No import runs yet" when history is empty', async () => {
      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByText('No import runs yet.')).toBeInTheDocument()
      })
    })
  })

  describe('Read-Only Mode badge', () => {
    it('shows Read-Only Mode badge when configured without write-back', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue({
        ...mockConfig,
        write_back_enabled: false,
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('HubSpot connection is read-only')).toBeInTheDocument()
      })
    })

    it('shows Write-back enabled badge when write-back is on', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue({
        ...mockConfig,
        write_back_enabled: true,
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.getByLabelText('HubSpot write-back is enabled')).toBeInTheDocument()
        expect(screen.queryByLabelText('HubSpot connection is read-only')).not.toBeInTheDocument()
      })
    })

    it('does not show connection badge when config is absent', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockRejectedValue(new Error('Not configured'))

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(screen.queryByLabelText('HubSpot connection is read-only')).not.toBeInTheDocument()
      })
    })
  })

  describe('Review Queue badge', () => {
    it('shows Review Queue badge with pending count when there are pending items', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
        matches: [],
        total: 7,
        page: 1,
        per_page: 1,
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        expect(
          screen.getByLabelText('Review queue has 7 pending items')
        ).toBeInTheDocument()
      })
    })

    it('does not show Review Queue badge when pending count is 0', async () => {
      vi.mocked(hubSpotService.getHubSpotConfig).mockResolvedValue(mockConfig)
      vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
        matches: [],
        total: 0,
        page: 1,
        per_page: 1,
      })

      render(<HubSpotImportArea />)

      await waitFor(() => {
        // Wait for queries to settle
        expect(screen.queryByLabelText(/Review queue has/)).not.toBeInTheDocument()
      })
    })
  })
})
