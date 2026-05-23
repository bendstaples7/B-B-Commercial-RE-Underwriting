/**
 * Tests for WebhookSyncPanel component
 *
 * Covers:
 * 1. Webhook URL display — shows the correct URL
 * 2. Client secret configured indicator — shows "Configured ✓" when hasClientSecret=true
 * 3. Retry action — clicking Retry on a failed row calls retryWebhookEvent
 * 4. Stale sync warning — shows warning when last_synced_at is more than 24 hours ago
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { WebhookSyncPanel } from './WebhookSyncPanel'
import { hubSpotService } from '@/services/api'
import type { WebhookLogListResponse, WebhookLogSummary } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  hubSpotService: {
    getWebhookLog: vi.fn(),
    getWebhookLogSummary: vi.fn(),
    retryWebhookEvent: vi.fn(),
    saveHubSpotConfigWithSecret: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const emptyLogResponse: WebhookLogListResponse = {
  logs: [],
  total: 0,
  page: 1,
  per_page: 10,
  pages: 0,
}

const logResponseWithFailedRow: WebhookLogListResponse = {
  logs: [
    {
      id: 42,
      hubspot_object_type: 'deal',
      hubspot_object_id: '12345',
      event_type: 'deal.propertyChange',
      status: 'failed',
      error_message: 'API timeout',
      received_at: new Date().toISOString(),
      processed_at: null,
    },
    {
      id: 43,
      hubspot_object_type: 'contact',
      hubspot_object_id: '67890',
      event_type: 'contact.creation',
      status: 'processed',
      error_message: null,
      received_at: new Date().toISOString(),
      processed_at: new Date().toISOString(),
    },
  ],
  total: 2,
  page: 1,
  per_page: 10,
  pages: 1,
}

const recentSummary: WebhookLogSummary = {
  processed_count: 10,
  failed_count: 1,
  deduplicated_count: 2,
  last_synced_at: new Date().toISOString(), // just now — not stale
}

const staleSummary: WebhookLogSummary = {
  processed_count: 5,
  failed_count: 0,
  deduplicated_count: 0,
  last_synced_at: new Date(Date.now() - 25 * 60 * 60 * 1000).toISOString(), // 25 hours ago
}

const noSyncSummary: WebhookLogSummary = {
  processed_count: 0,
  failed_count: 0,
  deduplicated_count: 0,
  last_synced_at: null,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const mockedHubSpotService = vi.mocked(hubSpotService)

function setupDefaultMocks() {
  mockedHubSpotService.getWebhookLog.mockResolvedValue(emptyLogResponse)
  mockedHubSpotService.getWebhookLogSummary.mockResolvedValue(recentSummary)
  mockedHubSpotService.retryWebhookEvent.mockResolvedValue({ success: true })
  mockedHubSpotService.saveHubSpotConfigWithSecret.mockResolvedValue({
    configured: true,
    has_client_secret: true,
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('WebhookSyncPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupDefaultMocks()
  })

  // ── Test 1: Webhook URL display ──────────────────────────────────────────

  describe('Webhook URL display', () => {
    it('shows the correct webhook URL', async () => {
      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      // Use data-testid to avoid ambiguity with the heading text
      const urlField = await screen.findByTestId('webhook-url-field')
      expect(urlField).toBeInTheDocument()
      expect((urlField as HTMLInputElement).value).toContain('/api/hubspot/webhook')
    })

    it('renders the webhook URL section heading', async () => {
      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      expect(await screen.findByText('Webhook URL')).toBeInTheDocument()
    })
  })

  // ── Test 2: Client secret configured indicator ───────────────────────────

  describe('Client secret configured indicator', () => {
    it('shows "Configured ✓" chip when hasClientSecret is true', async () => {
      render(
        <WebhookSyncPanel
          hasClientSecret={true}
          onClientSecretSaved={vi.fn()}
        />
      )

      expect(await screen.findByText('Configured ✓')).toBeInTheDocument()
    })

    it('does not show "Configured ✓" chip when hasClientSecret is false', async () => {
      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      // Wait for component to settle
      await screen.findByText('Webhook URL')
      expect(screen.queryByText('Configured ✓')).not.toBeInTheDocument()
    })

    it('shows the client secret input field', async () => {
      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      expect(await screen.findByLabelText('HubSpot client secret')).toBeInTheDocument()
    })
  })

  // ── Test 3: Retry action ─────────────────────────────────────────────────

  describe('Retry action', () => {
    it('shows Retry button only for failed rows', async () => {
      mockedHubSpotService.getWebhookLog.mockResolvedValue(logResponseWithFailedRow)

      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      // Wait for the Retry button to appear (only for the failed row)
      const retryBtn = await screen.findByTestId('retry-btn-42')
      expect(retryBtn).toBeInTheDocument()

      // The processed row should NOT have a retry button
      expect(screen.queryByTestId('retry-btn-43')).not.toBeInTheDocument()
    })

    it('calls retryWebhookEvent with the correct log ID when Retry is clicked', async () => {
      const user = userEvent.setup()
      mockedHubSpotService.getWebhookLog.mockResolvedValue(logResponseWithFailedRow)

      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      // Wait for the Retry button to appear
      const retryBtn = await screen.findByTestId('retry-btn-42')
      await user.click(retryBtn)

      await waitFor(() => {
        expect(mockedHubSpotService.retryWebhookEvent).toHaveBeenCalledWith(42)
      })
    })

    it('does not show Retry button for processed rows', async () => {
      mockedHubSpotService.getWebhookLog.mockResolvedValue(logResponseWithFailedRow)

      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      // Wait for the table to render (failed row's button appears)
      await screen.findByTestId('retry-btn-42')

      // The processed row (id=43) should not have a retry button
      expect(screen.queryByTestId('retry-btn-43')).not.toBeInTheDocument()
    })
  })

  // ── Test 4: Stale sync warning ───────────────────────────────────────────

  describe('Stale sync warning', () => {
    it('shows warning when last_synced_at is more than 24 hours ago', async () => {
      mockedHubSpotService.getWebhookLogSummary.mockResolvedValue(staleSummary)

      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      await waitFor(() => {
        expect(
          screen.getByLabelText('No webhook events received in the last 24 hours')
        ).toBeInTheDocument()
      })
    })

    it('shows warning when last_synced_at is null (never synced)', async () => {
      mockedHubSpotService.getWebhookLogSummary.mockResolvedValue(noSyncSummary)

      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      await waitFor(() => {
        expect(
          screen.getByLabelText('No webhook events received in the last 24 hours')
        ).toBeInTheDocument()
      })
    })

    it('does not show stale warning when last_synced_at is recent', async () => {
      mockedHubSpotService.getWebhookLogSummary.mockResolvedValue(recentSummary)

      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      // Wait for summary to load
      await waitFor(() => {
        expect(screen.getByText(/Last 24 Hours/i)).toBeInTheDocument()
      })

      expect(
        screen.queryByLabelText('No webhook events received in the last 24 hours')
      ).not.toBeInTheDocument()
    })
  })

  // ── Additional: 24-hour summary counts ──────────────────────────────────

  describe('24-hour summary', () => {
    it('displays processed, failed, and deduplicated counts', async () => {
      mockedHubSpotService.getWebhookLogSummary.mockResolvedValue(recentSummary)

      render(
        <WebhookSyncPanel
          hasClientSecret={false}
          onClientSecretSaved={vi.fn()}
        />
      )

      await waitFor(() => {
        expect(screen.getByLabelText('10 processed events')).toBeInTheDocument()
        expect(screen.getByLabelText('1 failed events')).toBeInTheDocument()
        expect(screen.getByLabelText('2 deduplicated events')).toBeInTheDocument()
      })
    })
  })
})
