/**
 * LeadTaskList — displays open tasks for a lead ordered by due_date asc (nulls last),
 * with an inline task creation form.
 *
 * Requirements: 3.2, 3.3, 3.6, 4.3, 7.5, 7.6
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemText,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import AddTaskIcon from '@mui/icons-material/AddTask'
import HubIcon from '@mui/icons-material/Hub'
import type { LeadTask, LeadTaskType, CRMRecommendedAction, OutreachContact } from '@/types'
import { leadTaskService, callLogService } from '@/services/api'
import { OutreachContactInline, OutreachContactMissingHint } from '@/components/OutreachContactCallout'
import { ccSubsectionTitleSx } from '@/components/lead-detail/commandCenterChrome'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export type TaskDueStatus = 'overdue' | 'due_today' | 'upcoming' | 'no_due'

const CREATE_TASK_TYPES: Array<{ value: LeadTaskType; label: string; defaultTitle?: string }> = [
  { value: 'custom', label: 'Custom' },
  {
    value: 'add_to_mail_batch',
    label: 'Add to mail queue',
    defaultTitle: 'Add to mail queue',
  },
]

const DUE_STATUS_SORT_ORDER: Record<TaskDueStatus, number> = {
  overdue: 0,
  due_today: 1,
  upcoming: 2,
  no_due: 3,
}

function getTaskDueStatus(dueDate: string | null): TaskDueStatus {
  if (!dueDate) return 'no_due'
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const due = new Date(dueDate + 'T00:00:00')
  if (due < today) return 'overdue'
  if (due.getTime() === today.getTime()) return 'due_today'
  return 'upcoming'
}

/**
 * Sort tasks: overdue first, then due today, then upcoming by date asc, nulls last.
 */
function sortTasks(tasks: LeadTask[]): LeadTask[] {
  return [...tasks].sort((a, b) => {
    const statusA = getTaskDueStatus(a.due_date)
    const statusB = getTaskDueStatus(b.due_date)
    const orderDiff = DUE_STATUS_SORT_ORDER[statusA] - DUE_STATUS_SORT_ORDER[statusB]
    if (orderDiff !== 0) return orderDiff
    if (a.due_date === null && b.due_date === null) return 0
    if (a.due_date === null) return 1
    if (b.due_date === null) return -1
    return a.due_date.localeCompare(b.due_date)
  })
}

function formatDueDate(dueDate: string | null): string {
  if (!dueDate) return 'Pending'
  // dueDate is a date string like "2024-01-15"
  const [year, month, day] = dueDate.split('-')
  return `Due ${month}/${day}/${year}`
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface LeadTaskListHandle {
  openCreateForm: () => void
}

export interface LeadTaskListProps {
  leadId: number
  tasks: LeadTask[]
  recommendedAction?: CRMRecommendedAction | null
  onTaskCreated: (task: LeadTask) => void
  /** Called after a successful title/due-date update on a native task. */
  onTaskUpdated?: (task: LeadTask) => void
  onTaskCompleted?: (taskId: number | string) => void
  onHubSpotTaskDone?: (taskId: number) => void
  /** Called immediately when the user submits the form, before the API call
   *  completes. Receives a temporary placeholder task (id = 0, status = 'open').
   *  Use this to add an optimistic entry to the task list.
   */
  onOptimisticTaskCreate?: (optimisticTask: LeadTask) => void
  /** Called when the create API call fails, to roll back the optimistic
   *  placeholder added via `onOptimisticTaskCreate`. Receives the same
   *  placeholder task (id = 0) so the parent can remove it from the list.
   */
  onOptimisticTaskRevert?: (optimisticTask: LeadTask) => void
  outreachContact?: OutreachContact | null
  /** Show outreach contact inline on the primary (first sorted) open task only */
  showOutreachContactOnPrimaryTask?: boolean
  /** Channel when outreach is recommended but no contact could be resolved */
  missingOutreachChannel?: OutreachContact['channel'] | null
  mailQueueStatus?: 'queued' | 'sent_recently' | null
  upNextToMail?: boolean
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * LeadTaskList renders open tasks ordered by due_date asc (nulls last),
 * an inline task creation form, and a "Create Task" CTA when RA is
 * `create_task` and no open tasks exist.
 */
export const LeadTaskList = forwardRef<LeadTaskListHandle, LeadTaskListProps>(function LeadTaskList(
  {
    leadId,
    tasks,
    recommendedAction,
    onTaskCreated,
    onTaskUpdated,
    onTaskCompleted,
    onHubSpotTaskDone,
    onOptimisticTaskCreate,
    onOptimisticTaskRevert,
    outreachContact,
    showOutreachContactOnPrimaryTask = false,
    missingOutreachChannel = null,
    mailQueueStatus = null,
    upNextToMail = false,
  },
  ref,
) {
  const [formOpen, setFormOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [taskType, setTaskType] = useState<LeadTaskType>('custom')
  const [dueDate, setDueDate] = useState('')
  const [titleError, setTitleError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [markingDone, setMarkingDone] = useState<number | null>(null)
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null)
  const [editingField, setEditingField] = useState<'title' | 'due_date' | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDueDate, setEditDueDate] = useState('')
  const [editTitleError, setEditTitleError] = useState<string | null>(null)
  const [editSubmitError, setEditSubmitError] = useState<string | null>(null)
  const [editSubmitting, setEditSubmitting] = useState(false)
  const editSubmittingRef = useRef(false)
  const skipBlurSaveRef = useRef(false)
  const editingRef = useRef<{ id: number | null; field: 'title' | 'due_date' | null }>({
    id: null,
    field: null,
  })

  useEffect(() => {
    editingRef.current = { id: editingTaskId, field: editingField }
  }, [editingTaskId, editingField])

  const openTasks = tasks.filter((t) => t.status === 'open' || t.status === 'overdue')
  const sortedTasks = sortTasks(openTasks)
  const showCreateTaskCTA = recommendedAction === 'create_task' && openTasks.length === 0
  const awaitingMailBatch = mailQueueStatus === 'queued' || upNextToMail
  const noOpenTasksWhileAwaitingMail = awaitingMailBatch && openTasks.length === 0

  // ---------------------------------------------------------------------------
  // Form handlers
  // ---------------------------------------------------------------------------

  const handleOpenForm = () => {
    setEditingTaskId(null)
    setEditingField(null)
    setEditTitle('')
    setEditDueDate('')
    setEditTitleError(null)
    setEditSubmitError(null)
    setFormOpen(true)
    setTitle('')
    setTaskType('custom')
    setDueDate('')
    setTitleError(null)
    setSubmitError(null)
  }

  useImperativeHandle(ref, () => ({
    openCreateForm: handleOpenForm,
  }))

  const handleCloseForm = () => {
    setFormOpen(false)
    setTitle('')
    setTaskType('custom')
    setDueDate('')
    setTitleError(null)
    setSubmitError(null)
  }

  const handleTaskTypeChange = (nextType: LeadTaskType) => {
    const prevDefault = CREATE_TASK_TYPES.find((t) => t.value === taskType)?.defaultTitle
    const nextDefault = CREATE_TASK_TYPES.find((t) => t.value === nextType)?.defaultTitle
    setTaskType(nextType)
    // Prefill default title when switching to a typed task and title is empty or still the prior default
    if (nextDefault && (!title.trim() || title.trim() === prevDefault)) {
      setTitle(nextDefault)
      if (titleError) setTitleError(null)
    }
  }

  const validateTitle = (value: string): string | null => {
    const trimmed = value.trim()
    if (trimmed.length === 0) return 'Title is required.'
    if (trimmed.length > 255) return 'Title must be 255 characters or fewer.'
    return null
  }

  const handleSubmit = async () => {
    const error = validateTitle(title)
    if (error) {
      setTitleError(error)
      return
    }

    setTitleError(null)
    setSubmitError(null)
    setSubmitting(true)

    // Fire optimistic callback before the API call so the parent can render
    // a placeholder task immediately (property 12: optimistic task creation).
    const optimisticTask: LeadTask = {
      id: 0,
      lead_id: leadId,
      task_type: taskType,
      title: title.trim(),
      status: 'open',
      due_date: dueDate || null,
      created_at: new Date().toISOString(),
      completed_at: null,
      created_by: 'user',
    }
    if (onOptimisticTaskCreate) {
      onOptimisticTaskCreate(optimisticTask)
    }

    try {
      const newTask = await leadTaskService.createTask(leadId, {
        title: title.trim(),
        task_type: taskType,
        due_date: dueDate || null,
      })
      onTaskCreated(newTask)
      handleCloseForm()
    } catch (err) {
      // Roll back the optimistic placeholder (if one was added) so a failed
      // create doesn't leave a stale task in the list. Preserve form data on
      // failure — do NOT close the form — so the user can retry.
      if (onOptimisticTaskCreate) {
        onOptimisticTaskRevert?.(optimisticTask)
      }
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to create task. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleStartEdit = (task: LeadTask, field: 'title' | 'due_date' = 'title') => {
    // Local LeadTask rows (native or HubSpot-imported) are editable via PATCH.
    // Legacy string ids (e.g. hs-…) and optimistic placeholders are not.
    if (editSubmittingRef.current) return
    if (typeof task.id !== 'number' || task.id <= 0) return
    skipBlurSaveRef.current = false
    setFormOpen(false)
    setEditingTaskId(task.id)
    setEditingField(field)
    setEditTitle(task.title)
    setEditDueDate(task.due_date ?? '')
    setEditTitleError(null)
    setEditSubmitError(null)
  }

  const handleCancelEdit = () => {
    setEditingTaskId(null)
    setEditingField(null)
    setEditTitle('')
    setEditDueDate('')
    setEditTitleError(null)
    setEditSubmitError(null)
  }

  const handleSaveEdit = async (task: LeadTask, field: 'title' | 'due_date') => {
    if (typeof task.id !== 'number' || task.id <= 0) return
    if (editSubmittingRef.current) return

    if (field === 'title') {
      const error = validateTitle(editTitle)
      if (error) {
        setEditTitleError(error)
        return
      }
      if (editTitle.trim() === task.title) {
        if (editingRef.current.id === task.id && editingRef.current.field === field) {
          handleCancelEdit()
        }
        return
      }
    } else {
      const nextDue = editDueDate || null
      if (nextDue === (task.due_date ?? null)) {
        if (editingRef.current.id === task.id && editingRef.current.field === field) {
          handleCancelEdit()
        }
        return
      }
    }

    const saveForId = task.id
    const saveForField = field
    setEditTitleError(null)
    setEditSubmitError(null)
    editSubmittingRef.current = true
    setEditSubmitting(true)

    const payload =
      field === 'title'
        ? { title: editTitle.trim() }
        : { due_date: editDueDate || null }

    try {
      const updated = await leadTaskService.updateTask(leadId, task.id, payload)
      onTaskUpdated?.({
        ...task,
        ...updated,
        lead_id: updated.lead_id ?? task.lead_id ?? leadId,
        task_type: updated.task_type ?? task.task_type,
        created_at: updated.created_at ?? task.created_at,
        completed_at: updated.completed_at ?? task.completed_at,
        created_by: updated.created_by ?? task.created_by,
        title: updated.title ?? (field === 'title' ? editTitle.trim() : task.title),
        due_date:
          updated.due_date !== undefined
            ? updated.due_date
            : field === 'due_date'
              ? editDueDate || null
              : task.due_date,
      })
      // Don't dismiss a different field the user opened while this save was in flight.
      if (editingRef.current.id === saveForId && editingRef.current.field === saveForField) {
        handleCancelEdit()
      }
    } catch (err) {
      setEditSubmitError(
        err instanceof Error ? err.message : 'Failed to update task. Please try again.',
      )
    } finally {
      editSubmittingRef.current = false
      setEditSubmitting(false)
    }
  }

  const commitEditField = (task: LeadTask, field: 'title' | 'due_date') => {
    skipBlurSaveRef.current = true
    void handleSaveEdit(task, field).finally(() => {
      // Allow later blurs after the Enter-driven commit finishes.
      skipBlurSaveRef.current = false
    })
  }

  const suppressCancelBlurSave = () => {
    skipBlurSaveRef.current = true
    window.setTimeout(() => {
      skipBlurSaveRef.current = false
    }, 0)
  }

  const handleEditBlur = (task: LeadTask, field: 'title' | 'due_date') => {
    if (skipBlurSaveRef.current || editSubmittingRef.current) return
    void handleSaveEdit(task, field)
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box data-testid="lead-task-list">
      {/* Section header */}
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography sx={ccSubsectionTitleSx}>
          Open tasks
          {openTasks.length > 0 && (
            <Chip
              label={openTasks.length}
              size="small"
              sx={{ ml: 1 }}
              data-testid="task-count-badge"
            />
          )}
        </Typography>
        {!formOpen && (
          <Button
            size="small"
            startIcon={<AddIcon />}
            onClick={handleOpenForm}
            data-testid="open-task-form-btn"
          >
            Add Task
          </Button>
        )}
      </Stack>

      {awaitingMailBatch && (
        <Chip
          label="Awaiting mail batch"
          size="small"
          color="info"
          sx={{ mb: 1.5 }}
          data-testid="awaiting-mail-batch-chip"
        />
      )}

      {noOpenTasksWhileAwaitingMail && (
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          sx={{ mb: 1.5 }}
          data-testid="mail-awaiting-paused-note"
        >
          Outreach paused — waiting for batch send.
        </Typography>
      )}

      {/* create_task CTA — shown when RA is create_task and no open tasks */}
      {showCreateTaskCTA && !formOpen && (
        <Box sx={{ mb: 2 }} data-testid="create-task-cta">
          <Button
            variant="contained"
            color="primary"
            startIcon={<AddTaskIcon />}
            onClick={handleOpenForm}
            data-testid="create-task-cta-button"
          >
            Create Task
          </Button>
        </Box>
      )}

      {/* Task list */}
      {sortedTasks.length > 0 && (
        <List dense disablePadding data-testid="task-list">
          {sortedTasks.map((task, index) => {
            const dueStatus = getTaskDueStatus(task.due_date)
            const overdue = dueStatus === 'overdue'
            const dueToday = dueStatus === 'due_today'
            const isHubSpot = task.source === 'hubspot'
            const canEdit = typeof task.id === 'number' && task.id > 0
            const editingTitle =
              canEdit && editingTaskId === task.id && editingField === 'title'
            const editingDue =
              canEdit && editingTaskId === task.id && editingField === 'due_date'
            const showContactOnTask =
              showOutreachContactOnPrimaryTask
              && index === 0
              && (outreachContact || missingOutreachChannel)

            return (
              <Box key={task.id}>
                {index > 0 && <Divider component="li" />}
                <ListItem
                  data-testid={`task-item-${task.id}`}
                  sx={{
                    ...(overdue
                      ? { borderLeft: 3, borderColor: 'error.main', pl: 1.5, ml: 0 }
                      : {}),
                    ...((onTaskCompleted || isHubSpot) ? { pr: 6 } : {}),
                  }}
                  secondaryAction={
                    !isHubSpot && onTaskCompleted ? (
                      <IconButton
                        edge="end"
                        aria-label={`Complete task: ${task.title}`}
                        onClick={() => onTaskCompleted(task.id as number)}
                        data-testid={`complete-task-btn-${task.id}`}
                        size="small"
                      >
                        <CheckCircleOutlineIcon fontSize="small" />
                      </IconButton>
                    ) : isHubSpot ? (
                      <Tooltip title="Attempts to mark as done in HubSpot; will mark locally if HubSpot update fails">
                        <span>
                          <IconButton
                            edge="end"
                            aria-label={`Mark HubSpot task done: ${task.title}`}
                            onClick={async () => {
                              const rawId = String(task.id)
                              const isLegacyCrm = rawId.startsWith('hs-')
                              const numericId = parseInt(rawId.replace(/^hs-/, ''), 10)
                              setMarkingDone(numericId)
                              try {
                                await callLogService.markHubSpotTaskDone(leadId, numericId, {
                                  idNamespace: isLegacyCrm ? 'crm_task' : 'lead_task',
                                })
                                if (onHubSpotTaskDone) onHubSpotTaskDone(numericId)
                                if (onTaskCompleted) onTaskCompleted(task.id)
                              } finally {
                                setMarkingDone(null)
                              }
                            }}
                            disabled={markingDone === parseInt(String(task.id).replace('hs-', ''), 10)}
                            data-testid={`mark-done-btn-${task.id}`}
                            size="small"
                          >
                            {markingDone === parseInt(String(task.id).replace('hs-', ''), 10)
                              ? <CircularProgress size={14} />
                              : <CheckCircleOutlineIcon fontSize="small" />
                            }
                          </IconButton>
                        </span>
                      </Tooltip>
                    ) : undefined
                  }
                >
                  <ListItemText
                    primary={
                      <Stack spacing={0.5} sx={{ pr: 1 }}>
                        {editSubmitError && editingTaskId === task.id && (
                          <Alert
                            severity="error"
                            sx={{ py: 0 }}
                            onClose={() => setEditSubmitError(null)}
                            data-testid="task-edit-error"
                          >
                            {editSubmitError}
                          </Alert>
                        )}
                        <Stack direction="row" alignItems="center" spacing={0.5} flexWrap="wrap">
                          {editingTitle ? (
                            <TextField
                              value={editTitle}
                              onChange={(e) => {
                                setEditTitle(e.target.value)
                                if (editTitleError) setEditTitleError(null)
                              }}
                              error={!!editTitleError}
                              helperText={editTitleError}
                              size="small"
                              fullWidth
                              autoFocus
                              disabled={editSubmitting}
                              inputProps={{
                                maxLength: 255,
                                'data-testid': 'task-edit-title-input',
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault()
                                  commitEditField(task, 'title')
                                } else if (e.key === 'Escape') {
                                  e.preventDefault()
                                  suppressCancelBlurSave()
                                  handleCancelEdit()
                                }
                              }}
                              onBlur={() => handleEditBlur(task, 'title')}
                              sx={{ flex: 1, minWidth: 140 }}
                            />
                          ) : (
                            <>
                              <Box
                                component="span"
                                onClick={canEdit ? () => handleStartEdit(task, 'title') : undefined}
                                data-testid={`task-title-${task.id}`}
                                sx={{
                                  cursor: canEdit ? 'pointer' : 'default',
                                  borderRadius: 0.5,
                                  px: 0.25,
                                  '&:hover': canEdit
                                    ? { bgcolor: 'action.hover' }
                                    : undefined,
                                }}
                              >
                                {task.title}
                              </Box>
                              {canEdit && (
                                <Tooltip title="Edit title">
                                  <IconButton
                                    aria-label={`Edit title: ${task.title}`}
                                    onClick={() => handleStartEdit(task, 'title')}
                                    data-testid={`edit-task-btn-${task.id}`}
                                    size="small"
                                    sx={{ p: 0.25 }}
                                  >
                                    <EditOutlinedIcon sx={{ fontSize: 14 }} />
                                  </IconButton>
                                </Tooltip>
                              )}
                            </>
                          )}
                          {overdue && (
                            <Chip
                              label="Overdue"
                              size="small"
                              color="error"
                              sx={{ height: 18, fontSize: '0.65rem' }}
                              data-testid={`task-overdue-chip-${task.id}`}
                            />
                          )}
                          {dueToday && (
                            <Chip
                              label="Due today"
                              size="small"
                              color="warning"
                              sx={{ height: 18, fontSize: '0.65rem' }}
                              data-testid={`task-due-today-chip-${task.id}`}
                            />
                          )}
                          {isHubSpot && (
                            <Chip
                              icon={<HubIcon sx={{ fontSize: '12px !important' }} />}
                              label="HubSpot"
                              size="small"
                              sx={{
                                height: 18,
                                fontSize: '0.65rem',
                                bgcolor: '#ff7a59',
                                color: '#fff',
                                '& .MuiChip-icon': { color: '#fff' },
                              }}
                            />
                          )}
                        </Stack>
                      </Stack>
                    }
                    secondary={
                      <>
                        {editingDue ? (
                          <TextField
                            type="date"
                            value={editDueDate}
                            onChange={(e) => setEditDueDate(e.target.value)}
                            size="small"
                            autoFocus
                            disabled={editSubmitting}
                            InputLabelProps={{ shrink: true }}
                            helperText={
                              isHubSpot ? 'Also pushes to HubSpot when possible.' : undefined
                            }
                            inputProps={{ 'data-testid': 'task-edit-due-date-input' }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                commitEditField(task, 'due_date')
                              } else if (e.key === 'Escape') {
                                e.preventDefault()
                                suppressCancelBlurSave()
                                handleCancelEdit()
                              }
                            }}
                            onBlur={() => handleEditBlur(task, 'due_date')}
                            sx={{ mt: 0.5, maxWidth: 200 }}
                          />
                        ) : (
                          (task.due_date || dueStatus === 'no_due') && (
                            <Typography
                              component="span"
                              variant="caption"
                              color={
                                overdue
                                  ? 'error'
                                  : dueToday
                                    ? 'warning.main'
                                    : dueStatus === 'no_due'
                                      ? 'info.main'
                                      : 'text.secondary'
                              }
                              data-testid={`task-due-date-${task.id}`}
                              onClick={canEdit ? () => handleStartEdit(task, 'due_date') : undefined}
                              sx={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 0.25,
                                mt: 0.25,
                                cursor: canEdit ? 'pointer' : 'default',
                                borderRadius: 0.5,
                                px: 0.25,
                                '&:hover': canEdit ? { bgcolor: 'action.hover' } : undefined,
                              }}
                            >
                              {formatDueDate(task.due_date)}
                              {overdue && ' (overdue)'}
                              {canEdit && (
                                <EditOutlinedIcon sx={{ fontSize: 12, opacity: 0.7 }} />
                              )}
                            </Typography>
                          )
                        )}
                        {showContactOnTask && outreachContact && (
                          <OutreachContactInline contact={outreachContact} />
                        )}
                        {showContactOnTask && !outreachContact && missingOutreachChannel && (
                          <OutreachContactMissingHint channel={missingOutreachChannel} />
                        )}
                        {task.source === 'hubspot' && (
                          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                            HubSpot task — complete in HubSpot to close
                          </Typography>
                        )}
                      </>
                    }
                  />
                </ListItem>
              </Box>
            )
          })}
        </List>
      )}

      {/* Empty state (no tasks, no CTA) */}
      {sortedTasks.length === 0 && !showCreateTaskCTA && (
        <Typography
          variant="body2"
          color="text.secondary"
          data-testid="no-tasks-message"
        >
          No open tasks.
        </Typography>
      )}

      {/* Inline task creation form */}
      {formOpen && (
        <Box
          component="form"
          onSubmit={(e) => {
            e.preventDefault()
            handleSubmit()
          }}
          sx={{ mt: 2, p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}
          data-testid="task-creation-form"
        >
          <Typography variant="subtitle2" gutterBottom>
            New Task
          </Typography>

          {/* Server-level error */}
          {submitError && (
            <Alert
              severity="error"
              sx={{ mb: 2 }}
              onClose={() => setSubmitError(null)}
              data-testid="task-submit-error"
            >
              {submitError}
            </Alert>
          )}

          <FormControl fullWidth size="small" sx={{ mb: 2 }}>
            <InputLabel id="task-type-label">Type</InputLabel>
            <Select
              labelId="task-type-label"
              label="Type"
              value={taskType}
              onChange={(e) => handleTaskTypeChange(e.target.value as LeadTaskType)}
              inputProps={{ 'data-testid': 'task-type-select' }}
            >
              {CREATE_TASK_TYPES.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            label="Title"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              if (titleError) setTitleError(null)
            }}
            error={!!titleError}
            helperText={titleError ?? `${title.length}/255`}
            fullWidth
            size="small"
            sx={{ mb: 2 }}
            inputProps={{ maxLength: 255, 'data-testid': 'task-title-input' }}
          />

          <TextField
            label="Due Date (optional)"
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            fullWidth
            size="small"
            sx={{ mb: 2 }}
            InputLabelProps={{ shrink: true }}
            inputProps={{ 'data-testid': 'task-due-date-input' }}
          />

          <Stack direction="row" spacing={1} justifyContent="flex-end">
            <Button
              size="small"
              onClick={handleCloseForm}
              disabled={submitting}
              data-testid="cancel-task-btn"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="contained"
              size="small"
              disabled={submitting}
              startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : undefined}
              data-testid="save-task-btn"
            >
              {submitting ? 'Saving…' : 'Save Task'}
            </Button>
          </Stack>
        </Box>
      )}
    </Box>
  )
})

export default LeadTaskList
