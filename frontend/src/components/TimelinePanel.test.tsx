/**
 * Tests for TimelinePanel component
 *
 * Covers:
 * - renders entries in reverse chronological order
 * - renders both Interaction and Task entries with correct icons and labels
 * - empty state displays message when no entries
 * - filter by entry type shows only matching entries
 * - filter by date range shows only entries within range
 * - source badge shows manual or hubspot_import correctly
 * - HubSpot engagement ID displayed when present
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import { TimelinePanel } from './TimelinePanel'
import { timelineService } from '@/services/api'
import type { TimelineEntry } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  timelineService: {
    getLeadTimeline: vi.fn(),
    getOrganizationTimeline: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockEntries: TimelineEntry[] = [
  {
    entry_type: 'interaction',
    subtype: 'note',
    date: '2024-03-15T14:00:00Z',
    body_or_title: 'Called owner, left voicemail',
    source: 'manual',
    hubspot_engagement_id: null,
  },
  {
    entry_type: 'task',
    subtype: 'task',
    date: '2024-03-10T09:00:00Z',
    body_or_title: 'Follow up with owner next week',
    source: 'hubspot_import',
    hubspot_engagement_id: 'hs-eng-12345',
  },
  {
    entry_type: 'interaction',
    subtype: 'call',
    date: '2024-03-05T11:30:00Z',
    body_or_title: 'Spoke with owner about property',
    source: 'hubspot_import',
    hubspot_engagement_id: 'hs-eng-67890',
  },
]

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(timelineService.getLeadTimeline).mockResolvedValue(mockEntries)
  vi.mocked(timelineService.getOrganizationTimeline).mockResolvedValue(mockEntries)
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TimelinePanel', () => {
  describe('reverse chronological order', () => {
    it('renders entries in reverse chronological order (newest first)', async () => {
      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry').length).toBe(3)
      })

      const entries = screen.getAllByTestId('timeline-entry-body')
      // The API returns entries already sorted; we verify they appear in the order returned
      expect(entries[0]).toHaveTextContent('Called owner, left voicemail')
      expect(entries[1]).toHaveTextContent('Follow up with owner next week')
      expect(entries[2]).toHaveTextContent('Spoke with owner about property')
    })
  })

  describe('entry rendering', () => {
    it('renders Interaction entries with correct subtype labels', async () => {
      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry').length).toBe(3)
      })

      const subtypes = screen.getAllByTestId('timeline-entry-subtype')
      expect(subtypes[0]).toHaveTextContent('Note')
      expect(subtypes[1]).toHaveTextContent('Task')
      expect(subtypes[2]).toHaveTextContent('Call')
    })

    it('renders Task entries with task subtype label', async () => {
      const taskOnlyEntries: TimelineEntry[] = [
        {
          entry_type: 'task',
          subtype: 'task',
          date: '2024-03-10T09:00:00Z',
          body_or_title: 'Schedule property walkthrough',
          source: 'manual',
          hubspot_engagement_id: null,
        },
      ]
      vi.mocked(timelineService.getLeadTimeline).mockResolvedValue(taskOnlyEntries)

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getByText('Schedule property walkthrough')).toBeInTheDocument()
      })

      expect(screen.getByTestId('timeline-entry-subtype')).toHaveTextContent('Task')
    })

    it('renders body text for each entry', async () => {
      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getByText('Called owner, left voicemail')).toBeInTheDocument()
        expect(screen.getByText('Follow up with owner next week')).toBeInTheDocument()
        expect(screen.getByText('Spoke with owner about property')).toBeInTheDocument()
      })
    })
  })

  describe('empty state', () => {
    it('displays empty state message when no entries exist', async () => {
      vi.mocked(timelineService.getLeadTimeline).mockResolvedValue([])

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getByTestId('timeline-empty')).toBeInTheDocument()
        expect(screen.getByText('No timeline entries yet')).toBeInTheDocument()
      })
    })

    it('does not render the timeline list when empty', async () => {
      vi.mocked(timelineService.getLeadTimeline).mockResolvedValue([])

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.queryByTestId('timeline-list')).not.toBeInTheDocument()
      })
    })
  })

  describe('filter by entry type', () => {
    it('calls API with entry_type filter when type is selected', async () => {
      vi.mocked(timelineService.getLeadTimeline)
        .mockResolvedValueOnce(mockEntries)
        .mockResolvedValue([mockEntries[0], mockEntries[2]]) // only interactions

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry').length).toBe(3)
      })

      // Select "Interaction" from the Type filter
      const typeSelect = screen.getByLabelText('Type')
      fireEvent.mouseDown(typeSelect)

      const listbox = screen.getByRole('listbox')
      fireEvent.click(listbox.querySelector('[data-value="interaction"]')!)

      await waitFor(() => {
        expect(timelineService.getLeadTimeline).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ entry_type: 'interaction' })
        )
      })
    })

    it('calls API with task entry_type filter', async () => {
      vi.mocked(timelineService.getLeadTimeline)
        .mockResolvedValueOnce(mockEntries)
        .mockResolvedValue([mockEntries[1]]) // only tasks

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry').length).toBe(3)
      })

      const typeSelect = screen.getByLabelText('Type')
      fireEvent.mouseDown(typeSelect)

      const listbox = screen.getByRole('listbox')
      fireEvent.click(listbox.querySelector('[data-value="task"]')!)

      await waitFor(() => {
        expect(timelineService.getLeadTimeline).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ entry_type: 'task' })
        )
      })
    })
  })

  describe('filter by date range', () => {
    it('calls API with date_from filter when From date is set', async () => {
      vi.mocked(timelineService.getLeadTimeline)
        .mockResolvedValueOnce(mockEntries)
        .mockResolvedValue([mockEntries[0]])

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry').length).toBe(3)
      })

      const fromInput = screen.getByLabelText('From')
      fireEvent.change(fromInput, { target: { value: '2024-03-12' } })

      await waitFor(() => {
        expect(timelineService.getLeadTimeline).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ date_from: '2024-03-12' })
        )
      })
    })

    it('calls API with date_to filter when To date is set', async () => {
      vi.mocked(timelineService.getLeadTimeline)
        .mockResolvedValueOnce(mockEntries)
        .mockResolvedValue([mockEntries[1], mockEntries[2]])

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry').length).toBe(3)
      })

      const toInput = screen.getByLabelText('To')
      fireEvent.change(toInput, { target: { value: '2024-03-12' } })

      await waitFor(() => {
        expect(timelineService.getLeadTimeline).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ date_to: '2024-03-12' })
        )
      })
    })
  })

  describe('source badge', () => {
    it('shows "Manual" source badge for manual entries', async () => {
      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry-source').length).toBe(3)
      })

      const sourceBadges = screen.getAllByTestId('timeline-entry-source')
      expect(sourceBadges[0]).toHaveTextContent('Manual')
    })

    it('shows "HubSpot" source badge for hubspot_import entries', async () => {
      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry-source').length).toBe(3)
      })

      const sourceBadges = screen.getAllByTestId('timeline-entry-source')
      expect(sourceBadges[1]).toHaveTextContent('HubSpot')
      expect(sourceBadges[2]).toHaveTextContent('HubSpot')
    })
  })

  describe('HubSpot engagement ID', () => {
    it('displays HubSpot engagement ID badge when present', async () => {
      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getAllByTestId('timeline-entry-hs-id').length).toBe(2)
      })

      const hsBadges = screen.getAllByTestId('timeline-entry-hs-id')
      expect(hsBadges[0]).toHaveTextContent('HS: hs-eng-12345')
      expect(hsBadges[1]).toHaveTextContent('HS: hs-eng-67890')
    })

    it('does not display HubSpot engagement ID badge when absent', async () => {
      const manualOnlyEntries: TimelineEntry[] = [
        {
          entry_type: 'interaction',
          subtype: 'note',
          date: '2024-03-15T14:00:00Z',
          body_or_title: 'Manual note',
          source: 'manual',
          hubspot_engagement_id: null,
        },
      ]
      vi.mocked(timelineService.getLeadTimeline).mockResolvedValue(manualOnlyEntries)

      render(<TimelinePanel targetType="lead" targetId={1} />)

      await waitFor(() => {
        expect(screen.getByText('Manual note')).toBeInTheDocument()
      })

      expect(screen.queryByTestId('timeline-entry-hs-id')).not.toBeInTheDocument()
    })
  })

  describe('organization timeline', () => {
    it('calls getOrganizationTimeline when targetType is organization', async () => {
      vi.mocked(timelineService.getOrganizationTimeline).mockResolvedValue(mockEntries)

      render(<TimelinePanel targetType="organization" targetId={5} />)

      await waitFor(() => {
        expect(timelineService.getOrganizationTimeline).toHaveBeenCalledWith(5, {})
      })
    })
  })
})
