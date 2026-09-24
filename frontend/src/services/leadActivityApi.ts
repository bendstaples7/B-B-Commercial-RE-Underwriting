/**
 * Lead task + activity logging API (Command Center / Log Activity).
 * Split from api.ts to stay under the duplication line budget.
 */
import api from '@/services/httpClient'
import type {
  LeadTask,
  LeadTimelineEntry,
  LogCallPayload,
  LogNotePayload,
} from '@/types'

export type LeadTaskCreate = {
  title: string
  task_type?: string
  due_date?: string | null
  notes?: string | null
}

/** PATCH may update title/due_date/notes — not task_type (server ignores it). */
export type LeadTaskUpdate = {
  title?: string
  due_date?: string | null
  notes?: string | null
  new_due_date?: string
}

export const leadTaskService = {
  createTask: (leadId: number, data: LeadTaskCreate): Promise<LeadTask> =>
    api.post(`/leads/${leadId}/tasks`, data).then((r) => r.data),
  updateTask: (leadId: number, taskId: number, data: LeadTaskUpdate): Promise<LeadTask> =>
    api.patch(`/leads/${leadId}/tasks/${taskId}`, data).then((r) => r.data),
  completeTask: (leadId: number, taskId: number): Promise<LeadTask> =>
    api.post(`/leads/${leadId}/tasks/${taskId}/complete`).then((r) => r.data),
  snoozeTask: (leadId: number, taskId: number, newDueDate: string): Promise<LeadTask> =>
    api.patch(`/leads/${leadId}/tasks/${taskId}`, { new_due_date: newDueDate }).then((r) => r.data),
}

export const callLogService = {
  logCall: (leadId: number, payload: LogCallPayload): Promise<LeadTimelineEntry> =>
    api.post(`/leads/${leadId}/calls`, payload).then((r) => r.data),
  logNote: (leadId: number, payload: LogNotePayload): Promise<LeadTimelineEntry> =>
    api.post(`/leads/${leadId}/notes`, payload).then((r) => r.data),
  markHubSpotTaskDone: (
    leadId: number,
    taskId: number,
    opts?: { idNamespace?: 'lead_task' | 'crm_task' },
  ): Promise<{ task_id: number; status: string }> =>
    api
      .post(`/leads/${leadId}/hubspot-tasks/${taskId}/done`, {
        id_namespace: opts?.idNamespace ?? 'lead_task',
      })
      .then((r) => r.data),
}
