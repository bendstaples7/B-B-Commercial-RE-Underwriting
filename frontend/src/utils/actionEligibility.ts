/**
 * Quick-action eligibility mirror of backend action_eligibility.py.
 * Keep reason codes and messages aligned with the Python SoT.
 */
import type { LeadStatus } from '@/types'
import { formatDateOnly } from '@/utils/helpers'

export const REASON_ALREADY_SKIP_TRACE = 'already_skip_trace'
export const REASON_ALREADY_AWAITING_SKIP_TRACE = 'already_awaiting_skip_trace'
export const REASON_TERMINAL_STATUS = 'terminal_status'
export const REASON_DNC_BLOCKS_OUTREACH = 'dnc_blocks_outreach'
export const REASON_MAIL_RECENTLY_SOLD = 'mail_recently_sold'
export const REASON_MAIL_INVALID_ADDRESS = 'mail_invalid_address'
export const REASON_MAIL_ALREADY_QUEUED = 'mail_already_queued'

const TERMINAL_LEAD_STATUSES: LeadStatus[] = [
  'deprioritize',
  'deal_won',
  'deal_lost',
  'suppressed',
  'do_not_contact',
]

export type QuickActionId =
  | 'log_call'
  | 'log_note'
  | 'log_email'
  | 'add_to_mail_batch'
  | 'move_to_skip_trace'

export interface ActionEligibilityResult {
  ok: boolean
  reasonCode: string | null
  message: string | null
  alreadyDone: boolean
}

function ok(): ActionEligibilityResult {
  return { ok: true, reasonCode: null, message: null, alreadyDone: false }
}

function blocked(
  reasonCode: string,
  message: string,
  alreadyDone = false,
): ActionEligibilityResult {
  return { ok: false, reasonCode, message, alreadyDone }
}

export function evaluateMoveToSkipTrace(leadStatus: LeadStatus): ActionEligibilityResult {
  if (leadStatus === 'skip_trace') {
    return blocked(REASON_ALREADY_SKIP_TRACE, 'Already in Skip Trace', true)
  }
  if (leadStatus === 'awaiting_skip_trace') {
    return blocked(REASON_ALREADY_AWAITING_SKIP_TRACE, 'Already awaiting skip trace', true)
  }
  if (TERMINAL_LEAD_STATUSES.includes(leadStatus)) {
    return blocked(REASON_TERMINAL_STATUS, 'Not available for this lead status')
  }
  return ok()
}

export function evaluateAddToMailBatch(input: {
  mailQueueStatus?: 'queued' | 'sent_recently' | null
  mailEligible?: boolean
  isMailable?: boolean
  mailIneligibleReason?: string | null
  mailEligibleDate?: string | null
}): ActionEligibilityResult {
  if (input.mailQueueStatus === 'queued') {
    return blocked(
      REASON_MAIL_ALREADY_QUEUED,
      'Already staged for the next mail batch',
      true,
    )
  }
  const mailReady = input.mailEligible ?? input.isMailable ?? false
  if (mailReady) return ok()
  if (input.mailIneligibleReason === 'recently_sold') {
    if (input.mailEligibleDate) {
      return blocked(
        REASON_MAIL_RECENTLY_SOLD,
        `Held after recent sale until ${formatDateOnly(input.mailEligibleDate)}`,
      )
    }
    return blocked(
      REASON_MAIL_RECENTLY_SOLD,
      'Held after recent sale until the two-year hold ends',
    )
  }
  return blocked(
    REASON_MAIL_INVALID_ADDRESS,
    'Owner mailing address is not ready for the mail queue',
  )
}

export function evaluateOutreachLog(
  leadStatus: LeadStatus,
  action: 'log_call' | 'log_note' | 'log_email',
): ActionEligibilityResult {
  if (action === 'log_note') return ok()
  if (
    (action === 'log_call' || action === 'log_email')
    && leadStatus === 'do_not_contact'
  ) {
    return blocked(
      REASON_DNC_BLOCKS_OUTREACH,
      'Outreach is blocked — lead is Do Not Contact',
    )
  }
  return ok()
}

/** Unavailable title text for a Quick Action button, or null if enabled. */
export function unavailableReasonForQuickAction(
  action: QuickActionId,
  ctx: {
    leadStatus: LeadStatus
    mailQueueStatus?: 'queued' | 'sent_recently' | null
    mailEligible?: boolean
    isMailable?: boolean
    mailIneligibleReason?: string | null
    mailEligibleDate?: string | null
  },
): string | null {
  if (action === 'move_to_skip_trace') {
    const r = evaluateMoveToSkipTrace(ctx.leadStatus)
    return r.ok ? null : r.message
  }
  if (action === 'add_to_mail_batch') {
    const r = evaluateAddToMailBatch(ctx)
    // Queued shows alternate "In mail batch" controls — not a gray Add button title.
    if (r.reasonCode === REASON_MAIL_ALREADY_QUEUED) return null
    return r.ok ? null : r.message
  }
  if (action === 'log_call' || action === 'log_email' || action === 'log_note') {
    const r = evaluateOutreachLog(ctx.leadStatus, action)
    return r.ok ? null : r.message
  }
  return null
}
