import { describe, it, expect } from 'vitest'
import { previewTimelineEntries, sortTimelineEntriesDesc } from '@/utils/timelineSort'
import type { LeadTimelineEntry, TimelineEventType } from '@/types'

function makeEntry(
  id: number,
  eventType: TimelineEventType,
  occurredAt: string,
): LeadTimelineEntry {
  return {
    id,
    lead_id: 1,
    event_type: eventType,
    occurred_at: occurredAt,
    source: 'manual',
    actor: 'Ben',
    summary: `Entry ${id}`,
    metadata: null,
    hubspot_activity_id: null,
    is_deleted: false,
    created_at: occurredAt,
  }
}

describe('sortTimelineEntriesDesc', () => {
  it('prefers human activity over task side-effects at the same timestamp', () => {
    const ts = '2026-08-25T18:01:19.000Z'
    const sorted = sortTimelineEntriesDesc([
      makeEntry(3, 'task_created', ts),
      makeEntry(4, 'hubspot_note', ts),
      makeEntry(2, 'task_completed', ts),
      makeEntry(1, 'note_added', ts),
    ])
    expect(sorted.map((e) => e.event_type)).toEqual([
      'hubspot_note',
      'note_added',
      'task_completed',
      'task_created',
    ])
  })
})

describe('previewTimelineEntries', () => {
  it('keeps an older note in the collapsed preview when later system rows would hide it', () => {
    const later = '2026-09-03T23:51:24.000Z'
    const capture = '2026-09-03T23:49:48.000Z'
    const preview = previewTimelineEntries(
      sortTimelineEntriesDesc([
        makeEntry(11, 'status_changed', later),
        makeEntry(10, 'status_changed', later),
        makeEntry(9, 'category_changed', later),
        makeEntry(8, 'status_changed', later),
        makeEntry(7, 'task_created', capture),
        makeEntry(6, 'note_added', capture),
        makeEntry(5, 'lead_imported', capture),
      ]),
      5,
    )
    expect(preview.map((e) => e.event_type)).toEqual([
      'note_added',
      'status_changed',
      'status_changed',
      'category_changed',
      'status_changed',
    ])
  })

  it('keeps meeting rows in the collapsed preview ahead of later system events', () => {
    const later = '2026-09-03T23:51:24.000Z'
    const meetingAt = '2026-09-03T23:49:48.000Z'
    const preview = previewTimelineEntries(
      sortTimelineEntriesDesc([
        makeEntry(11, 'status_changed', later),
        makeEntry(10, 'status_changed', later),
        makeEntry(9, 'category_changed', later),
        makeEntry(8, 'status_changed', later),
        makeEntry(7, 'task_created', meetingAt),
        makeEntry(6, 'meeting_logged', meetingAt),
        makeEntry(5, 'hubspot_meeting', meetingAt),
      ]),
      5,
    )
    expect(preview.map((e) => e.event_type)).toEqual([
      'meeting_logged',
      'hubspot_meeting',
      'status_changed',
      'status_changed',
      'category_changed',
    ])
  })
})
