/**
 * Tests for QueueSidebar component
 *
 * Covers:
 * - renders all 7 queue links
 * - badge counts are displayed when counts are available
 * - active link is highlighted based on current URL path
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import { MemoryRouter } from 'react-router-dom'
import { QueueSidebar } from './QueueSidebar'
import type { QueueCounts } from '@/types'

// ---------------------------------------------------------------------------
// Mock the queueService
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  queueService: {
    getCounts: vi.fn(),
  },
}))

import { queueService } from '@/services/api'

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockCounts: QueueCounts = {
  todays_action: 5,
  previously_warm: 3,
  follow_up_overdue: 7,
  no_next_action: 2,
  needs_review: 1,
  do_not_contact: 4,
  missing_property_match: 6,
  ready_to_mail: 2,
  mail_candidates: 8,
  prospect_candidates: 3,
}

// ---------------------------------------------------------------------------
// Helper render function — wraps with MemoryRouter for Link support
// ---------------------------------------------------------------------------

function renderSidebar(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <QueueSidebar />
    </MemoryRouter>
  )
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(queueService.getCounts).mockResolvedValue(mockCounts)
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('QueueSidebar', () => {
  // -------------------------------------------------------------------------
  // Renders all 7 links
  // -------------------------------------------------------------------------

  describe('renders all 7 queue links', () => {
    it('renders the sidebar container', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-sidebar')).toBeInTheDocument()
    })

    it('renders Today\'s Action link', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-link-todays_action')).toBeInTheDocument()
      expect(screen.getByText("Today's Action")).toBeInTheDocument()
    })

    it('renders Previously Warm link', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-link-previously_warm')).toBeInTheDocument()
      expect(screen.getByText('Previously Warm')).toBeInTheDocument()
    })

    it('renders Follow-Up Overdue link', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-link-follow_up_overdue')).toBeInTheDocument()
      expect(screen.getByText('Follow-Up Overdue')).toBeInTheDocument()
    })

    it('renders No Next Action link', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-link-no_next_action')).toBeInTheDocument()
      expect(screen.getByText('No Next Action')).toBeInTheDocument()
    })

    it('renders Needs Review link', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-link-needs_review')).toBeInTheDocument()
      expect(screen.getByText('Needs Review')).toBeInTheDocument()
    })

    it('renders Do Not Contact link', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-link-do_not_contact')).toBeInTheDocument()
      expect(screen.getByText('Do Not Contact')).toBeInTheDocument()
    })

    it('renders Missing Property Match link', () => {
      renderSidebar()
      expect(screen.getByTestId('queue-link-missing_property_match')).toBeInTheDocument()
      expect(screen.getByText('Missing Property Match')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Badge counts displayed
  // -------------------------------------------------------------------------

  describe('badge counts displayed', () => {
    it('shows badge count for Today\'s Action', async () => {
      renderSidebar()
      await waitFor(() => {
        expect(screen.getByTestId('queue-badge-todays_action')).toHaveTextContent('5')
      })
    })

    it('shows badge count for Previously Warm', async () => {
      renderSidebar()
      await waitFor(() => {
        expect(screen.getByTestId('queue-badge-previously_warm')).toHaveTextContent('3')
      })
    })

    it('shows badge count for Follow-Up Overdue', async () => {
      renderSidebar()
      await waitFor(() => {
        expect(screen.getByTestId('queue-badge-follow_up_overdue')).toHaveTextContent('7')
      })
    })

    it('shows badge count for No Next Action', async () => {
      renderSidebar()
      await waitFor(() => {
        expect(screen.getByTestId('queue-badge-no_next_action')).toHaveTextContent('2')
      })
    })

    it('shows badge count for Needs Review', async () => {
      renderSidebar()
      await waitFor(() => {
        expect(screen.getByTestId('queue-badge-needs_review')).toHaveTextContent('1')
      })
    })

    it('shows badge count for Do Not Contact', async () => {
      renderSidebar()
      await waitFor(() => {
        expect(screen.getByTestId('queue-badge-do_not_contact')).toHaveTextContent('4')
      })
    })

    it('shows badge count for Missing Property Match', async () => {
      renderSidebar()
      await waitFor(() => {
        expect(screen.getByTestId('queue-badge-missing_property_match')).toHaveTextContent('6')
      })
    })

    it('does not show badge when count is 0', async () => {
      vi.mocked(queueService.getCounts).mockResolvedValue({
        ...mockCounts,
        needs_review: 0,
      })
      renderSidebar()
      await waitFor(() => {
        // Other badges should be visible
        expect(screen.getByTestId('queue-badge-todays_action')).toBeInTheDocument()
      })
      // needs_review badge should not be rendered when count is 0
      expect(screen.queryByTestId('queue-badge-needs_review')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Active link highlighted
  // -------------------------------------------------------------------------

  describe('active link highlighted', () => {
    it('marks Today\'s Action as selected when path is "/queues/todays-action"', () => {
      renderSidebar('/queues/todays-action')
      const link = screen.getByTestId('queue-link-todays_action')
      // MUI ListItemButton with selected=true gets aria-selected or Mui-selected class
      expect(link).toHaveClass('Mui-selected')
    })

    it('marks Previously Warm as selected when path is "/queues/previously-warm"', () => {
      renderSidebar('/queues/previously-warm')
      const link = screen.getByTestId('queue-link-previously_warm')
      expect(link).toHaveClass('Mui-selected')
    })

    it('marks Follow-Up Overdue as selected when path is "/queues/follow-up-overdue"', () => {
      renderSidebar('/queues/follow-up-overdue')
      const link = screen.getByTestId('queue-link-follow_up_overdue')
      expect(link).toHaveClass('Mui-selected')
    })

    it('marks No Next Action as selected when path is "/queues/no-next-action"', () => {
      renderSidebar('/queues/no-next-action')
      const link = screen.getByTestId('queue-link-no_next_action')
      expect(link).toHaveClass('Mui-selected')
    })

    it('marks Needs Review as selected when path is "/queues/needs-review"', () => {
      renderSidebar('/queues/needs-review')
      const link = screen.getByTestId('queue-link-needs_review')
      expect(link).toHaveClass('Mui-selected')
    })

    it('marks Do Not Contact as selected when path is "/queues/do-not-contact"', () => {
      renderSidebar('/queues/do-not-contact')
      const link = screen.getByTestId('queue-link-do_not_contact')
      expect(link).toHaveClass('Mui-selected')
    })

    it('marks Missing Property Match as selected when path is "/queues/missing-property-match"', () => {
      renderSidebar('/queues/missing-property-match')
      const link = screen.getByTestId('queue-link-missing_property_match')
      expect(link).toHaveClass('Mui-selected')
    })

    it('does not mark Today\'s Action as selected when on a different path', () => {
      renderSidebar('/queues/previously-warm')
      const link = screen.getByTestId('queue-link-todays_action')
      expect(link).not.toHaveClass('Mui-selected')
    })
  })
})
