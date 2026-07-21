/**
 * Tests for RecommendedActionPanel component
 *
 * Covers:
 * - renders RA label, explanation, and action buttons
 * - shows inline error on action failure without changing RA
 * - DNC badge shown and outreach buttons disabled when leadStatus='do_not_contact'
 * - create_task RA shows inline CTA when no open tasks
 * - create_task RA does NOT show inline CTA when open tasks exist
 * - no RA renders fallback message
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { RecommendedActionPanel } from './RecommendedActionPanel'
import type { RecommendedActionMeta, LeadTask } from '@/types'
import { formatDateOnly } from '@/utils/helpers'

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeRA(
  value: RecommendedActionMeta['value'],
  label = 'Test Label',
  explanation = 'Test explanation for this recommended action.'
): RecommendedActionMeta {
  return { value, label, explanation, signals: {} }
}

function makeTask(id: number, overrides: Partial<LeadTask> = {}): LeadTask {
  return {
    id,
    lead_id: 1,
    task_type: 'custom',
    title: `Task ${id}`,
    status: 'open',
    due_date: null,
    created_at: '2024-01-01T00:00:00Z',
    completed_at: null,
    created_by: 'user',
    source: 'native',
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

describe('RecommendedActionPanel', () => {
  describe('renders label, explanation, and buttons', () => {
    it('renders the RA label', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now', 'Follow Up Now', 'Reach out now.')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-label')).toHaveTextContent('Follow Up Now')
    })

    it('renders the RA explanation', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now', 'Follow Up Now', 'Reach out now to keep the conversation warm.')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-explanation')).toHaveTextContent(
        'Reach out now to keep the conversation warm.'
      )
    })

    it('renders action buttons for follow_up_now RA', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-universal-btn-log_call')).toBeInTheDocument()
      expect(screen.getByTestId('ra-universal-btn-log_note')).toBeInTheDocument()
      expect(screen.getByTestId('ra-action-btn-create_task')).toBeInTheDocument()
    })

    it('renders action buttons for enrich_data RA', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-universal-btn-move_to_skip_trace')).toBeInTheDocument()
      expect(screen.getByTestId('ra-action-btn-add_contact_info')).toBeInTheDocument()
      expect(screen.getByTestId('ra-action-btn-research_property')).toBeInTheDocument()
    })

    it('shows winning rule caption when provided', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={{
            ...makeRA('enrich_data', 'Enrich Data', 'Fill gaps that block scoring.'),
            winning_rule: 'tier_d',
            winning_rule_label:
              'Lead score is Tier D — add property and contact data to improve the score',
          }}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-winning-rule')).toHaveTextContent(
        'Why this next step: Lead score is Tier D',
      )
    })

    it('renders action buttons for analyze_property RA', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('analyze_property')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-action-btn-run_analysis')).toBeInTheDocument()
    })

    it('renders Run Analysis on follow_up_now RA', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-action-btn-run_analysis')).toBeInTheDocument()
    })

    it('renders Run Analysis on ready_for_outreach RA', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('ready_for_outreach')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-action-btn-run_analysis')).toBeInTheDocument()
    })

    it('renders outreach contact callout when outreach_contact is present and showOutreachContact', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={{
            ...makeRA('follow_up_now', 'Call Now', 'Reach out now.'),
            recommended_contact_method: 'phone',
            outreach_contact: {
              channel: 'phone',
              label: 'Call',
              value: '5551234567',
              display: '(555) 123-4567',
              href: 'tel:+15551234567',
            },
          }}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          showOutreachContact
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('outreach-contact-inline')).toBeInTheDocument()
      expect(screen.getByTestId('outreach-contact-link')).toHaveTextContent('(555) 123-4567')
      expect(screen.queryByTestId('outreach-contact-callout')).not.toBeInTheDocument()
    })

    it('does not render outreach contact when showOutreachContact is false', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={{
            ...makeRA('follow_up_now', 'Call Now', 'Reach out now.'),
            outreach_contact: {
              channel: 'phone',
              label: 'Call',
              value: '5551234567',
              display: '(555) 123-4567',
              href: 'tel:+15551234567',
            },
          }}
          leadStatus="mailing_no_contact_made"
          openTasks={[makeTask(1)]}
          showOutreachContact={false}
          onAction={vi.fn()}
        />
      )

      expect(screen.queryByTestId('outreach-contact-inline')).not.toBeInTheDocument()
    })

    it('calls onAction with the correct action string when a button is clicked', async () => {
      const onAction = vi.fn().mockResolvedValue(undefined)

      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('analyze_property')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={onAction}
        />
      )

      await user.click(screen.getByTestId('ra-action-btn-run_analysis'))

      await waitFor(() => {
        expect(onAction).toHaveBeenCalledWith('run_analysis')
      })
    })

    it('renders fallback message when recommendedAction is null', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={null}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByText('No recommended action at this time.')).toBeInTheDocument()
    })

    it('renders fallback message when recommendedAction.value is null', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={{ value: null, label: null, explanation: null, signals: {} }}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByText('No recommended action at this time.')).toBeInTheDocument()
    })

    it('hides nurture heading when open tasks exist (task lives in Open Tasks)', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('nurture', 'Nurture')}
          leadStatus="mailing_no_contact_made"
          openTasks={[{ ...makeTask(1), title: 'Manually skip trace returned letter' }]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.queryByTestId('ra-label')).not.toBeInTheDocument()
      expect(screen.queryByText('Follow up on next task')).not.toBeInTheDocument()
    })

    it('keeps RA explanation visible for skip-trace nurture without Follow up heading', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA(
            'nurture',
            'Nurture',
            'Because of a recent sale, the owner and mailing details on file are likely tied to the prior owner.',
          )}
          leadStatus="skip_trace"
          openTasks={[{ ...makeTask(1), title: 'Awaiting skip trace', task_type: 'skip_trace_owner' }]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.queryByTestId('ra-label')).not.toBeInTheDocument()
      expect(screen.queryByText('Follow up on next task')).not.toBeInTheDocument()
      expect(screen.getByTestId('ra-explanation')).toHaveTextContent('recent sale')
    })

    it('shows open task title when no recommended action exists', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={null}
          leadStatus="mailing_no_contact_made"
          openTasks={[makeTask(2)]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.queryByText('Follow up on next task')).not.toBeInTheDocument()
      expect(screen.getByTestId('ra-next-task-title')).toHaveTextContent('Task 2')
    })

    it('offers Move to Skip Trace as a standardized quick action', async () => {
      const onAction = vi.fn().mockResolvedValue(undefined)
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[makeTask(3)]}
          onAction={onAction}
        />,
      )

      await user.click(screen.getByTestId('ra-universal-btn-move_to_skip_trace'))
      expect(onAction).toHaveBeenCalledWith('move_to_skip_trace')
    })

    it.each([
      'deprioritize',
      'deal_won',
      'deal_lost',
      'suppressed',
      'do_not_contact',
    ] as const)('grays out Move to Skip Trace for status %s', (leadStatus) => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data')}
          leadStatus={leadStatus}
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-move_to_skip_trace')).toBeDisabled()
    })

    it('exposes disabled Move to Skip Trace reason to keyboard users', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data')}
          leadStatus="suppressed"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      const reason = screen.getByRole('group', {
        name: /Move to Skip Trace:/i,
      })
      expect(reason).toHaveAttribute('tabindex', '0')
      expect(screen.getByTestId('ra-universal-btn-move_to_skip_trace')).toBeDisabled()
    })

    it.each([
      ['skip_trace', 'In Skip Trace'],
    ] as const)('shows already-done skip-trace control for status %s', (leadStatus, label) => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data')}
          leadStatus={leadStatus}
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      const btn = screen.getByTestId('ra-universal-btn-already-skip-trace')
      expect(btn).toBeDisabled()
      expect(btn).toHaveTextContent(label)
      expect(screen.queryByTestId('ra-universal-btn-move_to_skip_trace')).not.toBeInTheDocument()
    })

    it('keeps Move to Skip Trace enabled for awaiting_skip_trace', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data')}
          leadStatus="awaiting_skip_trace"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-move_to_skip_trace')).toBeEnabled()
      expect(screen.queryByTestId('ra-universal-btn-already-skip-trace')).not.toBeInTheDocument()
    })

    it('keeps real RA label when open skip_trace_owner exists (no Follow up framing)', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('call_ready', 'Call Now')}
          leadStatus="awaiting_skip_trace"
          openTasks={[
            makeTask(1, {
              task_type: 'skip_trace_owner',
              title: 'Recent-sale hold ended — verify new owner',
            }),
          ]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-label')).toHaveTextContent('Call Now')
      expect(screen.queryByText('Follow up on next task')).not.toBeInTheDocument()
      expect(screen.queryByTestId('ra-next-task-title')).not.toBeInTheDocument()
    })

    it('keeps Quick actions in a fixed order across leads', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('mail_ready', 'Ready to Mail')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      const buttons = Array.from(
        screen.getByTestId('ra-universal-actions').querySelectorAll('button'),
      ).map((btn) => btn.getAttribute('data-testid'))

      expect(buttons).toEqual([
        'ra-universal-btn-log_call',
        'ra-universal-btn-log_note',
        'ra-universal-btn-log_email',
        'ra-universal-btn-add_to_mail_batch',
        'ra-universal-btn-move_to_skip_trace',
      ])
    })
  })

  describe('inline error on action failure', () => {
    it('shows inline error when onAction rejects', async () => {
      const onAction = vi.fn().mockRejectedValue(new Error('Server error'))

      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('analyze_property')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={onAction}
        />
      )

      await user.click(screen.getByTestId('ra-action-btn-run_analysis'))

      await waitFor(() => {
        expect(screen.getByTestId('ra-action-error')).toHaveTextContent('Server error')
      })
    })

    it('still shows RA label and explanation after action failure', async () => {
      const onAction = vi.fn().mockRejectedValue(new Error('Server error'))

      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('analyze_property', 'Analyze Property', 'Run an analysis.')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={onAction}
        />
      )

      await user.click(screen.getByTestId('ra-action-btn-run_analysis'))

      await waitFor(() => {
        expect(screen.getByTestId('ra-action-error')).toBeInTheDocument()
      })

      // RA label and explanation remain unchanged
      expect(screen.getByTestId('ra-label')).toHaveTextContent('Analyze Property')
      expect(screen.getByTestId('ra-explanation')).toHaveTextContent('Run an analysis.')
    })

    it('shows generic error message when onAction rejects with non-Error', async () => {
      const onAction = vi.fn().mockRejectedValue('string error')

      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('analyze_property')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={onAction}
        />
      )

      await user.click(screen.getByTestId('ra-action-btn-run_analysis'))

      await waitFor(() => {
        expect(screen.getByTestId('ra-action-error')).toHaveTextContent(
          'Action failed. Please try again.'
        )
      })
    })

    it('clears error when close button on alert is clicked', async () => {
      const onAction = vi.fn().mockRejectedValue(new Error('Server error'))

      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('analyze_property')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={onAction}
        />
      )

      await user.click(screen.getByTestId('ra-action-btn-run_analysis'))

      await waitFor(() => {
        expect(screen.getByTestId('ra-action-error')).toBeInTheDocument()
      })

      // Close the alert
      const closeButton = screen.getByRole('button', { name: /close/i })
      await user.click(closeButton)

      await waitFor(() => {
        expect(screen.queryByTestId('ra-action-error')).not.toBeInTheDocument()
      })
    })
  })

  describe('DNC badge and disabled outreach buttons', () => {
    it('shows DNC badge when leadStatus is do_not_contact', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="do_not_contact"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('dnc-badge')).toBeInTheDocument()
      expect(screen.getByTestId('dnc-badge')).toHaveTextContent('DO NOT CONTACT')
    })

    it('does NOT show DNC badge when leadStatus is active', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.queryByTestId('dnc-badge')).not.toBeInTheDocument()
    })

    it('disables outreach buttons (log_call, log_email) when leadStatus is do_not_contact', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="do_not_contact"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-universal-btn-log_call')).toBeDisabled()
      expect(screen.getByTestId('ra-universal-btn-log_email')).toBeDisabled()
      expect(screen.getByTestId('ra-universal-btn-log_note')).not.toBeDisabled()
    })

    it('does NOT disable non-outreach buttons when leadStatus is do_not_contact', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="do_not_contact"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      // create_task is not an outreach action — should remain enabled
      expect(screen.getByTestId('ra-action-btn-create_task')).not.toBeDisabled()
    })

    it('shows DNC badge on null RA when leadStatus is do_not_contact', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={null}
          leadStatus="do_not_contact"
          openTasks={[]}
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('dnc-badge')).toBeInTheDocument()
    })

    it('disables outreach buttons for ready_for_outreach RA when DNC', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('ready_for_outreach')}
          leadStatus="do_not_contact"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />
      )

      expect(screen.getByTestId('ra-universal-btn-log_call')).toBeDisabled()
      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeDisabled()
      expect(screen.getByTestId('ra-universal-btn-log_email')).toBeDisabled()
      expect(screen.getByTestId('ra-universal-btn-log_note')).not.toBeDisabled()
      // create_task is not outreach — should be enabled
      expect(screen.getByTestId('ra-action-btn-create_task')).not.toBeDisabled()
    })
  })

  describe('create_task RA inline CTA', () => {
    it('shows Create Task CTA when RA is create_task and no open tasks', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('create_task', 'Create a Task', 'Create a task to define the next step.')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
          onCreateTask={vi.fn()}
        />
      )

      expect(screen.getByTestId('create-task-cta')).toBeInTheDocument()
      expect(screen.getByTestId('create-task-cta-button')).toBeInTheDocument()
    })

    it('does NOT show Create Task CTA when RA is create_task but open tasks exist', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('create_task')}
          leadStatus="mailing_no_contact_made"
          openTasks={[makeTask(1)]}
          onAction={vi.fn()}
          onCreateTask={vi.fn()}
        />
      )

      expect(screen.queryByTestId('create-task-cta')).not.toBeInTheDocument()
    })

    it('does NOT show Create Task CTA when RA is not create_task', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
          onCreateTask={vi.fn()}
        />
      )

      expect(screen.queryByTestId('create-task-cta')).not.toBeInTheDocument()
    })

    it('calls onCreateTask when Create Task CTA button is clicked', async () => {
      const onCreateTask = vi.fn()

      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('create_task')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
          onCreateTask={onCreateTask}
        />
      )

      await user.click(screen.getByTestId('create-task-cta-button'))

      expect(onCreateTask).toHaveBeenCalledOnce()
    })
  })

  describe('mailable universal Quick actions', () => {
    it('shows Add to Mail Queue in Quick actions for call_ready when isMailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('call_ready', 'Call Now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeInTheDocument()
    })

    it('shows Add to Mail Queue in Quick actions for follow_up_now when isMailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('follow_up_now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeInTheDocument()
    })

    it('shows Add to Mail Queue in Quick actions for a hold when mail remains eligible', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('hold')}
          leadStatus="skip_trace"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeInTheDocument()
    })

    it('shows Add to Mail Queue in Quick actions when RA is null and isMailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={null}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeInTheDocument()
    })

    it('shows Add to Mail Queue for add_contact_info when isMailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('add_contact_info', 'Add Contact Info')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeInTheDocument()
    })

    it('shows Add to Mail Queue for needs_manual_review when isMailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('needs_manual_review', 'Needs Manual Review')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeInTheDocument()
    })

    it('shows Add to Mail Queue grayed out when not mailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('call_ready', 'Call Now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeDisabled()
    })

    it('explains a recent-sale hold and grays out Add to Mail Queue', async () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('hold')}
          leadStatus="skip_trace"
          openTasks={[]}
          isMailable
          mailEligible={false}
          mailIneligibleReason="recently_sold"
          mailEligibleDate="2027-03-31"
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('recent-sale-mail-hold')).toHaveTextContent(
        'Held in Skip Trace',
      )
      expect(screen.getByTestId('recent-sale-mail-hold')).toHaveTextContent(
        'move to Awaiting Skip Trace',
      )
      expect(screen.getByTestId('recent-sale-mail-hold')).toHaveTextContent(
        formatDateOnly('2027-03-31'),
      )
      expect(screen.getByRole('button', { name: 'Adjust for Recent Sale' })).toBeInTheDocument()
      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeDisabled()
      // Disabled buttons have pointer-events:none — hover the Tooltip's wrapping span.
      const wrapper = screen.getByTestId('ra-universal-btn-add_to_mail_batch').parentElement
      expect(wrapper).toBeTruthy()
      await user.hover(wrapper!)
      expect(await screen.findByRole('tooltip')).toHaveTextContent(
        `Held after recent sale until ${formatDateOnly('2027-03-31')}`,
      )
    })

    it('grays out Add to Mail Queue for stale mail_ready when owner mail is invalid', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('mail_ready', 'Ready to Mail')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeDisabled()
    })

    it('grays out Add to Mail Queue for stale direct_mail method when owner mail is invalid', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={{
            ...makeRA('ready_for_outreach', 'Ready for Outreach'),
            recommended_contact_method: 'direct_mail',
          }}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeDisabled()
    })

    it('keeps Add to Mail Queue in fixed position when RA is mail_ready', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('mail_ready', 'Ready to Mail')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          onAction={vi.fn()}
        />,
      )

      const buttons = screen.getByTestId('ra-universal-actions').querySelectorAll('button')
      expect(buttons[3]).toHaveAttribute('data-testid', 'ra-universal-btn-add_to_mail_batch')
    })

    it('shows In mail batch in Quick actions when queued and mailable', () => {
      render(
        <MemoryRouter>
          <RecommendedActionPanel
            recommendedAction={makeRA('mail_ready', 'Ready to Mail')}
            leadStatus="mailing_no_contact_made"
            openTasks={[]}
            isMailable
            mailQueueStatus="queued"
            onAction={vi.fn()}
          />
        </MemoryRouter>,
      )

      expect(screen.getByTestId('ra-universal-btn-in-mail-batch')).toBeDisabled()
      expect(screen.getByTestId('ra-universal-btn-view-mail-batch')).toBeInTheDocument()
      expect(screen.queryByTestId('ra-universal-btn-add_to_mail_batch')).not.toBeInTheDocument()
    })

    it('shows queued controls even when no longer mailable or mail-recommended', () => {
      render(
        <MemoryRouter>
          <RecommendedActionPanel
            recommendedAction={makeRA('call_ready', 'Call Now')}
            leadStatus="mailing_no_contact_made"
            openTasks={[]}
            mailQueueStatus="queued"
            onAction={vi.fn()}
          />
        </MemoryRouter>,
      )

      expect(screen.getByTestId('ra-universal-btn-in-mail-batch')).toBeDisabled()
      expect(screen.getByTestId('ra-universal-btn-view-mail-batch')).toBeInTheDocument()
      expect(screen.queryByTestId('ra-universal-btn-add_to_mail_batch')).not.toBeInTheDocument()
    })

    it('still shows Add to Mail Queue when mail was sent recently and isMailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('call_ready', 'Call Now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          mailQueueStatus="sent_recently"
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-universal-btn-add_to_mail_batch')).toBeInTheDocument()
    })

    it('shows inline error on null RA when Quick action fails', async () => {
      const onAction = vi.fn().mockRejectedValue(new Error('Invalid mailing address'))

      render(
        <RecommendedActionPanel
          recommendedAction={null}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          isMailable
          mailEligible
          onAction={onAction}
        />,
      )

      await user.click(screen.getByTestId('ra-universal-btn-add_to_mail_batch'))

      expect(await screen.findByTestId('ra-action-error')).toHaveTextContent('Invalid mailing address')
    })

    it('does not show Confirm Building Ownership for needs_manual_review', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('needs_manual_review', 'Needs Manual Review')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.queryByTestId('ra-action-btn-research_property')).not.toBeInTheDocument()
      expect(screen.queryByText('Confirm Building Ownership')).not.toBeInTheDocument()
      expect(screen.getByTestId('ra-universal-btn-log_note')).toBeInTheDocument()
      expect(screen.getByTestId('ra-action-btn-create_task')).toBeInTheDocument()
    })
  })

  describe('entity research status', () => {
    it('shows Never researched and Refresh when entityResearch has no checked_at', () => {
      const onRefresh = vi.fn().mockResolvedValue(undefined)
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data', 'Enrich Data')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
          entityResearch={{
            organization_id: 517,
            organization_name: 'Svigos Asset Management',
            entity_lookup_status: 'pending',
            entity_lookup_person_found: false,
            entity_lookup_checked_at: null,
            entity_lookup_error: null,
          }}
          onRefreshEntityResearch={onRefresh}
        />,
      )

      expect(screen.getByTestId('entity-research-status')).toHaveTextContent(
        'Never researched (Illinois LLC / org)',
      )
      expect(screen.getByTestId('entity-research-status')).toHaveTextContent('pending')
      expect(screen.getByTestId('entity-research-status')).toHaveTextContent(
        'Svigos Asset Management',
      )
      expect(screen.getByTestId('refresh-entity-research-btn')).toBeInTheDocument()
    })

    it('shows Last researched date when checked_at is set', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('nurture', 'Nurture')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
          entityResearch={{
            organization_id: 10,
            organization_name: 'Acme LLC',
            entity_lookup_status: 'no_match',
            entity_lookup_person_found: false,
            entity_lookup_checked_at: '2026-07-01T12:00:00Z',
            entity_lookup_error: null,
          }}
          onRefreshEntityResearch={vi.fn()}
        />,
      )

      expect(screen.getByTestId('entity-research-status')).toHaveTextContent(/Last researched/)
      expect(screen.getByTestId('entity-research-status')).toHaveTextContent('no match')
    })

    it('calls onRefreshEntityResearch when Refresh research is clicked', async () => {
      const onRefresh = vi.fn().mockResolvedValue(undefined)
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data', 'Enrich Data')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
          entityResearch={{
            organization_id: 1,
            organization_name: 'Test Org',
            entity_lookup_status: null,
            entity_lookup_person_found: false,
            entity_lookup_checked_at: null,
            entity_lookup_error: null,
          }}
          onRefreshEntityResearch={onRefresh}
        />,
      )

      await user.click(screen.getByTestId('refresh-entity-research-btn'))
      await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1))
    })
  })
})


