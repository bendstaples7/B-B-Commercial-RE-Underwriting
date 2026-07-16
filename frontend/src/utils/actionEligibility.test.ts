import { describe, expect, it } from 'vitest'
import {
  REASON_ALREADY_AWAITING_SKIP_TRACE,
  REASON_ALREADY_SKIP_TRACE,
  REASON_DNC_BLOCKS_OUTREACH,
  REASON_MAIL_ALREADY_QUEUED,
  REASON_MAIL_INVALID_ADDRESS,
  REASON_MAIL_RECENTLY_SOLD,
  REASON_TERMINAL_STATUS,
  evaluateAddToMailBatch,
  evaluateMoveToSkipTrace,
  evaluateOutreachLog,
  unavailableReasonForQuickAction,
} from '@/utils/actionEligibility'
import { formatDateOnly } from '@/utils/helpers'

describe('actionEligibility', () => {
  it('allows move_to_skip_trace for active statuses', () => {
    expect(evaluateMoveToSkipTrace('mailing_no_contact_made').ok).toBe(true)
  })

  it('marks skip_trace pipeline as already done', () => {
    expect(evaluateMoveToSkipTrace('skip_trace')).toMatchObject({
      ok: false,
      alreadyDone: true,
      reasonCode: REASON_ALREADY_SKIP_TRACE,
    })
    expect(evaluateMoveToSkipTrace('awaiting_skip_trace')).toMatchObject({
      ok: false,
      alreadyDone: true,
      reasonCode: REASON_ALREADY_AWAITING_SKIP_TRACE,
    })
  })

  it('blocks terminal statuses for skip trace', () => {
    expect(evaluateMoveToSkipTrace('do_not_contact').reasonCode).toBe(REASON_TERMINAL_STATUS)
  })

  it('gates mail queue with already_queued / sold / invalid', () => {
    expect(evaluateAddToMailBatch({ mailEligible: true }).ok).toBe(true)
    expect(evaluateAddToMailBatch({ mailQueueStatus: 'queued', mailEligible: true })).toMatchObject({
      alreadyDone: true,
      reasonCode: REASON_MAIL_ALREADY_QUEUED,
    })
    expect(
      evaluateAddToMailBatch({
        mailEligible: false,
        mailIneligibleReason: 'recently_sold',
        mailEligibleDate: '2027-03-31',
      }),
    ).toMatchObject({
      reasonCode: REASON_MAIL_RECENTLY_SOLD,
      message: `Held after recent sale until ${formatDateOnly('2027-03-31')}`,
    })
    expect(evaluateAddToMailBatch({ mailEligible: false }).reasonCode).toBe(
      REASON_MAIL_INVALID_ADDRESS,
    )
  })

  it('blocks outreach logs on DNC but allows notes', () => {
    expect(evaluateOutreachLog('do_not_contact', 'log_call').reasonCode).toBe(
      REASON_DNC_BLOCKS_OUTREACH,
    )
    expect(evaluateOutreachLog('do_not_contact', 'log_note').ok).toBe(true)
  })

  it('unavailableReasonForQuickAction hides mail title when already queued', () => {
    expect(
      unavailableReasonForQuickAction('add_to_mail_batch', {
        leadStatus: 'mailing_no_contact_made',
        mailQueueStatus: 'queued',
        mailEligible: true,
      }),
    ).toBeNull()
    expect(
      unavailableReasonForQuickAction('move_to_skip_trace', {
        leadStatus: 'awaiting_skip_trace',
      }),
    ).toBe('Already awaiting skip trace')
  })
})
