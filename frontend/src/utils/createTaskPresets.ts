/**
 * Shared presets for creating lead tasks (Add Task form + activity next-step).
 * Email uses task_type=custom with a title that matches outreach matchers.
 */
import type { LeadTaskType } from '@/types'

export type CreateTaskPresetId =
  | 'call_owner_today'
  | 'schedule_email'
  | 'add_to_mail_batch'
  | 'custom'

export type CreateTaskPreset = {
  id: CreateTaskPresetId
  label: string
  taskType: LeadTaskType
  defaultTitle?: string
  /** Free-text title required (Custom only). */
  requireTitle?: boolean
}

export const CREATE_TASK_PRESETS: CreateTaskPreset[] = [
  {
    id: 'call_owner_today',
    label: 'Schedule call',
    taskType: 'call_owner_today',
    defaultTitle: 'Follow up call',
  },
  {
    id: 'schedule_email',
    label: 'Schedule email',
    taskType: 'custom',
    defaultTitle: 'Email owner',
  },
  {
    id: 'add_to_mail_batch',
    label: 'Add to mail queue',
    taskType: 'add_to_mail_batch',
    defaultTitle: 'Add to mail queue',
  },
  {
    id: 'custom',
    label: 'Custom',
    taskType: 'custom',
    requireTitle: true,
  },
]

export function getCreateTaskPreset(id: CreateTaskPresetId): CreateTaskPreset {
  return (
    CREATE_TASK_PRESETS.find((p) => p.id === id) ??
    CREATE_TASK_PRESETS[CREATE_TASK_PRESETS.length - 1]
  )
}

/** Map an existing open task back onto the next-step preset used to create it. */
export function nextStepTypeFromTask(task: {
  task_type: LeadTaskType | string
  title: string
}): CreateTaskPresetId {
  if (task.task_type === 'call_owner_today') return 'call_owner_today'
  if (task.task_type === 'add_to_mail_batch') return 'add_to_mail_batch'
  const trimmed = task.title.trim()
  const emailTitle = getCreateTaskPreset('schedule_email').defaultTitle
  if (emailTitle && trimmed === emailTitle) return 'schedule_email'
  const callTitle = getCreateTaskPreset('call_owner_today').defaultTitle
  if (callTitle && trimmed === callTitle) return 'call_owner_today'
  return 'custom'
}

/** Resolve API title + task_type for a selected preset. */
export function resolveCreateTaskPayload(
  presetId: CreateTaskPresetId,
  customTitle: string,
): { title: string; task_type: LeadTaskType } {
  const preset = getCreateTaskPreset(presetId)
  if (preset.requireTitle) {
    return {
      title: customTitle.trim() || 'Custom task',
      task_type: preset.taskType,
    }
  }
  return {
    title: customTitle.trim() || preset.defaultTitle || preset.label,
    task_type: preset.taskType,
  }
}
