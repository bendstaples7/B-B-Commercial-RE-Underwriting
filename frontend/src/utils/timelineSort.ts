import type { LeadTimelineEntry, TimelineEventType } from '@/types'

/** Human-facing activity rows sort above system task side-effects at the same timestamp. */
const EVENT_SORT_PRIORITY: Record<string, number> = {
  note_added: 3,
  call_logged: 3,
  email_logged: 3,
  meeting_logged: 3,
  hubspot_call: 3,
  hubspot_note: 3,
  hubspot_meeting: 3,
  task_completed: 2,
  task_created: 1,
}

const HUMAN_ACTIVITY_TYPES = new Set<TimelineEventType>([
  'note_added',
  'call_logged',
  'email_logged',
  'hubspot_call',
  'hubspot_note',
])

export function isHumanActivityEntry(
  entry: Pick<LeadTimelineEntry, 'event_type'>,
): boolean {
  return HUMAN_ACTIVITY_TYPES.has(entry.event_type)
}

/**
 * Collapsed Activity preview: keep notes/calls/emails visible even when later
 * system rows (status, GIS, skip-trace tasks) would otherwise push them out of
 * the first N chronological items.
 */
export function previewTimelineEntries<T extends LeadTimelineEntry>(
  entries: readonly T[],
  limit: number,
): T[] {
  if (entries.length <= limit) return [...entries]
  const human: T[] = []
  const rest: T[] = []
  for (const entry of entries) {
    if (isHumanActivityEntry(entry)) human.push(entry)
    else rest.push(entry)
  }
  return [...human, ...rest].slice(0, limit)
}

function eventSortPriority(eventType: string): number {
  return EVENT_SORT_PRIORITY[eventType] ?? 0
}

/** Compare timeline rows newest-first; tie-break by event priority then id descending. */
export function compareTimelineEntriesDesc(
  a: LeadTimelineEntry,
  b: LeadTimelineEntry,
): number {
  const aTime = Date.parse(a.occurred_at || '') || 0
  const bTime = Date.parse(b.occurred_at || '') || 0
  if (bTime !== aTime) return bTime - aTime
  const priorityDiff =
    eventSortPriority(b.event_type) - eventSortPriority(a.event_type)
  if (priorityDiff !== 0) return priorityDiff
  return b.id - a.id
}

/** Return a copy sorted newest-first. */
export function sortTimelineEntriesDesc(
  entries: readonly LeadTimelineEntry[],
): LeadTimelineEntry[] {
  return [...entries].sort(compareTimelineEntriesDesc)
}
