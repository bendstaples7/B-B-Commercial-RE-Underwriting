/**
 * Tests for LeadTimeline component
 *
 * Covers:
 * - renders entries with event type, timestamp, actor, summary
 * - HubSpot icon shown on source='hubspot' entries
 * - HubSpot icon NOT shown on non-hubspot entries
 * - "Load more" appends entries without replacing existing ones
 * - read-only for HubSpot entries (no edit/delete buttons)
 * - empty state when no entries
 * - "Load more" button hidden when all entries loaded
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LeadTimeline } from './LeadTimeline'
import type { LeadTimelineEntry } from '@/types'

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeEntry(
  id: number,
  overrides: Partial<LeadTimelineEntry> = {}
): LeadTimelineEntry {
  return {
    id,
    lead_id: 1,
    event_type: 'note_added',
    occurred_at: '2024-06-01T12:00:00Z',
    source: 'manual',
    actor: 'Test User',
    summary: `Entry ${id} summary`,
    metadata: null,
    hubspot_activity_id: null,
    is_deleted: false,
    created_at: '2024-06-01T12:00:00Z',
    ...overrides,
  }
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LeadTimeline', () => {
  // -------------------------------------------------------------------------
  // Renders entries
  // -------------------------------------------------------------------------

  describe('renders entries', () => {
    it('renders the timeline container', () => {
      render(
        <LeadTimeline
          leadId={1}
          initialEntries={[]}
          initialTotal={0}
        />
      )
      expect(screen.getByTestId('lead-timeline')).toBeInTheDocument()
    })

    it('shows empty state when no entries', () => {
      render(
        <LeadTimeline
          leadId={1}
          initialEntries={[]}
          initialTotal={0}
        />
      )
      expect(screen.getByTestId('timeline-empty')).toBeInTheDocument()
    })

    it('renders each entry with event type, timestamp, actor, and summary', () => {
      const entries = [
        makeEntry(1, {
          event_type: 'note_added',
          occurred_at: '2024-06-01T12:00:00Z',
          actor: 'Alice',
          summary: 'Left a note about the property',
        }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={1}
        />
      )

      expect(screen.getByTestId('entry-event-type-1')).toHaveTextContent('Note Added')
      expect(screen.getByTestId('entry-timestamp-1')).toBeInTheDocument()
      expect(screen.getByTestId('entry-actor-1')).toHaveTextContent('Alice')
      expect(screen.getByTestId('entry-summary-1')).toHaveTextContent('Left a note about the property')
    })

    it('renders multiple entries', () => {
      const entries = [
        makeEntry(1, { summary: 'First entry' }),
        makeEntry(2, { summary: 'Second entry' }),
        makeEntry(3, { summary: 'Third entry' }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={3}
        />
      )

      expect(screen.getByTestId('timeline-entry-1')).toBeInTheDocument()
      expect(screen.getByTestId('timeline-entry-2')).toBeInTheDocument()
      expect(screen.getByTestId('timeline-entry-3')).toBeInTheDocument()
    })

    it('shows "Showing X of Y" count', () => {
      const entries = [makeEntry(1), makeEntry(2)]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={10}
        />
      )

      expect(screen.getByTestId('timeline-showing')).toHaveTextContent('Showing 2 of 10')
    })

    it('does not show empty state when entries exist', () => {
      render(
        <LeadTimeline
          leadId={1}
          initialEntries={[makeEntry(1)]}
          initialTotal={1}
        />
      )
      expect(screen.queryByTestId('timeline-empty')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // HubSpot icon on hubspot entries
  // -------------------------------------------------------------------------

  describe('HubSpot icon on hubspot entries', () => {
    it('shows HubSpot icon on source=hubspot entries', () => {
      const entries = [
        makeEntry(1, { source: 'hubspot', event_type: 'hubspot_call' }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={1}
        />
      )

      expect(screen.getByTestId('hubspot-avatar-1')).toBeInTheDocument()
      expect(screen.getByTestId('hubspot-icon')).toBeInTheDocument()
    })

    it('does NOT show HubSpot icon on source=manual entries', () => {
      const entries = [
        makeEntry(1, { source: 'manual' }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={1}
        />
      )

      expect(screen.queryByTestId('hubspot-avatar-1')).not.toBeInTheDocument()
      expect(screen.queryByTestId('hubspot-icon')).not.toBeInTheDocument()
    })

    it('does NOT show HubSpot icon on source=system entries', () => {
      const entries = [
        makeEntry(1, { source: 'system' }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={1}
        />
      )

      expect(screen.queryByTestId('hubspot-avatar-1')).not.toBeInTheDocument()
    })

    it('shows HubSpot icon only on hubspot entries when mixed', () => {
      const entries = [
        makeEntry(1, { source: 'hubspot' }),
        makeEntry(2, { source: 'manual' }),
        makeEntry(3, { source: 'hubspot' }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={3}
        />
      )

      expect(screen.getByTestId('hubspot-avatar-1')).toBeInTheDocument()
      expect(screen.queryByTestId('hubspot-avatar-2')).not.toBeInTheDocument()
      expect(screen.getByTestId('hubspot-avatar-3')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Load more appends entries
  // -------------------------------------------------------------------------

  describe('load more appends entries', () => {
    it('shows "Load more" button when more entries exist', () => {
      const entries = [makeEntry(1), makeEntry(2)]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={10}
          onLoadMore={vi.fn()}
        />
      )

      expect(screen.getByTestId('load-more-btn')).toBeInTheDocument()
    })

    it('does NOT show "Load more" button when all entries are loaded', () => {
      const entries = [makeEntry(1), makeEntry(2)]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={2}
          onLoadMore={vi.fn()}
        />
      )

      expect(screen.queryByTestId('load-more-btn')).not.toBeInTheDocument()
    })

    it('does NOT show "Load more" button when onLoadMore is not provided', () => {
      const entries = [makeEntry(1)]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={10}
          // no onLoadMore
        />
      )

      expect(screen.queryByTestId('load-more-btn')).not.toBeInTheDocument()
    })

    it('appends new entries without replacing existing ones on load more', async () => {
      const initialEntries = [makeEntry(1, { summary: 'Entry 1' }), makeEntry(2, { summary: 'Entry 2' })]
      const moreEntries = [makeEntry(3, { summary: 'Entry 3' }), makeEntry(4, { summary: 'Entry 4' })]

      const onLoadMore = vi.fn().mockResolvedValue({
        entries: moreEntries,
        total: 4,
      })

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={initialEntries}
          initialTotal={4}
          onLoadMore={onLoadMore}
        />
      )

      await user.click(screen.getByTestId('load-more-btn'))

      await waitFor(() => {
        // Original entries still present
        expect(screen.getByTestId('entry-summary-1')).toHaveTextContent('Entry 1')
        expect(screen.getByTestId('entry-summary-2')).toHaveTextContent('Entry 2')
        // New entries appended
        expect(screen.getByTestId('entry-summary-3')).toHaveTextContent('Entry 3')
        expect(screen.getByTestId('entry-summary-4')).toHaveTextContent('Entry 4')
      })
    })

    it('calls onLoadMore with the next page number', async () => {
      const onLoadMore = vi.fn().mockResolvedValue({
        entries: [makeEntry(26)],
        total: 26,
      })

      const initialEntries = Array.from({ length: 25 }, (_, i) => makeEntry(i + 1))

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={initialEntries}
          initialTotal={26}
          onLoadMore={onLoadMore}
        />
      )

      await user.click(screen.getByTestId('load-more-btn'))

      await waitFor(() => {
        expect(onLoadMore).toHaveBeenCalledWith(2)
      })
    })

    it('hides "Load more" button after all entries are loaded', async () => {
      const initialEntries = [makeEntry(1), makeEntry(2)]
      const moreEntries = [makeEntry(3)]

      const onLoadMore = vi.fn().mockResolvedValue({
        entries: moreEntries,
        total: 3,
      })

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={initialEntries}
          initialTotal={3}
          onLoadMore={onLoadMore}
        />
      )

      await user.click(screen.getByTestId('load-more-btn'))

      await waitFor(() => {
        expect(screen.queryByTestId('load-more-btn')).not.toBeInTheDocument()
      })
    })

    it('updates "Showing X of Y" after loading more', async () => {
      const initialEntries = [makeEntry(1), makeEntry(2)]
      const moreEntries = [makeEntry(3), makeEntry(4)]

      const onLoadMore = vi.fn().mockResolvedValue({
        entries: moreEntries,
        total: 4,
      })

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={initialEntries}
          initialTotal={4}
          onLoadMore={onLoadMore}
        />
      )

      expect(screen.getByTestId('timeline-showing')).toHaveTextContent('Showing 2 of 4')

      await user.click(screen.getByTestId('load-more-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('timeline-showing')).toHaveTextContent('Showing 4 of 4')
      })
    })
  })

  // -------------------------------------------------------------------------
  // Read-only for HubSpot entries
  // -------------------------------------------------------------------------

  describe('read-only HubSpot entries', () => {
    it('does not render edit or delete buttons for any entries', () => {
      const entries = [
        makeEntry(1, { source: 'hubspot' }),
        makeEntry(2, { source: 'manual' }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={2}
        />
      )

      // No edit or delete buttons should exist anywhere in the timeline
      expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument()
    })

    it('renders HubSpot entry content (event type, actor, summary) as read-only text', () => {
      const entries = [
        makeEntry(1, {
          source: 'hubspot',
          event_type: 'hubspot_call',
          actor: 'HubSpot',
          summary: 'Call logged via HubSpot',
        }),
      ]

      render(
        <LeadTimeline
          leadId={1}
          initialEntries={entries}
          initialTotal={1}
        />
      )

      // Content is rendered as text, not editable inputs
      expect(screen.getByTestId('entry-event-type-1')).toHaveTextContent('Hubspot Call')
      expect(screen.getByTestId('entry-actor-1')).toHaveTextContent('HubSpot')
      expect(screen.getByTestId('entry-summary-1')).toHaveTextContent('Call logged via HubSpot')

      // No input fields for HubSpot entries
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    })
  })
})
