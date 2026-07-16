/**
 * Tests for LogCallForm component
 *
 * Covers:
 * - outcome required validation
 * - duration range validation (1–999)
 * - form preserved on server error
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LogCallForm } from './LogCallForm'
import type { LeadTask, LeadTimelineEntry } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  callLogService: {
    logNote: vi.fn(),
    logCall: vi.fn(),
    markHubSpotTaskDone: vi.fn(),
  },
}))

import { callLogService } from '@/services/api'

const mockLogCall = callLogService.logCall as ReturnType<typeof vi.fn>
const mockMarkHubSpotTaskDone = callLogService.markHubSpotTaskDone as ReturnType<typeof vi.fn>

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeTimelineEntry(overrides: Partial<LeadTimelineEntry> = {}): LeadTimelineEntry {
  return {
    id: 1,
    lead_id: 1,
    event_type: 'call_logged',
    occurred_at: '2024-01-01T00:00:00Z',
    source: 'manual',
    actor: 'user',
    summary: 'Call logged',
    metadata: null,
    hubspot_activity_id: null,
    is_deleted: false,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeOpenHubSpotTask(): LeadTask {
  return {
    id: 42,
    lead_id: 1,
    title: 'Follow up on 1726 W Roscoe St',
    task_type: 'custom',
    status: 'overdue',
    due_date: '2026-07-01',
    created_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    created_by: 'hubspot',
    source: 'hubspot',
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
// Helper: select an outcome from the MUI Select dropdown
// Uses the same pattern as LeadTimeline.test.tsx:
//   getByLabelText → fireEvent.mouseDown → getByRole('listbox') → fireEvent.click
// ---------------------------------------------------------------------------

function selectOutcome(outcomeValue: string) {
  // MUI Select's visible combobox div is associated with the label via aria-labelledby
  // getByLabelText finds it by the label text
  const selectEl = screen.getByLabelText('Outcome *')
  fireEvent.mouseDown(selectEl)

  // The listbox appears synchronously in jsdom after mouseDown
  const listbox = screen.getByRole('listbox')
  const option = listbox.querySelector(`[data-value="${outcomeValue}"]`)
  if (!option) throw new Error(`Option with data-value="${outcomeValue}" not found`)
  fireEvent.click(option)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LogCallForm', () => {
  // -------------------------------------------------------------------------
  // Outcome required validation
  // -------------------------------------------------------------------------

  describe('outcome required validation', () => {
    it('shows validation error when Save is clicked without selecting outcome', async () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      await user.click(screen.getByTestId('call-save-btn'))

      expect(screen.getByTestId('call-outcome-error')).toHaveTextContent('Outcome is required.')
    })

    it('does not call logCall when outcome is missing', async () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      await user.click(screen.getByTestId('call-save-btn'))

      expect(mockLogCall).not.toHaveBeenCalled()
    })

    it('clears outcome error when outcome is selected', async () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      await user.click(screen.getByTestId('call-save-btn'))
      expect(screen.getByTestId('call-outcome-error')).toBeInTheDocument()

      selectOutcome('answered')

      expect(screen.queryByTestId('call-outcome-error')).not.toBeInTheDocument()
    })

    it('renders all five outcome options in the dropdown', () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      const selectEl = screen.getByLabelText('Outcome *')
      fireEvent.mouseDown(selectEl)

      const listbox = screen.getByRole('listbox')
      expect(listbox.querySelector('[data-value="answered"]')).toBeInTheDocument()
      expect(listbox.querySelector('[data-value="voicemail"]')).toBeInTheDocument()
      expect(listbox.querySelector('[data-value="no_answer"]')).toBeInTheDocument()
      expect(listbox.querySelector('[data-value="busy"]')).toBeInTheDocument()
      expect(listbox.querySelector('[data-value="wrong_number"]')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Duration range validation
  // -------------------------------------------------------------------------

  describe('duration range validation', () => {
    it('shows validation error when duration is 0', () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '0' },
      })
      fireEvent.submit(screen.getByTestId('log-call-form'))

      expect(screen.getByTestId('call-duration-error')).toHaveTextContent(
        'Duration must be a whole number between 1 and 999.'
      )
    })

    it('shows validation error when duration is 1000', () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '1000' },
      })
      fireEvent.submit(screen.getByTestId('log-call-form'))

      expect(screen.getByTestId('call-duration-error')).toHaveTextContent(
        'Duration must be a whole number between 1 and 999.'
      )
    })

    it('shows validation error when duration is negative', () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '-5' },
      })
      fireEvent.submit(screen.getByTestId('log-call-form'))

      expect(screen.getByTestId('call-duration-error')).toHaveTextContent(
        'Duration must be a whole number between 1 and 999.'
      )
    })

    it('shows validation error when duration is a decimal', () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '1.5' },
      })
      fireEvent.submit(screen.getByTestId('log-call-form'))

      expect(screen.getByTestId('call-duration-error')).toHaveTextContent(
        'Duration must be a whole number between 1 and 999.'
      )
    })

    it('does not call logCall when duration is invalid', () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '0' },
      })
      fireEvent.submit(screen.getByTestId('log-call-form'))

      expect(mockLogCall).not.toHaveBeenCalled()
    })

    it('accepts duration of 1 (lower boundary)', async () => {
      const entry = makeTimelineEntry()
      mockLogCall.mockResolvedValue(entry)
      const onSaved = vi.fn()

      render(<LogCallForm leadId={1} onSaved={onSaved} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '1' },
      })
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(
          expect.objectContaining({
            id: entry.id,
            summary: entry.summary,
            event_type: entry.event_type,
          }),
          undefined,
        )
      })
    })

    it('accepts duration of 999 (upper boundary)', async () => {
      const entry = makeTimelineEntry()
      mockLogCall.mockResolvedValue(entry)
      const onSaved = vi.fn()

      render(<LogCallForm leadId={1} onSaved={onSaved} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '999' },
      })
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(
          expect.objectContaining({
            id: entry.id,
            summary: entry.summary,
            event_type: entry.event_type,
          }),
          undefined,
        )
      })
    })

    it('accepts empty duration (optional field)', async () => {
      const entry = makeTimelineEntry()
      mockLogCall.mockResolvedValue(entry)
      const onSaved = vi.fn()

      render(<LogCallForm leadId={1} onSaved={onSaved} />)

      selectOutcome('voicemail')
      // Leave duration empty
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(
          expect.objectContaining({
            id: entry.id,
            summary: entry.summary,
            event_type: entry.event_type,
          }),
          undefined,
        )
      })
      expect(mockLogCall).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ duration_minutes: null })
      )
    })
  })

  // -------------------------------------------------------------------------
  // Form preserved on server error
  // -------------------------------------------------------------------------

  describe('form preserved on server error', () => {
    it('shows inline error when logCall rejects', async () => {
      mockLogCall.mockRejectedValue(new Error('Server error'))

      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('call-submit-error')).toHaveTextContent('Server error')
      })
    })

    it('preserves outcome selection after server error', async () => {
      mockLogCall.mockRejectedValue(new Error('Server error'))

      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('voicemail')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('call-submit-error')).toBeInTheDocument()
      })

      // The select display should still show the selected value text
      expect(screen.getByTestId('call-outcome-select')).toHaveTextContent('Voicemail')
    })

    it('preserves duration after server error', async () => {
      mockLogCall.mockRejectedValue(new Error('Server error'))

      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '15' },
      })
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('call-submit-error')).toBeInTheDocument()
      })

      expect(screen.getByTestId('call-duration-input')).toHaveValue(15)
    })

    it('preserves notes after server error', async () => {
      mockLogCall.mockRejectedValue(new Error('Server error'))

      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      await user.type(screen.getByTestId('call-notes-input'), 'Call notes here')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('call-submit-error')).toBeInTheDocument()
      })

      expect(screen.getByTestId('call-notes-input')).toHaveValue('Call notes here')
    })

    it('does not call onSaved on server error', async () => {
      mockLogCall.mockRejectedValue(new Error('Server error'))
      const onSaved = vi.fn()

      render(<LogCallForm leadId={1} onSaved={onSaved} />)

      selectOutcome('answered')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('call-submit-error')).toBeInTheDocument()
      })

      expect(onSaved).not.toHaveBeenCalled()
    })

    it('shows generic error message when rejection is not an Error instance', async () => {
      mockLogCall.mockRejectedValue('string error')

      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('answered')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('call-submit-error')).toHaveTextContent(
          'Failed to log call. Please try again.'
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
      mockLogCall.mockResolvedValue(entry)
      const onSaved = vi.fn()

      render(<LogCallForm leadId={1} onSaved={onSaved} />)

      selectOutcome('answered')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(onSaved).toHaveBeenCalledWith(
          expect.objectContaining({
            id: entry.id,
            summary: entry.summary,
            event_type: entry.event_type,
          }),
          undefined,
        )
      })
    })

    it('calls logCall with correct leadId, outcome, duration, and notes', async () => {
      const entry = makeTimelineEntry()
      mockLogCall.mockResolvedValue(entry)

      render(<LogCallForm leadId={42} onSaved={vi.fn()} />)

      selectOutcome('no_answer')
      fireEvent.change(screen.getByTestId('call-duration-input'), {
        target: { value: '5' },
      })
      await user.type(screen.getByTestId('call-notes-input'), 'Left message')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(mockLogCall).toHaveBeenCalledWith(42, expect.objectContaining({
          outcome: 'no_answer',
          duration_minutes: 5,
          notes: 'Left message',
          mail_campaign_id: null,
        }))
      })
    })

    it('sends null for notes when notes field is empty', async () => {
      const entry = makeTimelineEntry()
      mockLogCall.mockResolvedValue(entry)

      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      selectOutcome('busy')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(mockLogCall).toHaveBeenCalledWith(
          1,
          expect.objectContaining({ notes: null })
        )
      })
    })
  })

  describe('open task completion', () => {
    it('shows complete-task checkbox for hubspot follow-up tasks', () => {
      render(
        <LogCallForm leadId={1} openTasks={[makeOpenHubSpotTask()]} onSaved={vi.fn()} />,
      )

      expect(screen.getByRole('checkbox', { name: /Complete task:/i })).toBeChecked()
      expect(screen.getByText(/Follow up on 1726 W Roscoe St/)).toBeInTheDocument()
      expect(screen.getByTestId('call-save-btn')).toHaveTextContent('Log call and complete task')
    })

    it('marks hubspot task done after logging call', async () => {
      const entry = makeTimelineEntry()
      mockLogCall.mockResolvedValue(entry)
      mockMarkHubSpotTaskDone.mockResolvedValue({ task_id: 42, status: 'completed' })
      const onSaved = vi.fn()

      render(
        <LogCallForm leadId={1} openTasks={[makeOpenHubSpotTask()]} onSaved={onSaved} />,
      )

      selectOutcome('answered')
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(mockLogCall).toHaveBeenCalled()
        expect(mockMarkHubSpotTaskDone).toHaveBeenCalledWith(1, 42, {
          idNamespace: 'lead_task',
        })
        expect(onSaved).toHaveBeenCalledWith(
          expect.objectContaining({ event_type: 'call_logged' }),
          { completedHubSpotTaskId: 42 },
        )
      })
    })

    it('creates follow-up task when checkbox is enabled', async () => {
      const entry = makeTimelineEntry()
      mockLogCall.mockResolvedValue(entry)
      const onSaved = vi.fn()

      render(<LogCallForm leadId={1} onSaved={onSaved} />)

      selectOutcome('voicemail')
      // Follow-up is enabled by default — pick the 3-day horizon and save.
      expect(screen.getByTestId('follow-up-3d')).toBeInTheDocument()
      await user.click(screen.getByTestId('follow-up-3d'))
      await user.click(screen.getByTestId('call-save-btn'))

      await waitFor(() => {
        expect(mockLogCall).toHaveBeenCalledWith(
          1,
          expect.objectContaining({
            follow_up: expect.objectContaining({
              title: 'Follow up call',
              task_type: 'call_owner_today',
            }),
          }),
        )
      })
    })
  })

  // -------------------------------------------------------------------------
  // Cancel button
  // -------------------------------------------------------------------------

  describe('cancel button', () => {
    it('calls onCancel when Cancel is clicked', async () => {
      const onCancel = vi.fn()

      render(<LogCallForm leadId={1} onSaved={vi.fn()} onCancel={onCancel} />)

      await user.click(screen.getByTestId('call-cancel-btn'))

      expect(onCancel).toHaveBeenCalled()
    })

    it('does not render Cancel button when onCancel is not provided', () => {
      render(<LogCallForm leadId={1} onSaved={vi.fn()} />)

      expect(screen.queryByTestId('call-cancel-btn')).not.toBeInTheDocument()
    })
  })
})
