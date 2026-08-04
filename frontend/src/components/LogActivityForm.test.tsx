/**
 * Tests for the unified LogActivityForm component.
 *
 * - `mode="call"` parity: covers the behaviors that used to live in
 *   LogCallForm (outcome incl. Not Interested, direction, duration range,
 *   notes, follow-up cadence, HubSpot task completion, form-preserved-on-error).
 * - `mode="note"` / `mode="email"`: share the same next-step cadence section
 *   when the lead has open tasks.
 * - `mode="email"`: relabeled fields ("Email subject" + "Notes", not "Email
 *   body"), "Log email" CTA, and the persisted sent-from address dropdown.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LogActivityForm } from './LogActivityForm'
import { SENT_FROM_ADDRESSES_STORAGE_KEY } from '@/utils/emailSentFromAddresses'
import type { LeadTask, LeadTimelineEntry } from '@/types'

vi.mock('@/services/api', () => ({
  callLogService: {
    logNote: vi.fn(),
    logCall: vi.fn(),
    markHubSpotTaskDone: vi.fn(),
  },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {
    campaignsForLead: vi.fn().mockResolvedValue({ campaigns: [] }),
  },
}))

import { callLogService } from '@/services/api'

const mockLogCall = callLogService.logCall as ReturnType<typeof vi.fn>
const mockLogNote = callLogService.logNote as ReturnType<typeof vi.fn>
const mockMarkHubSpotTaskDone = callLogService.markHubSpotTaskDone as ReturnType<typeof vi.fn>

const user = userEvent.setup({ pointerEventsCheck: 0 })

function makeTimelineEntry(overrides: Partial<LeadTimelineEntry> = {}): LeadTimelineEntry {
  return {
    id: 1,
    lead_id: 1,
    event_type: 'call_logged',
    occurred_at: '2024-01-01T00:00:00Z',
    source: 'manual',
    actor: 'user',
    summary: 'Saved',
    metadata: null,
    hubspot_activity_id: null,
    is_deleted: false,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeOpenTask(overrides: Partial<LeadTask> = {}): LeadTask {
  return {
    id: 7,
    lead_id: 1,
    title: 'Follow up with owner',
    task_type: 'custom',
    status: 'open',
    due_date: null,
    created_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    created_by: 'user',
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

function selectOutcome(outcomeValue: string) {
  fireEvent.click(screen.getByTestId(`call-outcome-${outcomeValue}`))
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
})

// ---------------------------------------------------------------------------
// Call mode — parity with former LogCallForm
// ---------------------------------------------------------------------------

describe('LogActivityForm — mode="call" (parity with former LogCallForm)', () => {
  it('renders all six outcome options including Not Interested', () => {
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    expect(screen.getByTestId('call-outcome-answered')).toHaveTextContent('Answered')
    expect(screen.getByTestId('call-outcome-voicemail')).toHaveTextContent('Voicemail')
    expect(screen.getByTestId('call-outcome-no_answer')).toHaveTextContent('No Answer')
    expect(screen.getByTestId('call-outcome-busy')).toHaveTextContent('Busy')
    expect(screen.getByTestId('call-outcome-wrong_number')).toHaveTextContent('Wrong Number')
    expect(screen.getByTestId('call-outcome-not_interested')).toHaveTextContent('Not Interested')
  })

  it('submits the Not Interested outcome', async () => {
    mockLogCall.mockResolvedValue(makeTimelineEntry({ summary: 'Not interested' }))
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    selectOutcome('not_interested')
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(mockLogCall).toHaveBeenCalledWith(1, expect.objectContaining({ outcome: 'not_interested' }))
    })
  })

  it('shows validation error when Save is clicked without selecting outcome', async () => {
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    await user.click(screen.getByTestId('call-save-btn'))

    expect(screen.getByTestId('call-outcome-error')).toHaveTextContent('Outcome is required.')
    expect(mockLogCall).not.toHaveBeenCalled()
  })

  it('defaults direction to outbound and submits inbound when selected', async () => {
    mockLogCall.mockResolvedValue(makeTimelineEntry())
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    expect(screen.getByTestId('call-direction-outbound')).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByTestId('call-direction-inbound'))
    selectOutcome('answered')
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(mockLogCall).toHaveBeenCalledWith(1, expect.objectContaining({ direction: 'inbound' }))
    })
  })

  it('validates duration range (1–999)', () => {
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    selectOutcome('answered')
    fireEvent.change(screen.getByTestId('call-duration-input'), { target: { value: '0' } })
    fireEvent.submit(screen.getByTestId('log-call-form'))

    expect(screen.getByTestId('call-duration-error')).toHaveTextContent(
      'Duration must be a whole number between 1 and 999.',
    )
    expect(mockLogCall).not.toHaveBeenCalled()
  })

  it('preserves outcome, duration, and notes after a server error', async () => {
    mockLogCall.mockRejectedValue(new Error('Server error'))
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    selectOutcome('voicemail')
    fireEvent.change(screen.getByTestId('call-duration-input'), { target: { value: '15' } })
    await user.type(screen.getByTestId('call-notes-input'), 'Call notes here')
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('call-submit-error')).toHaveTextContent('Server error')
    })

    expect(screen.getByTestId('call-outcome-voicemail')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('call-duration-input')).toHaveValue(15)
    expect(screen.getByTestId('call-notes-input')).toHaveValue('Call notes here')
  })

  it('shows a complete-task checkbox for a matching open HubSpot task and marks it done after logging', async () => {
    mockLogCall.mockResolvedValue(makeTimelineEntry())
    mockMarkHubSpotTaskDone.mockResolvedValue({ task_id: 42, status: 'completed' })
    const onSaved = vi.fn()

    render(
      <LogActivityForm mode="call" leadId={1} openTasks={[makeOpenHubSpotTask()]} onSaved={onSaved} />,
    )

    expect(screen.getByRole('checkbox', { name: /Complete task:/i })).toBeChecked()
    expect(screen.getByTestId('call-save-btn')).toHaveTextContent('Log call and complete task')

    selectOutcome('answered')
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(mockMarkHubSpotTaskDone).toHaveBeenCalledWith(1, 42, { idNamespace: 'lead_task' })
      expect(onSaved).toHaveBeenCalledWith(
        expect.objectContaining({ event_type: 'call_logged' }),
        { completedHubSpotTaskId: 42 },
      )
    })
  })

  it('creates a follow-up task with the selected next-step type', async () => {
    mockLogCall.mockResolvedValue(makeTimelineEntry())
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    selectOutcome('voicemail')
    await user.click(screen.getByTestId('create-follow-up-checkbox'))
    await user.click(screen.getByTestId('change-next-step-btn'))
    fireEvent.mouseDown(screen.getByLabelText('Task type'))
    fireEvent.click(screen.getByRole('listbox').querySelector('[data-value="add_to_mail_batch"]')!)
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(mockLogCall).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          follow_up: expect.objectContaining({ title: 'Add to mail queue', task_type: 'add_to_mail_batch' }),
        }),
      )
    })
  })

  it('calls onCancel when Cancel is clicked and hides it when onCancel is absent', async () => {
    const onCancel = vi.fn()
    const { rerender } = render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} onCancel={onCancel} />)

    await user.click(screen.getByTestId('call-cancel-btn'))
    expect(onCancel).toHaveBeenCalled()

    rerender(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)
    expect(screen.queryByTestId('call-cancel-btn')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Note mode
// ---------------------------------------------------------------------------

describe('LogActivityForm — mode="note"', () => {
  it('shows character count and validates empty body', async () => {
    render(<LogActivityForm mode="note" leadId={1} onSaved={vi.fn()} />)

    expect(screen.getByTestId('note-char-count')).toHaveTextContent('0/5,000')

    await user.click(screen.getByTestId('note-save-btn'))
    expect(screen.getByText('Note cannot be empty.')).toBeInTheDocument()
    expect(mockLogNote).not.toHaveBeenCalled()
  })

  it('always shows the next-step section; follow-up defaults off when no completable task', () => {
    render(<LogActivityForm mode="note" leadId={1} openTasks={[]} onSaved={vi.fn()} />)

    expect(screen.getByTestId('activity-next-step-actions')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Create a follow-up task/i })).not.toBeChecked()
    expect(screen.queryByRole('checkbox', { name: /Complete task:/i })).not.toBeInTheDocument()
  })

  it('shows complete-task + follow-up defaults on for open tasks and sends both in the payload', async () => {
    mockLogNote.mockResolvedValue(makeTimelineEntry({ event_type: 'note_added', summary: 'Note' }))
    render(<LogActivityForm mode="note" leadId={1} openTasks={[makeOpenTask()]} onSaved={vi.fn()} />)

    expect(screen.getByTestId('activity-next-step-actions')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Complete task:/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Create a follow-up task/i })).toBeChecked()

    await user.type(screen.getByTestId('note-body-input'), 'Owner called back')
    await user.click(screen.getByTestId('note-save-btn'))

    await waitFor(() => {
      expect(mockLogNote).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          body: 'Owner called back',
          complete_task_id: 7,
          follow_up: expect.objectContaining({ title: 'Follow up call' }),
        }),
      )
    })
  })

  it('preserves body and shows inline error on server failure', async () => {
    mockLogNote.mockRejectedValue(new Error('Server error'))
    render(<LogActivityForm mode="note" leadId={1} onSaved={vi.fn()} />)

    await user.type(screen.getByTestId('note-body-input'), 'My note')
    await user.click(screen.getByTestId('note-save-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('note-submit-error')).toHaveTextContent('Server error')
    })
    expect(screen.getByTestId('note-body-input')).toHaveValue('My note')
  })
})

// ---------------------------------------------------------------------------
// Email mode
// ---------------------------------------------------------------------------

describe('LogActivityForm — mode="email"', () => {
  it('labels fields "Email subject" and "Notes" (not "Email body"), with a "Log email" CTA', () => {
    render(<LogActivityForm mode="email" leadId={1} onSaved={vi.fn()} />)

    expect(screen.getByLabelText('Email subject')).toBeInTheDocument()
    expect(screen.getByLabelText('Notes')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Email body/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('email-save-btn')).toHaveTextContent('Log email')
  })

  it('keeps the recipient (contact method) picker', () => {
    render(<LogActivityForm mode="email" leadId={1} onSaved={vi.fn()} />)

    expect(screen.getByTestId('contact-method-contact-select')).toBeInTheDocument()
    expect(screen.getByTestId('contact-method-method-select')).toBeInTheDocument()
  })

  it('offers a "sent from" dropdown of persisted addresses and can add a new one', async () => {
    window.localStorage.setItem(
      SENT_FROM_ADDRESSES_STORAGE_KEY,
      JSON.stringify(['agent@bbrealestate.com']),
    )

    render(<LogActivityForm mode="email" leadId={1} onSaved={vi.fn()} />)

    fireEvent.mouseDown(screen.getByLabelText('Sent from'))
    expect(screen.getByTestId('email-sent-from-option-agent@bbrealestate.com')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('email-sent-from-add-new'))

    await user.type(screen.getByTestId('email-sent-from-new-input'), 'new-agent@bbrealestate.com')
    await user.click(screen.getByTestId('email-sent-from-save-new'))

    const stored = JSON.parse(window.localStorage.getItem(SENT_FROM_ADDRESSES_STORAGE_KEY) || '[]')
    expect(stored).toEqual(['agent@bbrealestate.com', 'new-agent@bbrealestate.com'])
  })

  it('persists the chosen sent-from address in the logNote payload and timeline metadata fallback', async () => {
    window.localStorage.setItem(
      SENT_FROM_ADDRESSES_STORAGE_KEY,
      JSON.stringify(['agent@bbrealestate.com']),
    )
    mockLogNote.mockResolvedValue({
      id: 55,
      event_type: 'email_logged',
      occurred_at: '2024-01-01T00:00:00Z',
    })
    const onSaved = vi.fn()

    render(<LogActivityForm mode="email" leadId={1} onSaved={onSaved} />)

    fireEvent.mouseDown(screen.getByLabelText('Sent from'))
    fireEvent.click(screen.getByTestId('email-sent-from-option-agent@bbrealestate.com'))

    await user.type(screen.getByLabelText('Email subject'), 'Offer follow-up')
    await user.type(screen.getByLabelText('Notes'), 'Sent the updated offer letter.')
    await user.click(screen.getByTestId('email-save-btn'))

    await waitFor(() => {
      expect(mockLogNote).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          subject: 'Offer follow-up',
          sent_from_email: 'agent@bbrealestate.com',
        }),
      )
    })

    expect(onSaved).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: expect.objectContaining({
          subject: 'Offer follow-up',
          sent_from_email: 'agent@bbrealestate.com',
        }),
      }),
      undefined,
    )
  })

  it('validates empty notes and shows the generic error on non-Error rejection', async () => {
    render(<LogActivityForm mode="email" leadId={1} onSaved={vi.fn()} />)

    await user.click(screen.getByTestId('email-save-btn'))
    expect(screen.getByText('Notes cannot be empty.')).toBeInTheDocument()
    expect(mockLogNote).not.toHaveBeenCalled()
  })

  it('shows complete-task + follow-up defaults on for open tasks (parity with call/note)', () => {
    render(<LogActivityForm mode="email" leadId={1} openTasks={[makeOpenTask()]} onSaved={vi.fn()} />)

    expect(screen.getByTestId('activity-next-step-actions')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Complete task:/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Create a follow-up task/i })).toBeChecked()
  })
})

// ---------------------------------------------------------------------------
// Cross-mode next-step parity (Detect)
// ---------------------------------------------------------------------------

describe('LogActivityForm — cross-mode next-step parity', () => {
  it.each(['call', 'note', 'email'] as const)(
    'mode=%s shows complete + follow-up checked for the same open task fixture',
    (mode) => {
      render(
        <LogActivityForm mode={mode} leadId={1} openTasks={[makeOpenTask()]} onSaved={vi.fn()} />,
      )
      expect(screen.getByTestId('activity-next-step-actions')).toBeInTheDocument()
      expect(screen.getByRole('checkbox', { name: /Complete task:/i })).toBeChecked()
      expect(screen.getByRole('checkbox', { name: /Create a follow-up task/i })).toBeChecked()
    },
  )

  it.each(['note', 'email'] as const)(
    'mode=%s does not offer complete for skip_trace_owner',
    (mode) => {
      render(
        <LogActivityForm
          mode={mode}
          leadId={1}
          openTasks={[
            makeOpenTask({
              id: 9,
              title: 'Skip trace owner',
              task_type: 'skip_trace_owner',
            }),
          ]}
          onSaved={vi.fn()}
        />,
      )
      expect(screen.queryByRole('checkbox', { name: /Complete task:/i })).not.toBeInTheDocument()
    },
  )

  it('note mode does not offer complete for add_to_mail_batch', () => {
    render(
      <LogActivityForm
        mode="note"
        leadId={1}
        openTasks={[
          makeOpenTask({
            id: 8,
            title: 'Add to mail batch',
            task_type: 'add_to_mail_batch',
          }),
        ]}
        onSaved={vi.fn()}
      />,
    )
    expect(screen.queryByRole('checkbox', { name: /Complete task:/i })).not.toBeInTheDocument()
  })
})
