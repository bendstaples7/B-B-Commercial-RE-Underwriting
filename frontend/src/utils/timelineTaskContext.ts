import type { LeadTimelineEntry } from '@/types'
import { sortTimelineEntriesDesc } from '@/utils/timelineSort'

const CONTEXT_EVENT_TYPES = new Set(['note_added', 'call_logged', 'email_logged'])

export interface TaskActivityContext {
  body: string
  contactName?: string
  eventType: string
}

function getContextBody(entry: LeadTimelineEntry): string {
  if (entry.event_type === 'call_logged') {
    const notes = entry.metadata?.notes
    if (typeof notes === 'string' && notes.trim()) return notes.trim()
  }
  const body = entry.metadata?.body
  if (typeof body === 'string' && body.trim()) return body.trim()
  return entry.summary?.trim() ?? ''
}

/** Find the most recent activity that created this follow-up task. */
export function findActivityContextForTask(
  taskId: number,
  entries: readonly LeadTimelineEntry[],
): TaskActivityContext | null {
  const sorted = sortTimelineEntriesDesc(entries)
  for (const entry of sorted) {
    if (!CONTEXT_EVENT_TYPES.has(entry.event_type)) continue
    const followUpId = entry.metadata?.follow_up_task_id
    if (followUpId == null || Number(followUpId) !== Number(taskId)) continue
    const body = getContextBody(entry)
    if (!body) continue
    const contactName =
      typeof entry.metadata?.contact_name === 'string'
        ? entry.metadata.contact_name
        : undefined
    return { body, contactName, eventType: entry.event_type }
  }
  return null
}
