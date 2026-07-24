import { describe, it, expect } from 'vitest'
import { outreachContactPlacement } from './outreachContactPlacement'
import type { LeadTask, OutreachContact } from '@/types'

const phoneContact: OutreachContact = {
  channel: 'phone',
  label: 'Call',
  value: '6302023839',
  display: '(630) 202-3839',
  href: 'tel:+16302023839',
}

function makeTask(id: number): LeadTask {
  return {
    id,
    lead_id: 1,
    task_type: 'custom',
    title: 'Follow up',
    status: 'open',
    due_date: '2026-06-30',
    created_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    created_by: 'user',
    source: 'hubspot',
  }
}

describe('outreachContactPlacement', () => {
  it('returns none for non-outreach recommended actions', () => {
    expect(outreachContactPlacement([makeTask(1)], phoneContact, 'create_task')).toBe('none')
    expect(outreachContactPlacement([], phoneContact, 'enrich_data')).toBe('none')
  })

  it('returns primary_task when open tasks exist for outreach actions', () => {
    expect(outreachContactPlacement([makeTask(1)], phoneContact, 'call_ready')).toBe('primary_task')
    expect(outreachContactPlacement([makeTask(1)], null, 'call_ready')).toBe('primary_task')
  })

  it('returns recommended_action when no open tasks for outreach actions', () => {
    expect(outreachContactPlacement([], phoneContact, 'call_ready')).toBe('recommended_action')
    expect(outreachContactPlacement([], null, 'mail_ready')).toBe('recommended_action')
  })

  it('returns key_contact_card when Key Contact card is visible', () => {
    expect(
      outreachContactPlacement([makeTask(1)], phoneContact, 'call_ready', {
        keyContactCardVisible: true,
      }),
    ).toBe('key_contact_card')
    expect(
      outreachContactPlacement([], phoneContact, 'mail_ready', {
        keyContactCardVisible: true,
      }),
    ).toBe('key_contact_card')
  })
})
