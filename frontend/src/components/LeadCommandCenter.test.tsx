/**
 * Tests for LeadCommandCenter component
 *
 * Covers:
 * - renders all sections (header, RA panel, tasks, timeline, log note, log call)
 * - status badge dropdown opens and shows all valid statuses
 * - status change success updates badge (via query invalidation)
 * - status change failure reverts badge and shows error
 * - property match link shown when has_property_match=true
 * - missing match link shown when has_property_match=false
 * - DNC badge visible when lead_status='do_not_contact'
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { LeadCommandCenter } from './LeadCommandCenter'
import type { CommandCenterPayload } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API services
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  commandCenterService: {
    getCommandCenter: vi.fn(),
    updateStatus: vi.fn(),
    getTimeline: vi.fn(),
  },
  leadTaskService: {
    createTask: vi.fn(),
    completeTask: vi.fn(),
    snoozeTask: vi.fn(),
    updateTask: vi.fn(),
  },
  callLogService: {
    logNote: vi.fn(),
    logCall: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: 'John',
    owner_last_name: 'Smith',
    property_street: '123 Main St',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 75,
    lead_status: 'mailing_no_contact_made',
    has_property_match: true,
    analysis_session_id: 42,
    recommended_action: {
      value: 'follow_up_now',
      label: 'Follow Up Now',
      explanation: 'This lead has prior engagement.',
      signals: {},
    },
    open_tasks: [],
    timeline: {
      entries: [
        {
          id: 1,
          lead_id: 1,
          event_type: 'note_added',
          occurred_at: '2024-01-15T10:00:00Z',
          source: 'manual',
          actor: 'user@example.com',
          summary: 'Called owner, left voicemail.',
          metadata: null,
          hubspot_activity_id: null,
          is_deleted: false,
          created_at: '2024-01-15T10:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      per_page: 25,
    },
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

const user = userEvent.setup({ pointerEventsCheck: 0 })

let commandCenterService: typeof import('@/services/api')['commandCenterService']

beforeEach(async () => {
  vi.clearAllMocks()
  const api = await import('@/services/api')
  commandCenterService = api.commandCenterService
  vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(makePayload())
})

// ---------------------------------------------------------------------------
// Helper render function — wraps with MemoryRouter for RouterLink support
// ---------------------------------------------------------------------------

function renderCommandCenter(leadId = 1) {
  return render(
    <MemoryRouter>
      <LeadCommandCenter leadId={leadId} />
    </MemoryRouter>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LeadCommandCenter', () => {
  describe('renders all sections', () => {
    it('shows loading spinner initially', () => {
      // getCommandCenter is pending (never resolves in this test)
      vi.mocked(commandCenterService.getCommandCenter).mockReturnValue(new Promise(() => {}))
      renderCommandCenter()
      expect(screen.getByTestId('command-center-loading')).toBeInTheDocument()
    })

    it('renders lead header with owner name and address', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('lead-owner-name')).toHaveTextContent('John Smith')
      })
      expect(screen.getByTestId('lead-address')).toHaveTextContent('123 Main St, Chicago, IL')
    })

    it('renders lead score', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('lead-score')).toHaveTextContent('75')
      })
    })

    it('renders the recommended action section', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('recommended-action-section')).toBeInTheDocument()
      })
      expect(screen.getByTestId('recommended-action-panel')).toBeInTheDocument()
    })

    it('renders the tasks section', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('tasks-section')).toBeInTheDocument()
      })
      expect(screen.getByTestId('lead-task-list')).toBeInTheDocument()
    })

    it('renders the log note section', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('log-note-section')).toBeInTheDocument()
      })
      expect(screen.getByTestId('log-note-form')).toBeInTheDocument()
    })

    it('renders the log call section', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('log-call-section')).toBeInTheDocument()
      })
      expect(screen.getByTestId('log-call-form')).toBeInTheDocument()
    })

    it('renders the timeline section', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('timeline-section')).toBeInTheDocument()
      })
      expect(screen.getByTestId('lead-timeline')).toBeInTheDocument()
    })

    it('shows error state when API call fails', async () => {
      vi.mocked(commandCenterService.getCommandCenter).mockRejectedValue(
        new Error('Network error')
      )
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('command-center-error')).toBeInTheDocument()
      })
      expect(screen.getByTestId('command-center-error')).toHaveTextContent('Network error')
    })
  })

  describe('status badge dropdown', () => {
    it('renders the status badge with current status', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('status-badge-container')).toBeInTheDocument()
      })
    })

    it('shows all valid lead status options in the dropdown', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('status-badge-container')).toBeInTheDocument()
      })

      // Open the status dropdown specifically (there are multiple comboboxes on the page)
      const statusContainer = screen.getByTestId('status-badge-container')
      const statusSelect = statusContainer.querySelector('[role="combobox"]') as HTMLElement
      await user.click(statusSelect)

      await waitFor(() => {
        expect(screen.getByTestId('status-option-mailing_no_contact_made')).toBeInTheDocument()
        expect(screen.getByTestId('status-option-mailing_contacted_interested')).toBeInTheDocument()
        expect(screen.getByTestId('status-option-negotiating_remote')).toBeInTheDocument()
        expect(screen.getByTestId('status-option-deprioritize')).toBeInTheDocument()
        expect(screen.getByTestId('status-option-suppressed')).toBeInTheDocument()
        expect(screen.getByTestId('status-option-do_not_contact')).toBeInTheDocument()
      })
    })
  })

  describe('status change success', () => {
    it('calls updateStatus with the new status when a new option is selected', async () => {
      vi.mocked(commandCenterService.updateStatus).mockResolvedValue(undefined)
      // Return updated payload on second call
      vi.mocked(commandCenterService.getCommandCenter)
        .mockResolvedValueOnce(makePayload({ lead_status: 'mailing_no_contact_made' }))
        .mockResolvedValue(makePayload({ lead_status: 'mailing_contacted_interested' }))

      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('status-badge-container')).toBeInTheDocument()
      })

      const statusContainer = screen.getByTestId('status-badge-container')
      const statusSelect = statusContainer.querySelector('[role="combobox"]') as HTMLElement
      await user.click(statusSelect)

      await waitFor(() => {
        expect(screen.getByTestId('status-option-mailing_contacted_interested')).toBeInTheDocument()
      })

      await user.click(screen.getByTestId('status-option-mailing_contacted_interested'))

      await waitFor(() => {
        expect(commandCenterService.updateStatus).toHaveBeenCalledWith(1, 'mailing_contacted_interested')
      })
    })

    it('does not show status change error on success', async () => {
      vi.mocked(commandCenterService.updateStatus).mockResolvedValue(undefined)

      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('status-badge-container')).toBeInTheDocument()
      })

      const statusContainer = screen.getByTestId('status-badge-container')
      const statusSelect = statusContainer.querySelector('[role="combobox"]') as HTMLElement
      await user.click(statusSelect)

      await waitFor(() => {
        expect(screen.getByTestId('status-option-deprioritize')).toBeInTheDocument()
      })

      await user.click(screen.getByTestId('status-option-deprioritize'))

      await waitFor(() => {
        expect(commandCenterService.updateStatus).toHaveBeenCalled()
      })

      expect(screen.queryByTestId('status-change-error')).not.toBeInTheDocument()
    })
  })

  describe('status change failure reverts badge', () => {
    it('shows error message when status update fails', async () => {
      vi.mocked(commandCenterService.updateStatus).mockRejectedValue(
        new Error('Status update failed')
      )

      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('status-badge-container')).toBeInTheDocument()
      })

      const statusContainer = screen.getByTestId('status-badge-container')
      const statusSelect = statusContainer.querySelector('[role="combobox"]') as HTMLElement
      await user.click(statusSelect)

      await waitFor(() => {
        expect(screen.getByTestId('status-option-deprioritize')).toBeInTheDocument()
      })

      await user.click(screen.getByTestId('status-option-deprioritize'))

      await waitFor(() => {
        expect(screen.getByTestId('status-change-error')).toBeInTheDocument()
      })

      expect(screen.getByTestId('status-change-error')).toHaveTextContent(
        'Status update failed'
      )
    })

    it('refetches data to revert badge after failure', async () => {
      vi.mocked(commandCenterService.updateStatus).mockRejectedValue(
        new Error('Status update failed')
      )

      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('status-badge-container')).toBeInTheDocument()
      })

      const statusContainer = screen.getByTestId('status-badge-container')
      const statusSelect = statusContainer.querySelector('[role="combobox"]') as HTMLElement
      await user.click(statusSelect)

      await waitFor(() => {
        expect(screen.getByTestId('status-option-deprioritize')).toBeInTheDocument()
      })

      await user.click(screen.getByTestId('status-option-deprioritize'))

      await waitFor(() => {
        expect(screen.getByTestId('status-change-error')).toBeInTheDocument()
      })

      // getCommandCenter should have been called again to revert
      expect(commandCenterService.getCommandCenter).toHaveBeenCalledTimes(2)
    })
  })

  describe('property match link', () => {
    it('shows "Matched" with link to analysis when has_property_match=true', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('property-match-status')).toBeInTheDocument()
      })
      expect(screen.getByTestId('property-match-link')).toBeInTheDocument()
      expect(screen.getByTestId('property-match-link')).toHaveTextContent('View Analysis')
    })

    it('shows "Unmatched" with link to missing-property-match when has_property_match=false', async () => {
      vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
        makePayload({ has_property_match: false, analysis_session_id: null })
      )

      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('property-match-status')).toBeInTheDocument()
      })
      expect(screen.getByTestId('missing-match-link')).toBeInTheDocument()
      expect(screen.getByTestId('missing-match-link')).toHaveTextContent('Find Property Match')
    })

    it('missing match link points to /queues/missing-property-match', async () => {
      vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
        makePayload({ has_property_match: false, analysis_session_id: null })
      )

      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('missing-match-link')).toBeInTheDocument()
      })
      expect(screen.getByTestId('missing-match-link')).toHaveAttribute(
        'href',
        '/queues/missing-property-match'
      )
    })
  })

  describe('DNC badge', () => {
    it('shows DNC badge when lead_status is do_not_contact', async () => {
      vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
        makePayload({ lead_status: 'do_not_contact' })
      )

      renderCommandCenter()
      await waitFor(() => {
        // DNC badge appears in the lead header
        const header = screen.getByTestId('lead-header')
        expect(header.querySelector('[data-testid="dnc-badge"]')).toBeInTheDocument()
      })
    })

    it('DNC badge in header has correct text', async () => {
      vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
        makePayload({ lead_status: 'do_not_contact' })
      )

      renderCommandCenter()
      await waitFor(() => {
        const header = screen.getByTestId('lead-header')
        const badge = header.querySelector('[data-testid="dnc-badge"]')
        expect(badge).toBeInTheDocument()
        expect(badge).toHaveTextContent('DO NOT CONTACT')
      })
    })

    it('does NOT show DNC badge in header when lead_status is active', async () => {
      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('lead-header')).toBeInTheDocument()
      })
      const header = screen.getByTestId('lead-header')
      expect(header.querySelector('[data-testid="dnc-badge"]')).not.toBeInTheDocument()
    })

    it('does NOT show DNC badge in header when lead_status is follow_up', async () => {
      vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
        makePayload({ lead_status: 'mailing_contacted_interested' })
      )

      renderCommandCenter()
      await waitFor(() => {
        expect(screen.getByTestId('lead-header')).toBeInTheDocument()
      })
      const header = screen.getByTestId('lead-header')
      expect(header.querySelector('[data-testid="dnc-badge"]')).not.toBeInTheDocument()
    })
  })
})

