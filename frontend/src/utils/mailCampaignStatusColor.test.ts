import { describe, expect, it } from 'vitest'
import {
  isMailCampaignSubmitting,
  isRecentMailCampaignSubmitted,
  mailCampaignStatusColor,
  mailCampaignStatusLabel,
} from './mailCampaignStatusColor'

describe('mailCampaignStatus helpers', () => {
  it('treats only pending/processing as submitting', () => {
    expect(isMailCampaignSubmitting('pending')).toBe(true)
    expect(isMailCampaignSubmitting('processing')).toBe(true)
    expect(isMailCampaignSubmitting('submitted')).toBe(false)
    expect(isMailCampaignSubmitting('mailed')).toBe(false)
    expect(isMailCampaignSubmitting('failed')).toBe(false)
  })

  it('labels submitted as accepted by Open Letter', () => {
    expect(mailCampaignStatusLabel('submitted')).toBe('Submitted to Open Letter')
    expect(mailCampaignStatusLabel('pending')).toBe('Sending…')
    expect(mailCampaignStatusLabel('mailed')).toBe('Mailed')
  })

  it('keeps submitted as success color', () => {
    expect(mailCampaignStatusColor('submitted')).toBe('success')
    expect(mailCampaignStatusColor('pending')).toBe('info')
  })

  it('limits success banner to recent submitted campaigns', () => {
    const now = Date.parse('2026-07-27T12:00:00.000Z')
    expect(isRecentMailCampaignSubmitted({
      status: 'submitted',
      submitted_at: '2026-07-27T10:00:00.000Z',
    }, now)).toBe(true)
    expect(isRecentMailCampaignSubmitted({
      status: 'submitted',
      submitted_at: '2026-07-25T10:00:00.000Z',
    }, now)).toBe(false)
    expect(isRecentMailCampaignSubmitted({
      status: 'mailed',
      submitted_at: '2026-07-27T10:00:00.000Z',
    }, now)).toBe(false)
  })
})
