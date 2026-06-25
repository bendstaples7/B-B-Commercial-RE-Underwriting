export interface QueueContext {
  label: string
  path: string
  reason: string
  color: 'error' | 'warning' | 'info' | 'success' | 'default'
}

export function deriveQueueContext(data: any): QueueContext[] {
  const queues: QueueContext[] = []

  if (data.lead_status === 'do_not_contact') {
    queues.push({ label: 'Do Not Contact', path: '/queues/do-not-contact', reason: 'This lead is marked Do Not Contact.', color: 'error' })
  }
  if (data.review_required) {
    queues.push({ label: 'Needs Review', path: '/queues/needs-review', reason: data.review_reason || 'This lead has been flagged for review.', color: 'warning' })
  }
  if (data.follow_up_overdue) {
    queues.push({ label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue', reason: 'A follow-up task is overdue.', color: 'error' })
  }
  // Today's Action: overdue HubSpot task (most common case)
  if (data.has_overdue_hubspot_task) {
    const taskDesc = data.overdue_task_title
      ? `"${data.overdue_task_title}" (HubSpot task) was due ${data.overdue_task_due ? new Date(data.overdue_task_due).toLocaleDateString() : 'in the past'} and is still open.`
      : 'A HubSpot task is overdue.'
    queues.push({ label: "Today's Action", path: '/', reason: taskDesc, color: 'warning' })
  } else if (data.is_warm && !data.follow_up_overdue) {
    queues.push({ label: "Today's Action", path: '/', reason: 'This lead has prior warm engagement — reach out now.', color: 'warning' })
  } else if (data.recommended_action?.value === 'follow_up_now' && !data.follow_up_overdue && !data.is_warm) {
    queues.push({ label: "Today's Action", path: '/', reason: data.recommended_action.explanation || 'Follow up now.', color: 'warning' })
  }
  if (!data.has_property_match) {
    queues.push({ label: 'Missing Property Match', path: '/queues/missing-property-match', reason: 'No confirmed property match exists for this lead.', color: 'info' })
  }
  if (data.recommended_action?.value === 'create_task' && !['suppressed', 'do_not_contact', 'deprioritize', 'deal_won', 'deal_lost'].includes(data.lead_status)) {
    queues.push({ label: 'No Next Action', path: '/queues/no-next-action', reason: 'No open tasks or next action defined.', color: 'default' })
  }

  return queues
}
