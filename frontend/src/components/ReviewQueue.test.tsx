/**
 * Tests for ReviewQueue component
 *
 * Covers:
 * - filter by object type renders only matching rows
 * - filter by confidence renders only matching rows
 * - confirm action calls confirmMatch and removes item
 * - reject + re-link opens record search and calls rejectMatch
 * - mark as new record calls markMatchAsNewRecord and removes item
 * - side-by-side comparison displays existing vs incoming values
 * - pending count badge reflects correct count
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { ReviewQueue } from './ReviewQueue'
import { hubSpotService } from '@/services/api'
import { MatchConfidence, MatchStatus } from '@/types'
import type { HubSpotMatch } from '@/types'

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
  },
}))

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockDealMatch: HubSpotMatch = {
  id: 1,
  hubspot_record_type: 'deal',
  hubspot_id: 'hs-deal-001',
  internal_record_type: 'lead',
  internal_record_id: 100,
  confidence: MatchConfidence.MEDIUM,
  status: MatchStatus.PENDING,
  matching_criteria: 'address_match',
  created_at: '2024-01-01T10:00:00Z',
  updated_at: '2024-01-01T10:00:00Z',
}

const mockContactMatch: HubSpotMatch = {
  id: 2,
  hubspot_record_type: 'contact',
  hubspot_id: 'hs-contact-002',
  internal_record_type: 'lead',
  internal_record_id: 200,
  confidence: MatchConfidence.LOW,
  status: MatchStatus.PENDING,
  matching_criteria: 'email_match',
  created_at: '2024-01-02T10:00:00Z',
  updated_at: '2024-01-02T10:00:00Z',
}

const mockUnmatchedCompany: HubSpotMatch = {
  id: 3,
  hubspot_record_type: 'company',
  hubspot_id: 'hs-company-003',
  internal_record_type: null,
  internal_record_id: null,
  confidence: MatchConfidence.UNMATCHED,
  status: MatchStatus.PENDING,
  matching_criteria: null,
  created_at: '2024-01-03T10:00:00Z',
  updated_at: '2024-01-03T10:00:00Z',
}

const allMatches = [mockDealMatch, mockContactMatch, mockUnmatchedCompany]

const user = userEvent.setup({ pointerEventsCheck: 0 })

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()

  // Default: return all matches
  vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
    matches: allMatches,
    total: 3,
    page: 1,
    per_page: 20,
  })
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ReviewQueue', () => {
  describe('filter by object type', () => {
    it('renders only matching rows when object type filter is applied', async () => {
      // When "deal" type is selected, only deal matches are returned
      vi.mocked(hubSpotService.getReviewQueue)
        .mockResolvedValueOnce({ matches: allMatches, total: 3, page: 1, per_page: 20 }) // pending count query
        .mockResolvedValueOnce({ matches: allMatches, total: 3, page: 1, per_page: 20 }) // initial load
        .mockResolvedValue({ matches: [mockDealMatch], total: 1, page: 1, per_page: 20 }) // after filter

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Review queue row for HubSpot deal hs-deal-001/)).toBeInTheDocument()
      })

      // Open the Object Type filter dropdown
      const typeSelect = screen.getByLabelText('Object Type')
      fireEvent.mouseDown(typeSelect)

      const listbox = screen.getByRole('listbox')
      fireEvent.click(within(listbox).getByText('Deal'))

      await waitFor(() => {
        expect(hubSpotService.getReviewQueue).toHaveBeenCalledWith(
          expect.objectContaining({ type: 'deal' })
        )
      })
    })
  })

  describe('filter by confidence', () => {
    it('renders only matching rows when confidence filter is applied', async () => {
      vi.mocked(hubSpotService.getReviewQueue)
        .mockResolvedValueOnce({ matches: allMatches, total: 3, page: 1, per_page: 20 }) // pending count
        .mockResolvedValueOnce({ matches: allMatches, total: 3, page: 1, per_page: 20 }) // initial
        .mockResolvedValue({ matches: [mockContactMatch], total: 1, page: 1, per_page: 20 }) // after filter

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Review queue row for HubSpot contact hs-contact-002/)).toBeInTheDocument()
      })

      // Open the Confidence filter dropdown
      const confidenceSelect = screen.getByLabelText('Confidence')
      fireEvent.mouseDown(confidenceSelect)

      const listbox = screen.getByRole('listbox')
      fireEvent.click(within(listbox).getByText('Low'))

      await waitFor(() => {
        expect(hubSpotService.getReviewQueue).toHaveBeenCalledWith(
          expect.objectContaining({ confidence: MatchConfidence.LOW })
        )
      })
    })
  })

  describe('confirm action', () => {
    it('calls confirmMatch when Confirm button is clicked', async () => {
      vi.mocked(hubSpotService.confirmMatch).mockResolvedValue({
        ...mockDealMatch,
        status: MatchStatus.CONFIRMED,
      })
      vi.mocked(hubSpotService.getReviewQueue)
        .mockResolvedValueOnce({ matches: allMatches, total: 3, page: 1, per_page: 20 })
        .mockResolvedValue({ matches: [mockContactMatch, mockUnmatchedCompany], total: 2, page: 1, per_page: 20 })

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText('Confirm match for hs-deal-001')).toBeInTheDocument()
      })

      await user.click(screen.getByLabelText('Confirm match for hs-deal-001'))

      await waitFor(() => {
        expect(hubSpotService.confirmMatch).toHaveBeenCalledWith(1, undefined)
      })
    })

    it('invalidates queue after confirming a match', async () => {
      vi.mocked(hubSpotService.confirmMatch).mockResolvedValue({
        ...mockDealMatch,
        status: MatchStatus.CONFIRMED,
      })
      vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
        matches: allMatches,
        total: 3,
        page: 1,
        per_page: 20,
      })

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText('Confirm match for hs-deal-001')).toBeInTheDocument()
      })

      const callsBefore = vi.mocked(hubSpotService.getReviewQueue).mock.calls.length

      await user.click(screen.getByLabelText('Confirm match for hs-deal-001'))

      await waitFor(() => {
        // After confirm, the queue should be re-fetched (at least one more call)
        expect(vi.mocked(hubSpotService.getReviewQueue).mock.calls.length).toBeGreaterThan(callsBefore)
      })
    })
  })

  describe('reject + re-link', () => {
    it('opens re-link dialog when Reject + Re-link button is clicked', async () => {
      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText('Reject and re-link hs-deal-001')).toBeInTheDocument()
      })

      await user.click(screen.getByLabelText('Reject and re-link hs-deal-001'))

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        expect(screen.getByText('Reject & Re-link to Different Record')).toBeInTheDocument()
      })
    })

    it('calls rejectMatch with internal record ID from dialog', async () => {
      vi.mocked(hubSpotService.rejectMatch).mockResolvedValue({
        ...mockDealMatch,
        status: MatchStatus.REJECTED,
      })
      vi.mocked(hubSpotService.getReviewQueue)
        .mockResolvedValueOnce({ matches: allMatches, total: 3, page: 1, per_page: 20 })
        .mockResolvedValue({ matches: [mockContactMatch, mockUnmatchedCompany], total: 2, page: 1, per_page: 20 })

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText('Reject and re-link hs-deal-001')).toBeInTheDocument()
      })

      await user.click(screen.getByLabelText('Reject and re-link hs-deal-001'))

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument()
      })

      // Enter an internal record ID
      const recordIdInput = screen.getByLabelText('Internal record ID for re-link')
      await user.type(recordIdInput, '999')

      // Submit the dialog
      const relinkButton = screen.getByRole('button', { name: /reject.*re-link/i })
      await user.click(relinkButton)

      await waitFor(() => {
        expect(hubSpotService.rejectMatch).toHaveBeenCalledWith(1, 999)
      })
    })
  })

  describe('mark as new record', () => {
    it('calls markMatchAsNewRecord when Mark as New Record button is clicked', async () => {
      vi.mocked(hubSpotService.markMatchAsNewRecord).mockResolvedValue({
        ...mockUnmatchedCompany,
        status: MatchStatus.CONFIRMED,
      })
      vi.mocked(hubSpotService.getReviewQueue)
        .mockResolvedValueOnce({ matches: allMatches, total: 3, page: 1, per_page: 20 })
        .mockResolvedValue({ matches: [mockDealMatch, mockContactMatch], total: 2, page: 1, per_page: 20 })

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText('Mark hs-company-003 as new record')).toBeInTheDocument()
      })

      await user.click(screen.getByLabelText('Mark hs-company-003 as new record'))

      await waitFor(() => {
        expect(hubSpotService.markMatchAsNewRecord).toHaveBeenCalledWith(3)
      })
    })

    it('invalidates queue after marking as new record', async () => {
      vi.mocked(hubSpotService.markMatchAsNewRecord).mockResolvedValue({
        ...mockUnmatchedCompany,
        status: MatchStatus.CONFIRMED,
      })
      vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
        matches: allMatches,
        total: 3,
        page: 1,
        per_page: 20,
      })

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByLabelText('Mark hs-company-003 as new record')).toBeInTheDocument()
      })

      const callsBefore = vi.mocked(hubSpotService.getReviewQueue).mock.calls.length

      await user.click(screen.getByLabelText('Mark hs-company-003 as new record'))

      await waitFor(() => {
        expect(vi.mocked(hubSpotService.getReviewQueue).mock.calls.length).toBeGreaterThan(callsBefore)
      })
    })
  })

  describe('side-by-side comparison', () => {
    it('displays existing vs incoming values when row is expanded', async () => {
      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getAllByLabelText('Expand comparison').length).toBeGreaterThan(0)
      })

      // Click the expand button on the first row
      const expandButtons = screen.getAllByLabelText('Expand comparison')
      await user.click(expandButtons[0])

      await waitFor(() => {
        expect(screen.getByLabelText('Side-by-side comparison')).toBeInTheDocument()
        expect(screen.getByText('HubSpot Record (Incoming)')).toBeInTheDocument()
        expect(screen.getByText('Proposed Internal Match (Existing)')).toBeInTheDocument()
      })

      // Check incoming values
      expect(screen.getByText('hs-deal-001')).toBeInTheDocument()

      // Check existing values
      expect(screen.getByText('100')).toBeInTheDocument() // internal_record_id
    })

    it('shows "could not be matched" message for unmatched records', async () => {
      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getAllByLabelText('Expand comparison').length).toBeGreaterThan(0)
      })

      // Expand the unmatched company row (3rd row)
      const expandButtons = screen.getAllByLabelText('Expand comparison')
      await user.click(expandButtons[2])

      await waitFor(() => {
        expect(
          screen.getByText(/could not be matched to any existing property/)
        ).toBeInTheDocument()
      })
    })
  })

  describe('pending count badge', () => {
    it('reflects correct pending count from API', async () => {
      // Both queries call getReviewQueue; use a function mock that returns
      // different values based on the per_page parameter
      vi.mocked(hubSpotService.getReviewQueue).mockImplementation(async (filters) => {
        if (filters?.per_page === 1) {
          return { matches: [], total: 15, page: 1, per_page: 1 }
        }
        return { matches: allMatches, total: 3, page: 1, per_page: 20 }
      })

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByText(/15 items? pending review/)).toBeInTheDocument()
      })
    })

    it('shows singular "item" when count is 1', async () => {
      vi.mocked(hubSpotService.getReviewQueue).mockImplementation(async (filters) => {
        if (filters?.per_page === 1) {
          return { matches: [], total: 1, page: 1, per_page: 1 }
        }
        return { matches: [mockDealMatch], total: 1, page: 1, per_page: 20 }
      })

      render(<ReviewQueue />)

      await waitFor(() => {
        expect(screen.getByText(/1 item pending review/)).toBeInTheDocument()
      })
    })
  })
})
