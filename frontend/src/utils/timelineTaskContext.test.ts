import { describe, it, expect } from 'vitest'
import { findActivityContextForTask } from './timelineTaskContext'
import type { LeadTimelineEntry } from '@/types'

function makeEntry(overrides: Partial<LeadTimelineEntry> = {}): LeadTimelineEntry {
  return {
    id: 1,
    lead_id: 1,
    event_type: 'note_added',
    occurred_at: '2026-09-10T12:00:00Z',
    source: 'manual',
    actor: 'user',
    summary: 'Saved note',
    metadata: null,
    hubspot_activity_id: null,
    is_deleted: false,
    created_at: '2026-09-10T12:00:00Z',
    ...overrides,
  }
}

describe('findActivityContextForTask', () => {
  it('returns the note body from the activity that created the follow-up', () => {
    const ctx = findActivityContextForTask(5, [
      makeEntry({
        metadata: { body: 'Owner asked for a callback', follow_up_task_id: 5 },
      }),
    ])
    expect(ctx).toMatchObject({
      body: 'Owner asked for a callback',
      eventType: 'note_added',
    })
  })

  it('returns call notes and the phone that was used', () => {
    const ctx = findActivityContextForTask(8, [
      makeEntry({
        event_type: 'call_logged',
        summary: 'Left voicemail',
        metadata: {
          notes: 'Left voicemail yesterday',
          phone_number: '5551234567',
          contact_name: 'Bob Owner',
          follow_up_task_id: 8,
        },
      }),
    ])
    expect(ctx).toEqual({
      body: 'Left voicemail yesterday',
      contactName: 'Bob Owner',
      eventType: 'call_logged',
      phoneNumber: '5551234567',
    })
  })

  it('ignores activities for a different follow-up task', () => {
    expect(
      findActivityContextForTask(5, [
        makeEntry({
          metadata: { body: 'Other task note', follow_up_task_id: 9 },
        }),
      ]),
    ).toBeNull()
  })

  it('returns meeting notes and event type for a meeting_logged follow-up', () => {
    const context = findActivityContextForTask(88, [
      makeEntry({
        id: 10,
        event_type: 'meeting_logged',
        summary: 'Meeting: Courtyard walkthrough',
        metadata: {
          body: 'Walked the building and talked timing.',
          contact_name: 'Alice Owner',
          follow_up_task_id: 88,
        },
      }),
      makeEntry({
        id: 9,
        event_type: 'call_logged',
        metadata: {
          notes: 'Older call notes',
          follow_up_task_id: 87,
        },
      }),
    ])

    expect(context).toEqual({
      body: 'Walked the building and talked timing.',
      contactName: 'Alice Owner',
      eventType: 'meeting_logged',
    })
  })
})
