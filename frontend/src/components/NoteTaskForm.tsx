/**
 * NoteTaskForm — inline form for creating a Note (Interaction) or Task
 * associated with a lead or organization.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
 */
import React, { useState } from 'react'
import {
  Box,
  Tabs,
  Tab,
  TextField,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  FormHelperText,
  CircularProgress,
  Alert,
  Typography,
} from '@mui/material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { interactionService, crmTaskService } from '@/services/api'
import { InteractionType, InteractionSource, TaskPriority, TaskStatus } from '@/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface NoteTaskFormProps {
  /** Whether this form is attached to a lead or an organization. */
  targetType: 'lead' | 'organization'
  /** The ID of the lead or organization to associate the note/task with. */
  targetId: number
  /** Optional callback invoked after a successful submission. */
  onSuccess?: () => void
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <Box
    role="tabpanel"
    hidden={value !== index}
    id={`note-task-tabpanel-${index}`}
    aria-labelledby={`note-task-tab-${index}`}
    sx={{ pt: 2 }}
  >
    {value === index && children}
  </Box>
)

// ---------------------------------------------------------------------------
// Note form state
// ---------------------------------------------------------------------------

interface NoteFormState {
  body: string
}

interface NoteFormErrors {
  body?: string
}

// ---------------------------------------------------------------------------
// Task form state
// ---------------------------------------------------------------------------

interface TaskFormState {
  title: string
  body: string
  due_date: string
  priority: TaskPriority
}

interface TaskFormErrors {
  title?: string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * NoteTaskForm renders a tabbed form that lets users create a Note or a Task
 * directly from a lead or organization detail page.
 *
 * - Auto-associates the new record with `targetType` / `targetId` (Req 5.3).
 * - On success, invalidates the `['timeline', targetType, targetId]` React
 *   Query cache so the timeline refreshes without a page reload (Req 5.4).
 * - Shows inline validation errors per field (Req 5.5).
 * - Shows a loading indicator on the submit button during the request (Req 5.4).
 */
export const NoteTaskForm: React.FC<NoteTaskFormProps> = ({
  targetType,
  targetId,
  onSuccess,
}) => {
  const queryClient = useQueryClient()

  // Tab state: 0 = Note, 1 = Task
  const [activeTab, setActiveTab] = useState(0)

  // Note form state
  const [noteForm, setNoteForm] = useState<NoteFormState>({ body: '' })
  const [noteErrors, setNoteErrors] = useState<NoteFormErrors>({})

  // Task form state
  const [taskForm, setTaskForm] = useState<TaskFormState>({
    title: '',
    body: '',
    due_date: '',
    priority: TaskPriority.MEDIUM,
  })
  const [taskErrors, setTaskErrors] = useState<TaskFormErrors>({})

  // ---------------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------------

  const noteMutation = useMutation({
    mutationFn: () =>
      interactionService.createInteraction({
        interaction_type: InteractionType.NOTE,
        body: noteForm.body,
        occurred_at: new Date().toISOString(),
        source: InteractionSource.MANUAL,
        associations: [{ target_type: targetType, target_id: targetId }],
      }),
    onSuccess: () => {
      // Invalidate timeline cache so the timeline panel refreshes (Req 5.4)
      queryClient.invalidateQueries({ queryKey: ['timeline', targetType, targetId] })
      setNoteForm({ body: '' })
      setNoteErrors({})
      onSuccess?.()
    },
  })

  const taskMutation = useMutation({
    mutationFn: () =>
      crmTaskService.createTask({
        title: taskForm.title,
        body: taskForm.body || null,
        due_date: taskForm.due_date || null,
        status: TaskStatus.OPEN,
        priority: taskForm.priority,
        source: InteractionSource.MANUAL,
        associations: [{ target_type: targetType, target_id: targetId }],
      }),
    onSuccess: () => {
      // Invalidate timeline cache so the timeline panel refreshes (Req 5.4)
      queryClient.invalidateQueries({ queryKey: ['timeline', targetType, targetId] })
      setTaskForm({ title: '', body: '', due_date: '', priority: TaskPriority.MEDIUM })
      setTaskErrors({})
      onSuccess?.()
    },
  })

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  const validateNote = (): boolean => {
    const errors: NoteFormErrors = {}
    if (!noteForm.body.trim()) {
      errors.body = 'Note body is required.'
    }
    setNoteErrors(errors)
    return Object.keys(errors).length === 0
  }

  const validateTask = (): boolean => {
    const errors: TaskFormErrors = {}
    if (!taskForm.title.trim()) {
      errors.title = 'Task title is required.'
    }
    setTaskErrors(errors)
    return Object.keys(errors).length === 0
  }

  // ---------------------------------------------------------------------------
  // Submit handlers
  // ---------------------------------------------------------------------------

  const handleNoteSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (validateNote()) {
      noteMutation.mutate()
    }
  }

  const handleTaskSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (validateTask()) {
      taskMutation.mutate()
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box>
      <Tabs
        value={activeTab}
        onChange={(_e, newValue: number) => setActiveTab(newValue)}
        aria-label="Note or Task"
        sx={{ borderBottom: 1, borderColor: 'divider' }}
      >
        <Tab
          label="Note"
          id="note-task-tab-0"
          aria-controls="note-task-tabpanel-0"
        />
        <Tab
          label="Task"
          id="note-task-tab-1"
          aria-controls="note-task-tabpanel-1"
        />
      </Tabs>

      {/* ------------------------------------------------------------------ */}
      {/* Note Tab (Req 5.1)                                                  */}
      {/* ------------------------------------------------------------------ */}
      <TabPanel value={activeTab} index={0}>
        <Box
          component="form"
          onSubmit={handleNoteSubmit}
          noValidate
          sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
        >
          {noteMutation.isError && (
            <Alert severity="error">
              {noteMutation.error instanceof Error
                ? noteMutation.error.message
                : 'Failed to save note. Please try again.'}
            </Alert>
          )}

          <TextField
            label="Note"
            multiline
            minRows={3}
            required
            fullWidth
            value={noteForm.body}
            onChange={(e) =>
              setNoteForm((prev) => ({ ...prev, body: e.target.value }))
            }
            error={Boolean(noteErrors.body)}
            helperText={noteErrors.body}
            inputProps={{ 'aria-label': 'Note body' }}
            disabled={noteMutation.isPending}
          />

          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button
              type="submit"
              variant="contained"
              disabled={noteMutation.isPending}
              startIcon={
                noteMutation.isPending ? (
                  <CircularProgress size={16} color="inherit" />
                ) : undefined
              }
            >
              {noteMutation.isPending ? 'Saving…' : 'Save Note'}
            </Button>
          </Box>

          {noteMutation.isSuccess && (
            <Typography variant="body2" color="success.main">
              Note saved successfully.
            </Typography>
          )}
        </Box>
      </TabPanel>

      {/* ------------------------------------------------------------------ */}
      {/* Task Tab (Req 5.2)                                                  */}
      {/* ------------------------------------------------------------------ */}
      <TabPanel value={activeTab} index={1}>
        <Box
          component="form"
          onSubmit={handleTaskSubmit}
          noValidate
          sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
        >
          {taskMutation.isError && (
            <Alert severity="error">
              {taskMutation.error instanceof Error
                ? taskMutation.error.message
                : 'Failed to save task. Please try again.'}
            </Alert>
          )}

          {/* Title — required (Req 3.3) */}
          <TextField
            label="Title"
            required
            fullWidth
            value={taskForm.title}
            onChange={(e) =>
              setTaskForm((prev) => ({ ...prev, title: e.target.value }))
            }
            error={Boolean(taskErrors.title)}
            helperText={taskErrors.title}
            inputProps={{ 'aria-label': 'Task title' }}
            disabled={taskMutation.isPending}
          />

          {/* Body — optional */}
          <TextField
            label="Notes (optional)"
            multiline
            minRows={2}
            fullWidth
            value={taskForm.body}
            onChange={(e) =>
              setTaskForm((prev) => ({ ...prev, body: e.target.value }))
            }
            inputProps={{ 'aria-label': 'Task notes' }}
            disabled={taskMutation.isPending}
          />

          {/* Due date — plain TextField with type="date" (no @mui/x-date-pickers) */}
          <TextField
            label="Due Date"
            type="date"
            fullWidth
            value={taskForm.due_date}
            onChange={(e) =>
              setTaskForm((prev) => ({ ...prev, due_date: e.target.value }))
            }
            InputLabelProps={{ shrink: true }}
            inputProps={{ 'aria-label': 'Task due date' }}
            disabled={taskMutation.isPending}
          />

          {/* Priority selector */}
          <FormControl fullWidth disabled={taskMutation.isPending}>
            <InputLabel id="task-priority-label">Priority</InputLabel>
            <Select
              labelId="task-priority-label"
              label="Priority"
              value={taskForm.priority}
              onChange={(e) =>
                setTaskForm((prev) => ({
                  ...prev,
                  priority: e.target.value as TaskPriority,
                }))
              }
              inputProps={{ 'aria-label': 'Task priority' }}
            >
              <MenuItem value={TaskPriority.HIGH}>High</MenuItem>
              <MenuItem value={TaskPriority.MEDIUM}>Medium</MenuItem>
              <MenuItem value={TaskPriority.LOW}>Low</MenuItem>
            </Select>
            <FormHelperText>Select task priority</FormHelperText>
          </FormControl>

          <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button
              type="submit"
              variant="contained"
              disabled={taskMutation.isPending}
              startIcon={
                taskMutation.isPending ? (
                  <CircularProgress size={16} color="inherit" />
                ) : undefined
              }
            >
              {taskMutation.isPending ? 'Saving…' : 'Save Task'}
            </Button>
          </Box>

          {taskMutation.isSuccess && (
            <Typography variant="body2" color="success.main">
              Task saved successfully.
            </Typography>
          )}
        </Box>
      </TabPanel>
    </Box>
  )
}

export default NoteTaskForm
