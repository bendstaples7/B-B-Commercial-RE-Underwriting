import { describe, it, expect } from 'vitest'
import {
  outreachContactTaskTitle,
  resolveOutreachContactFromCommandCenter,
} from './outreachContact'
import type { CommandCenterPayload, OutreachContact } from '@/types'

function minimalCommandCenter(
  overrides: Partial<CommandCenterPayload> = {},
): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: 'Gilberto',
    owner_last_name: 'Olivares',
    property_street: '2553 N Drake Ave',
    property_city: 'Chicago',
    property_state: 'IL',
    property_zip: '60647',
    lead_score: 94,
    lead_status: 'negotiating_remote',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: {
      value: 'call_ready',
      recommended_contact_method: 'phone',
      label: 'Call Now',
      explanation: 'Ready for phone outreach.',
      signals: {},
    },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 25 },
    phones: [{ value: '(630) 202-3839', confidence_score: 80 }],
    ...overrides,
  }
}

describe('outreachContactTaskTitle', () => {
  it('builds title from contact label and display', () => {
    const contact: OutreachContact = {
      channel: 'phone',
      label: 'Call',
      value: '5551234567',
      display: '(555) 123-4567',
    }
    expect(outreachContactTaskTitle(contact)).toBe('Call (555) 123-4567')
  })

  it('falls back to Follow up when contact is missing', () => {
    expect(outreachContactTaskTitle(null)).toBe('Follow up')
  })
})

describe('resolveOutreachContactFromCommandCenter', () => {
  it('uses API outreach_contact when present', () => {
    const apiContact: OutreachContact = {
      channel: 'phone',
      label: 'Call',
      value: '6302023839',
      display: '(630) 202-3839',
      href: 'tel:+16302023839',
    }
    const data = minimalCommandCenter({
      recommended_action: {
        value: 'call_ready',
        recommended_contact_method: 'phone',
        label: 'Call Now',
        explanation: '',
        signals: {},
        outreach_contact: apiContact,
      },
    })
    expect(resolveOutreachContactFromCommandCenter(data)).toEqual(apiContact)
  })

  it('falls back to phones array when outreach_contact is missing', () => {
    const data = minimalCommandCenter()
    const contact = resolveOutreachContactFromCommandCenter(data)
    expect(contact?.display).toBe('(630) 202-3839')
    expect(contact?.href).toBe('tel:+16302023839')
  })

  it('falls back to phone_1 when phones array is empty', () => {
    const data = minimalCommandCenter({
      phones: [],
      phone_1: '(630) 202-3839',
    })
    const contact = resolveOutreachContactFromCommandCenter(data)
    expect(contact?.display).toBe('(630) 202-3839')
  })
})
