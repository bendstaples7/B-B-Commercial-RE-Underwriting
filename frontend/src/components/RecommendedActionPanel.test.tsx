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

function makeTask(id: number): LeadTask {
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

    it('shows the next task instead of a blank nurture heading', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('nurture', 'Nurture')}
          leadStatus="mailing_no_contact_made"
          openTasks={[{ ...makeTask(1), title: 'Manually skip trace returned letter' }]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByTestId('ra-label')).toHaveTextContent('Follow up on next task')
      expect(screen.getByTestId('ra-next-task-title')).toHaveTextContent(
        'Manually skip trace returned letter',
      )
    })

    it('shows next task fallback when no recommended action exists', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={null}
          leadStatus="mailing_no_contact_made"
          openTasks={[makeTask(2)]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.getByText('Follow up on next task')).toBeInTheDocument()
      expect(screen.getByText('Task 2')).toBeInTheDocument()
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
      'skip_trace',
      'awaiting_skip_trace',
    ] as const)('hides Move to Skip Trace for terminal status %s', (leadStatus) => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('enrich_data')}
          leadStatus={leadStatus}
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(
        screen.queryByRole('button', { name: 'Move to Skip Trace' }),
      ).not.toBeInTheDocument()
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

    it('shows Add to Mail Queue in Quick actions for nurture when isMailable', () => {
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

    it('does not show Add to Mail Queue when not mailable', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('call_ready', 'Call Now')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.queryByTestId('ra-universal-btn-add_to_mail_batch')).not.toBeInTheDocument()
      expect(screen.queryByTestId('ra-action-btn-add_to_mail_batch')).not.toBeInTheDocument()
    })

    it('explains a recent-sale hold and hides Add to Mail Queue', () => {
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
      expect(screen.getByTestId('recent-sale-mail-hold')).toHaveTextContent('3/31/2027')
      expect(screen.getByRole('button', { name: 'Adjust for Recent Sale' })).toBeInTheDocument()
      expect(screen.queryByTestId('ra-universal-btn-add_to_mail_batch')).not.toBeInTheDocument()
    })

    it('hides Add to Mail Queue for stale mail_ready when owner mail is invalid', () => {
      render(
        <RecommendedActionPanel
          recommendedAction={makeRA('mail_ready', 'Ready to Mail')}
          leadStatus="mailing_no_contact_made"
          openTasks={[]}
          onAction={vi.fn()}
        />,
      )

      expect(screen.queryByTestId('ra-universal-btn-add_to_mail_batch')).not.toBeInTheDocument()
    })

    it('hides Add to Mail Queue for stale direct_mail method when owner mail is invalid', () => {
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

      expect(screen.queryByTestId('ra-universal-btn-add_to_mail_batch')).not.toBeInTheDocument()
    })

    it('promotes Add to Mail Queue first when RA is mail_ready', () => {
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
      expect(buttons[0]).toHaveAttribute('data-testid', 'ra-universal-btn-add_to_mail_batch')
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
})


