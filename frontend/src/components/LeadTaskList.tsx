/**
 * LeadTaskList — displays open tasks for a lead ordered by due_date asc (nulls last),
 * with an inline task creation form.
 *
 * Requirements: 3.2, 3.3, 3.6, 4.3, 7.5, 7.6
 */
import { forwardRef, useImperativeHandle, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import AddTaskIcon from '@mui/icons-material/AddTask'
import HubIcon from '@mui/icons-material/Hub'
import type { LeadTask, CRMRecommendedAction, OutreachContact } from '@/types'
import { leadTaskService, callLogService } from '@/services/api'
import { OutreachContactInline, OutreachContactMissingHint } from '@/components/OutreachContactCallout'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export type TaskDueStatus = 'overdue' | 'due_today' | 'upcoming' | 'no_due'

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
  if (!dueDate) return ''
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
  const [dueDate, setDueDate] = useState('')
  const [titleError, setTitleError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [markingDone, setMarkingDone] = useState<number | null>(null)

  const openTasks = tasks.filter((t) => t.status === 'open' || t.status === 'overdue')
  const sortedTasks = sortTasks(openTasks)
  const showCreateTaskCTA = recommendedAction === 'create_task' && openTasks.length === 0
  const awaitingMailBatch = mailQueueStatus === 'queued' || upNextToMail
  const onlyMailPrepTaskOpen =
    awaitingMailBatch
    && openTasks.length === 1
    && openTasks[0].task_type === 'add_to_mail_batch'

  // ---------------------------------------------------------------------------
  // Form handlers
  // ---------------------------------------------------------------------------

  const handleOpenForm = () => {
    setFormOpen(true)
    setTitle('')
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
    setDueDate('')
    setTitleError(null)
    setSubmitError(null)
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
      task_type: 'custom',
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
        task_type: 'custom',
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

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box data-testid="lead-task-list">
      {/* Section header */}
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" fontWeight="bold">
          Open Tasks
          {openTasks.length > 0 && (
            <Chip
              label={openTasks.length}
              size="small"
              sx={{ ml: 1 }}
              data-testid="task-count-badge"
            />
          )}
        </Typography>        {!formOpen && (
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

      {onlyMailPrepTaskOpen && (
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          sx={{ mb: 1.5 }}
          data-testid="mail-prep-waiting-note"
        >
          Mail prep complete — waiting for batch send.
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
            const showContactOnTask =
              showOutreachContactOnPrimaryTask
              && index === 0
              && (outreachContact || missingOutreachChannel)
            return (
              <Box key={task.id}>
                {index > 0 && <Divider component="li" />}
                <ListItem
                  data-testid={`task-item-${task.id}`}
                  sx={
                    overdue
                      ? { borderLeft: 3, borderColor: 'error.main', pl: 1.5, ml: 0 }
                      : undefined
                  }
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
                              const numericId = parseInt(String(task.id).replace('hs-', ''), 10)
                              setMarkingDone(numericId)
                              try {
                                await callLogService.markHubSpotTaskDone(leadId, numericId)
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
                      <Stack direction="row" alignItems="center" spacing={0.75} flexWrap="wrap">
                        <span>{task.title}</span>
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
                    }
                    secondary={
                      <>
                        {task.due_date && (
                          <Typography
                            component="span"
                            variant="caption"
                            color={
                              overdue ? 'error' : dueToday ? 'warning.main' : 'text.secondary'
                            }
                            data-testid={`task-due-date-${task.id}`}
                            sx={{ display: 'block' }}
                          >
                            {formatDueDate(task.due_date)}
                            {overdue && ' (overdue)'}
                          </Typography>
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
