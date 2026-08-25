import { describe, it, expect } from 'vitest'
import { sortTimelineEntriesDesc } from '@/utils/timelineSort'
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
