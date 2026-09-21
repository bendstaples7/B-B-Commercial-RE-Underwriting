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
import { createRef } from 'react'
import { LogActivityForm, type LogActivityFormHandle } from './LogActivityForm'
import { SENT_FROM_ADDRESSES_STORAGE_KEY } from '@/utils/emailSentFromAddresses'
import type { LeadTask, LeadTimelineEntry, PropertyContact } from '@/types'

vi.mock('@/services/api', () => ({
  callLogService: {
    logNote: vi.fn(),
    logCall: vi.fn(),
    markHubSpotTaskDone: vi.fn(),
  },
  leadTaskService: {
    updateTask: vi.fn(),
  },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {
    campaignsForLead: vi.fn().mockResolvedValue({ campaigns: [] }),
  },
}))

vi.mock('@/services/channelRoiApi', () => ({
  default: {
    getSettings: vi.fn().mockResolvedValue({
      meta_connected: false,
      meta_ad_account_id: null,
      has_meta_token: false,
      expected_profit_per_deal: null,
      assumed_close_rate: null,
      last_synced_at: null,
      last_sync_error: null,
    }),
    listFacebookCampaigns: vi.fn().mockResolvedValue({ campaigns: [] }),
    getDashboard: vi.fn(),
    patchSettings: vi.fn(),
    syncFacebook: vi.fn(),
  },
}))

import { callLogService, leadTaskService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'

const mockLogCall = callLogService.logCall as ReturnType<typeof vi.fn>
const mockLogNote = callLogService.logNote as ReturnType<typeof vi.fn>
const mockMarkHubSpotTaskDone = callLogService.markHubSpotTaskDone as ReturnType<typeof vi.fn>
const mockUpdateTask = leadTaskService.updateTask as ReturnType<typeof vi.fn>

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
  vi.mocked(openLetterService.campaignsForLead).mockResolvedValue({ campaigns: [] })
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

  it('preselects the recent mailer when an inbound call is logged', async () => {
    vi.mocked(openLetterService.campaignsForLead).mockResolvedValue({
      campaigns: [{
        id: 77,
        status: 'submitted',
        lead_count: 40,
        response_count: 0,
        created_by: 'user',
        template_name: 'Yellow letter',
        submitted_at: '2026-09-01T12:00:00Z',
      }],
    })
    mockLogCall.mockResolvedValue(makeTimelineEntry())
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    fireEvent.click(screen.getByTestId('call-direction-inbound'))
    await waitFor(() => {
      expect(screen.getByTestId('mail-response-source')).toBeInTheDocument()
    })
    expect(screen.getByTestId('mail-response-source-77')).toBeChecked()

    selectOutcome('answered')
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(mockLogCall).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ direction: 'inbound', mail_campaign_id: 77 }),
      )
    })
  })

  it('sends no mailer when the inbound call is marked not from a mailer', async () => {
    vi.mocked(openLetterService.campaignsForLead).mockResolvedValue({
      campaigns: [{
        id: 77,
        status: 'submitted',
        lead_count: 40,
        response_count: 0,
        created_by: 'user',
        template_name: 'Yellow letter',
        submitted_at: '2026-09-01T12:00:00Z',
      }],
    })
    mockLogCall.mockResolvedValue(makeTimelineEntry())
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    fireEvent.click(screen.getByTestId('call-direction-inbound'))
    await waitFor(() => {
      expect(screen.getByTestId('mail-response-source-none')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('mail-response-source-none'))
    selectOutcome('answered')
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(mockLogCall).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ direction: 'inbound', mail_campaign_id: null }),
      )
    })
  })

  it('blocks inbound save when recent mailers fail to load', async () => {
    vi.mocked(openLetterService.campaignsForLead).mockRejectedValue(new Error('mailer offline'))
    render(<LogActivityForm mode="call" leadId={1} onSaved={vi.fn()} />)

    fireEvent.click(screen.getByTestId('call-direction-inbound'))
    selectOutcome('answered')
    await waitFor(() => {
      expect(openLetterService.campaignsForLead).toHaveBeenCalled()
    })
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('call-submit-error')).toHaveTextContent(
        'Could not load recent mailers',
      )
    })
    expect(mockLogCall).not.toHaveBeenCalled()
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

  it('ties an inbound text to the recent mailer when confirmed', async () => {
    vi.mocked(openLetterService.campaignsForLead).mockResolvedValue({
      campaigns: [{
        id: 88,
        status: 'submitted',
        lead_count: 8,
        response_count: 0,
        created_by: 'user',
        template_name: 'Yellow letter',
        submitted_at: '2026-09-01T12:00:00Z',
      }],
    })
    mockLogNote.mockResolvedValue(makeTimelineEntry({ event_type: 'note_added', summary: 'Inbound text' }))
    render(<LogActivityForm mode="note" leadId={1} onSaved={vi.fn()} />)

    fireEvent.click(screen.getByTestId('inbound-text-yes'))
    await waitFor(() => {
      expect(screen.getByTestId('mail-response-source-88')).toBeChecked()
    })
    await user.type(screen.getByTestId('note-body-input'), 'Got the letter')
    await user.click(screen.getByTestId('note-save-btn'))

    await waitFor(() => {
      expect(mockLogNote).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          body: 'Got the letter',
          activity_kind: 'text',
          mail_campaign_id: 88,
        }),
      )
    })
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

describe('LogActivityForm — mode="meeting"', () => {
  it('shows meeting notes, contact picker without a phone/email method, and Log meeting CTA', () => {
    render(<LogActivityForm mode="meeting" leadId={1} onSaved={vi.fn()} />)

    expect(screen.getByTestId('log-meeting-form')).toBeInTheDocument()
    expect(screen.getByLabelText('Meeting notes')).toBeInTheDocument()
    expect(screen.getByTestId('contact-method-contact-select')).toBeInTheDocument()
    expect(screen.queryByTestId('contact-method-method-select')).not.toBeInTheDocument()
    expect(screen.getByTestId('meeting-save-btn')).toHaveTextContent('Log meeting')
  })

  it('validates empty notes', async () => {
    render(<LogActivityForm mode="meeting" leadId={1} onSaved={vi.fn()} />)

    await user.click(screen.getByTestId('meeting-save-btn'))
    expect(screen.getByText('Notes cannot be empty.')).toBeInTheDocument()
    expect(mockLogNote).not.toHaveBeenCalled()
  })

  it('sends activity_kind=meeting on save', async () => {
    mockLogNote.mockResolvedValue(makeTimelineEntry({ event_type: 'meeting_logged', summary: 'Meeting: Coffee' }))
    const onSaved = vi.fn()
    render(<LogActivityForm mode="meeting" leadId={1} onSaved={onSaved} />)

    await user.type(screen.getByTestId('meeting-notes-input'), 'Had coffee downtown')
    await user.click(screen.getByTestId('meeting-save-btn'))

    await waitFor(() => {
      expect(mockLogNote).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          body: 'Had coffee downtown',
          activity_kind: 'meeting',
        }),
      )
    })
    expect(onSaved).toHaveBeenCalledWith(
      expect.objectContaining({ event_type: 'meeting_logged' }),
      undefined,
    )
  })

  it('includes contact_id in the logNote payload when a contact is selected', async () => {
    mockLogNote.mockResolvedValue(makeTimelineEntry({ event_type: 'meeting_logged', summary: 'Meeting: Coffee' }))
    const contacts: PropertyContact[] = [
      {
        id: 42,
        first_name: 'Alice',
        last_name: 'Owner',
        role: 'owner',
        role_description: null,
        notes: null,
        phones: [],
        emails: [],
        created_at: null,
        updated_at: null,
        property_contact_role: 'owner',
        is_primary: true,
      },
    ]
    render(<LogActivityForm mode="meeting" leadId={1} contacts={contacts} onSaved={vi.fn()} />)

    fireEvent.mouseDown(screen.getByRole('combobox', { name: /contact/i }))
    fireEvent.click(await screen.findByRole('option', { name: /Alice Owner/ }))
    await user.type(screen.getByTestId('meeting-notes-input'), 'Had coffee downtown')
    await user.click(screen.getByTestId('meeting-save-btn'))

    await waitFor(() => {
      expect(mockLogNote).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          body: 'Had coffee downtown',
          activity_kind: 'meeting',
          contact_id: 42,
        }),
      )
    })
  })

  it('focuses the meeting notes input from the imperative handle', () => {
    const ref = createRef<LogActivityFormHandle>()
    render(<LogActivityForm ref={ref} mode="meeting" leadId={1} onSaved={vi.fn()} />)
    ref.current?.focus()
    expect(screen.getByTestId('meeting-notes-input')).toHaveFocus()
  })
})

// ---------------------------------------------------------------------------
// Cross-mode next-step parity (Detect)
// ---------------------------------------------------------------------------

describe('LogActivityForm — cross-mode next-step parity', () => {
  it.each(['call', 'note', 'email', 'meeting'] as const)(
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

  it.each(['note', 'email', 'meeting'] as const)(
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

describe('LogActivityForm — edit-task overlay', () => {
  it('prefills the original note, phone, and due date', () => {
    render(
      <LogActivityForm
        mode="note"
        leadId={1}
        editTask={{
          task: makeOpenTask({
            title: 'Follow up with Bob',
            due_date: '2026-09-20',
          }),
          note: 'Left voicemail yesterday',
          phoneDigits: '5551234567',
        }}
        onSaved={vi.fn()}
        onTaskUpdated={vi.fn()}
      />,
    )

    expect(screen.getByTestId('edit-task-form')).toBeInTheDocument()
    expect(screen.getByTestId('edit-task-context-hint')).toBeInTheDocument()
    expect(screen.getByTestId('note-body-input')).toHaveValue('Left voicemail yesterday')
    expect(screen.getByTestId('contact-method-other-input')).toHaveValue('5551234567')
    expect(screen.getByTestId('follow-up-custom-date')).toHaveValue('2026-09-20')
    expect(screen.getByTestId('next-step-custom-title')).toHaveValue('Follow up with Bob')
    expect(screen.queryByRole('checkbox', { name: /Complete task:/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /Create a follow-up task/i })).not.toBeInTheDocument()
  })

  it('saves a new due date via updateTask without logging a new note', async () => {
    mockUpdateTask.mockResolvedValue({
      id: 7,
      title: 'Follow up with Bob',
      status: 'open',
      due_date: '2026-09-22',
    })
    const onTaskUpdated = vi.fn()

    render(
      <LogActivityForm
        mode="note"
        leadId={1}
        editTask={{
          task: makeOpenTask({
            title: 'Follow up with Bob',
            due_date: '2026-09-20',
          }),
          note: 'Left voicemail yesterday',
          phoneDigits: '5551234567',
        }}
        onSaved={vi.fn()}
        onTaskUpdated={onTaskUpdated}
      />,
    )

    const dateInput = screen.getByTestId('follow-up-custom-date')
    fireEvent.change(dateInput, { target: { value: '2026-09-22' } })
    await user.click(screen.getByTestId('edit-task-save-btn'))

    await waitFor(() => {
      expect(mockUpdateTask).toHaveBeenCalledWith(1, 7, { due_date: '2026-09-22' })
    })
    expect(mockLogNote).not.toHaveBeenCalled()
    expect(onTaskUpdated).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7, due_date: '2026-09-22' }),
    )
  })
})
