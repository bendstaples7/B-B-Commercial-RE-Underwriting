import PhoneIcon from '@mui/icons-material/Phone'
import NoteIcon from '@mui/icons-material/Note'
import AddTaskIcon from '@mui/icons-material/AddTask'
import type { QueryClient } from '@tanstack/react-query'
import type { NavigateFunction } from 'react-router-dom'
import { buildLeadLogUrl } from '@/utils/queueLogNavigation'
import { outreachContactTaskTitle } from '@/utils/outreachContact'
import { leadTaskService } from '@/services/api'
import type { RowAction } from './QueueTable'

interface QueueRowActionOptions {
  navigate: NavigateFunction
  queryClient: QueryClient
  queryKey: string
  extraQueryKeys?: string[]
  onAfterAction?: () => void
}

function invalidateQueueQueries(
  queryClient: QueryClient,
  queryKey: string,
  extraQueryKeys?: string[],
) {
  queryClient.invalidateQueries({ queryKey: [queryKey] })
  for (const key of extraQueryKeys ?? []) {
    queryClient.invalidateQueries({ queryKey: [key] })
  }
}

export function createLogCallRowAction({
  navigate,
  onAfterAction,
}: Pick<QueueRowActionOptions, 'navigate' | 'onAfterAction'>): RowAction {
  return {
    label: 'Log Call',
    icon: <PhoneIcon fontSize="small" />,
    testId: 'action-log-call',
    onClick: async (row) => {
      onAfterAction?.()
      navigate(buildLeadLogUrl(row.id, 'call'))
    },
  }
}

export function createLogNoteRowAction({
  navigate,
  onAfterAction,
}: Pick<QueueRowActionOptions, 'navigate' | 'onAfterAction'>): RowAction {
  return {
    label: 'Log Note',
    icon: <NoteIcon fontSize="small" />,
    testId: 'action-log-note',
    onClick: async (row) => {
      onAfterAction?.()
      navigate(buildLeadLogUrl(row.id, 'note'))
    },
  }
}

export function createCreateTaskRowAction({
  queryClient,
  queryKey,
  extraQueryKeys,
  onAfterAction,
}: Pick<QueueRowActionOptions, 'queryClient' | 'queryKey' | 'extraQueryKeys' | 'onAfterAction'>): RowAction {
  return {
    label: 'Create Task',
    icon: <AddTaskIcon fontSize="small" />,
    testId: 'action-create-task',
    onClick: async (row) => {
      const isMail =
        row.outreach_contact?.channel === 'direct_mail'
        || row.recommended_contact_method === 'direct_mail'
      await leadTaskService.createTask(row.id, {
        title: outreachContactTaskTitle(row.outreach_contact),
        task_type: isMail ? 'add_to_mail_batch' : 'call_owner_today',
      })
      invalidateQueueQueries(queryClient, queryKey, extraQueryKeys)
      onAfterAction?.()
    },
  }
}
