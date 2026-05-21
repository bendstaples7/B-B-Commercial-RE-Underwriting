/**
 * Tests for LogNoteForm component
 *
 * Covers:
 * - character count display
 * - validation error on empty note
 * - validation error on note exceeding 5,000 chars
 * - form preserved on server error
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LogNoteForm } from './LogNoteForm'
import type { LeadTimelineEntry } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  callLogService: {
    logNote: vi.fn(),
    logCall: vi.fn(),
  },
}))

import { callLogService } from '@/services/api'

const mockLogNote = callLogService.logNote as ReturnType<typeof vi.fn>

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeTimelineEntry(overrides: Partial<LeadTimelineEntry> = {}): LeadTimelineEntry {
  return {
    id: 1,
    lead_id: 1,
    event_type: 'note_added',
    occurred_at: '2024-01-01T00:00:00Z',
    source: 'manual',
    actor: 'user',
    summary: 'Note saved',
    metadata: null,
    hubspot_activity_id: null,
    is_deleted: false,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LogNoteForm', () => {
  // -------------------------------------------------------------------------
  // Character count display
  // -------------------------------------------------------------------------

  describe('character count display', () => {
    it('shows 0/5,000 initially', () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      expect(screen.getByTestId('note-char-count')).toHaveTextContent('0/5,000')
    })

    it('updates character count as user types', async () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.type(screen.getByTestId('note-body-input'), 'Hello')

      expect(screen.getByTestId('note-char-count')).toHaveTextContent('5/5,000')
    })

    it('shows character count over limit when text exceeds 5,000 chars', () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      const input = screen.getByTestId('note-body-input')
      fireEvent.change(input, { target: { value: 'a'.repeat(5001) } })

      const charCount = screen.getByTestId('note-char-count')
      expect(charCount).toHaveTextContent('5001/5,000')
    })
  })

  // -------------------------------------------------------------------------
  // Validation error on empty note
  // -------------------------------------------------------------------------

  describe('validation error on empty note', () => {
    it('shows validation error when Save is clicked with empty body', async () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.click(screen.getByTestId('note-save-btn'))

      expect(screen.getByText('Note cannot be empty.')).toBeInTheDocument()
    })

    it('shows validation error when body is only whitespace', async () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.type(screen.getByTestId('note-body-input'), '   ')
      await user.click(screen.getByTestId('note-save-btn'))

      expect(screen.getByText('Note cannot be empty.')).toBeInTheDocument()
    })

    it('does not call logNote when body is empty', async () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.click(screen.getByTestId('note-save-btn'))

      expect(mockLogNote).not.toHaveBeenCalled()
    })

    it('clears validation error when user starts typing', async () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.click(screen.getByTestId('note-save-btn'))
      expect(screen.getByText('Note cannot be empty.')).toBeInTheDocument()

      await user.type(screen.getByTestId('note-body-input'), 'A')
      expect(screen.queryByText('Note cannot be empty.')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Validation error on note exceeding 5,000 chars
  // -------------------------------------------------------------------------

  describe('validation error on note exceeding 5,000 chars', () => {
    it('shows validation error when note exceeds 5,000 characters', async () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      const input = screen.getByTestId('note-body-input')
      fireEvent.change(input, { target: { value: 'a'.repeat(5001) } })
      await user.click(screen.getByTestId('note-save-btn'))

      expect(
        screen.getByText('Note must be 5,000 characters or fewer.')
      ).toBeInTheDocument()
    })

    it('does not call logNote when note exceeds 5,000 characters', async () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      const input = screen.getByTestId('note-body-input')
      fireEvent.change(input, { target: { value: 'a'.repeat(5001) } })
      await user.click(screen.getByTestId('note-save-btn'))

      expect(mockLogNote).not.toHaveBeenCalled()
    })

    it('accepts a note of exactly 5,000 characters', async () => {
      const entry = makeTimelineEntry()
      mockLogNote.mockResolvedValue(entry)
      const onSaved = vi.fn()

      render(<LogNoteForm leadId={1} onSaved={onSaved} />)

      const input = screen.getByTestId('note-body-input')
      fireEvent.change(input, { target: { value: 'a'.repeat(5000) } })
      await user.click(screen.getByTestId('note-save-btn'))

      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(entry)
      })
    })
  })

  // -------------------------------------------------------------------------
  // Form preserved on server error
  // -------------------------------------------------------------------------

  describe('form preserved on server error', () => {
    it('shows inline error when logNote rejects', async () => {
      mockLogNote.mockRejectedValue(new Error('Server error'))

      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.type(screen.getByTestId('note-body-input'), 'My note')
      await user.click(screen.getByTestId('note-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('note-submit-error')).toHaveTextContent('Server error')
      })
    })

    it('preserves body text after server error', async () => {
      mockLogNote.mockRejectedValue(new Error('Server error'))

      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.type(screen.getByTestId('note-body-input'), 'My note')
      await user.click(screen.getByTestId('note-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('note-submit-error')).toBeInTheDocument()
      })

      expect(screen.getByTestId('note-body-input')).toHaveValue('My note')
    })

    it('does not call onSaved on server error', async () => {
      mockLogNote.mockRejectedValue(new Error('Server error'))
      const onSaved = vi.fn()

      render(<LogNoteForm leadId={1} onSaved={onSaved} />)

      await user.type(screen.getByTestId('note-body-input'), 'My note')
      await user.click(screen.getByTestId('note-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('note-submit-error')).toBeInTheDocument()
      })

      expect(onSaved).not.toHaveBeenCalled()
    })

    it('shows generic error message when rejection is not an Error instance', async () => {
      mockLogNote.mockRejectedValue('string error')

      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      await user.type(screen.getByTestId('note-body-input'), 'My note')
      await user.click(screen.getByTestId('note-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('note-submit-error')).toHaveTextContent(
          'Failed to save note. Please try again.'
        )
      })
    })
  })

  // -------------------------------------------------------------------------
  // Successful save
  // -------------------------------------------------------------------------

  describe('successful save', () => {
    it('calls onSaved with the returned entry', async () => {
      const entry = makeTimelineEntry()
      mockLogNote.mockResolvedValue(entry)
      const onSaved = vi.fn()

      render(<LogNoteForm leadId={1} onSaved={onSaved} />)

      await user.type(screen.getByTestId('note-body-input'), 'My note')
      await user.click(screen.getByTestId('note-save-btn'))

      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(entry)
      })
    })

    it('calls logNote with correct leadId and body', async () => {
      const entry = makeTimelineEntry()
      mockLogNote.mockResolvedValue(entry)

      render(<LogNoteForm leadId={42} onSaved={vi.fn()} />)

      await user.type(screen.getByTestId('note-body-input'), 'Test note')
      await user.click(screen.getByTestId('note-save-btn'))

      await waitFor(() => {
        expect(mockLogNote).toHaveBeenCalledWith(42, { body: 'Test note' })
      })
    })
  })

  // -------------------------------------------------------------------------
  // Cancel button
  // -------------------------------------------------------------------------

  describe('cancel button', () => {
    it('calls onCancel when Cancel is clicked', async () => {
      const onCancel = vi.fn()

      render(<LogNoteForm leadId={1} onSaved={vi.fn()} onCancel={onCancel} />)

      await user.click(screen.getByTestId('note-cancel-btn'))

      expect(onCancel).toHaveBeenCalled()
    })

    it('does not render Cancel button when onCancel is not provided', () => {
      render(<LogNoteForm leadId={1} onSaved={vi.fn()} />)

      expect(screen.queryByTestId('note-cancel-btn')).not.toBeInTheDocument()
    })
  })
})
