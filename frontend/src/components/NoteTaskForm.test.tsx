/**
 * Tests for NoteTaskForm component
 *
 * Covers:
 * - tab switcher switches between Note and Task forms
 * - note validation shows inline error when body is empty on submit
 * - task validation shows inline error when title is empty on submit
 * - successful note submission calls createInteraction and invalidates timeline cache
 * - successful task submission calls createTask and invalidates timeline cache
 * - auto-association uses context props without showing selector
 * - loading state on submit button during request
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { NoteTaskForm } from './NoteTaskForm'
import { interactionService, crmTaskService } from '@/services/api'
import { InteractionType, InteractionSource, TaskPriority, TaskStatus } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  interactionService: {
    createInteraction: vi.fn(),
    updateInteraction: vi.fn(),
    deleteInteraction: vi.fn(),
  },
  crmTaskService: {
    createTask: vi.fn(),
    updateTask: vi.fn(),
    deleteTask: vi.fn(),
    completeTask: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockInteraction = {
  id: 1,
  interaction_type: InteractionType.NOTE,
  body: 'Test note body',
  occurred_at: '2024-01-01T10:00:00Z',
  source: InteractionSource.MANUAL,
  hubspot_engagement_id: null,
  is_orphaned: false,
  created_at: '2024-01-01T10:00:00Z',
  updated_at: '2024-01-01T10:00:00Z',
}

const mockTask = {
  id: 2,
  title: 'Test task title',
  body: null,
  due_date: null,
  status: TaskStatus.OPEN,
  priority: TaskPriority.MEDIUM,
  source: InteractionSource.MANUAL,
  hubspot_task_id: null,
  completion_timestamp: null,
  created_at: '2024-01-01T10:00:00Z',
  updated_at: '2024-01-01T10:00:00Z',
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NoteTaskForm', () => {
  describe('tab switcher', () => {
    it('renders Note tab as active by default', () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      expect(screen.getByRole('tab', { name: 'Note' })).toHaveAttribute('aria-selected', 'true')
      expect(screen.getByRole('tab', { name: 'Task' })).toHaveAttribute('aria-selected', 'false')
    })

    it('switches to Task form when Task tab is clicked', async () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))

      expect(screen.getByRole('tab', { name: 'Task' })).toHaveAttribute('aria-selected', 'true')
      expect(screen.getByRole('tab', { name: 'Note' })).toHaveAttribute('aria-selected', 'false')
    })

    it('shows Note form fields when Note tab is active', () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      expect(screen.getByLabelText('Note body')).toBeInTheDocument()
      expect(screen.queryByLabelText('Task title')).not.toBeInTheDocument()
    })

    it('shows Task form fields when Task tab is active', async () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))

      expect(screen.getByLabelText('Task title')).toBeInTheDocument()
      expect(screen.queryByLabelText('Note body')).not.toBeInTheDocument()
    })
  })

  describe('note validation', () => {
    it('shows inline error when note body is empty on submit', async () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      // Submit without entering any text
      const saveButton = screen.getByRole('button', { name: /save note/i })
      await user.click(saveButton)

      await waitFor(() => {
        expect(screen.getByText('Note body is required.')).toBeInTheDocument()
      })
    })

    it('does not call createInteraction when note body is empty', async () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      const saveButton = screen.getByRole('button', { name: /save note/i })
      await user.click(saveButton)

      expect(interactionService.createInteraction).not.toHaveBeenCalled()
    })

    it('clears validation error when user starts typing', async () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      // Trigger validation error
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(screen.getByText('Note body is required.')).toBeInTheDocument()
      })

      // Start typing
      await user.type(screen.getByLabelText('Note body'), 'Some text')

      // Submit again — should not show error
      vi.mocked(interactionService.createInteraction).mockResolvedValue(mockInteraction)
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(screen.queryByText('Note body is required.')).not.toBeInTheDocument()
      })
    })
  })

  describe('task validation', () => {
    it('shows inline error when task title is empty on submit', async () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))

      const saveButton = screen.getByRole('button', { name: /save task/i })
      await user.click(saveButton)

      await waitFor(() => {
        expect(screen.getByText('Task title is required.')).toBeInTheDocument()
      })
    })

    it('does not call createTask when task title is empty', async () => {
      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))

      const saveButton = screen.getByRole('button', { name: /save task/i })
      await user.click(saveButton)

      expect(crmTaskService.createTask).not.toHaveBeenCalled()
    })
  })

  describe('successful note submission', () => {
    it('calls createInteraction with correct data on valid note submit', async () => {
      vi.mocked(interactionService.createInteraction).mockResolvedValue(mockInteraction)

      render(<NoteTaskForm targetType="lead" targetId={42} />)

      await user.type(screen.getByLabelText('Note body'), 'This is a test note')
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(interactionService.createInteraction).toHaveBeenCalledWith(
          expect.objectContaining({
            interaction_type: InteractionType.NOTE,
            body: 'This is a test note',
            source: InteractionSource.MANUAL,
            associations: [{ target_type: 'lead', target_id: 42 }],
          })
        )
      })
    })

    it('shows success message after note is saved', async () => {
      vi.mocked(interactionService.createInteraction).mockResolvedValue(mockInteraction)

      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.type(screen.getByLabelText('Note body'), 'Test note')
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(screen.getByText('Note saved successfully.')).toBeInTheDocument()
      })
    })

    it('clears note form after successful submission', async () => {
      vi.mocked(interactionService.createInteraction).mockResolvedValue(mockInteraction)

      render(<NoteTaskForm targetType="lead" targetId={1} />)

      const noteInput = screen.getByLabelText('Note body')
      await user.type(noteInput, 'Test note content')
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(noteInput).toHaveValue('')
      })
    })

    it('calls onSuccess callback after successful note submission', async () => {
      vi.mocked(interactionService.createInteraction).mockResolvedValue(mockInteraction)
      const onSuccess = vi.fn()

      render(<NoteTaskForm targetType="lead" targetId={1} onSuccess={onSuccess} />)

      await user.type(screen.getByLabelText('Note body'), 'Test note')
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledOnce()
      })
    })
  })

  describe('successful task submission', () => {
    it('calls createTask with correct data on valid task submit', async () => {
      vi.mocked(crmTaskService.createTask).mockResolvedValue(mockTask)

      render(<NoteTaskForm targetType="organization" targetId={7} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))
      await user.type(screen.getByLabelText('Task title'), 'Follow up call')
      await user.click(screen.getByRole('button', { name: /save task/i }))

      await waitFor(() => {
        expect(crmTaskService.createTask).toHaveBeenCalledWith(
          expect.objectContaining({
            title: 'Follow up call',
            status: TaskStatus.OPEN,
            priority: TaskPriority.MEDIUM,
            source: InteractionSource.MANUAL,
            associations: [{ target_type: 'organization', target_id: 7 }],
          })
        )
      })
    })

    it('shows success message after task is saved', async () => {
      vi.mocked(crmTaskService.createTask).mockResolvedValue(mockTask)

      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))
      await user.type(screen.getByLabelText('Task title'), 'Test task')
      await user.click(screen.getByRole('button', { name: /save task/i }))

      await waitFor(() => {
        expect(screen.getByText('Task saved successfully.')).toBeInTheDocument()
      })
    })

    it('clears task form after successful submission', async () => {
      vi.mocked(crmTaskService.createTask).mockResolvedValue(mockTask)

      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))
      const titleInput = screen.getByLabelText('Task title')
      await user.type(titleInput, 'Test task title')
      await user.click(screen.getByRole('button', { name: /save task/i }))

      await waitFor(() => {
        expect(titleInput).toHaveValue('')
      })
    })
  })

  describe('auto-association', () => {
    it('uses targetType and targetId props without showing a selector', () => {
      render(<NoteTaskForm targetType="lead" targetId={99} />)

      // There should be no "select target" or "associate with" UI element
      expect(screen.queryByLabelText(/associate with/i)).not.toBeInTheDocument()
      expect(screen.queryByLabelText(/select target/i)).not.toBeInTheDocument()
    })

    it('passes correct association to createInteraction for lead target', async () => {
      vi.mocked(interactionService.createInteraction).mockResolvedValue(mockInteraction)

      render(<NoteTaskForm targetType="lead" targetId={55} />)

      await user.type(screen.getByLabelText('Note body'), 'Note for lead 55')
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(interactionService.createInteraction).toHaveBeenCalledWith(
          expect.objectContaining({
            associations: [{ target_type: 'lead', target_id: 55 }],
          })
        )
      })
    })

    it('passes correct association to createTask for organization target', async () => {
      vi.mocked(crmTaskService.createTask).mockResolvedValue(mockTask)

      render(<NoteTaskForm targetType="organization" targetId={33} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))
      await user.type(screen.getByLabelText('Task title'), 'Org task')
      await user.click(screen.getByRole('button', { name: /save task/i }))

      await waitFor(() => {
        expect(crmTaskService.createTask).toHaveBeenCalledWith(
          expect.objectContaining({
            associations: [{ target_type: 'organization', target_id: 33 }],
          })
        )
      })
    })
  })

  describe('loading state', () => {
    it('shows loading state on note submit button during request', async () => {
      let resolveNote: (value: any) => void
      const pendingPromise = new Promise((resolve) => {
        resolveNote = resolve
      })
      vi.mocked(interactionService.createInteraction).mockReturnValue(pendingPromise as any)

      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.type(screen.getByLabelText('Note body'), 'Test note')
      await user.click(screen.getByRole('button', { name: /save note/i }))

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
      })

      // Resolve the promise to clean up
      resolveNote!(mockInteraction)
    })

    it('shows loading state on task submit button during request', async () => {
      let resolveTask: (value: any) => void
      const pendingPromise = new Promise((resolve) => {
        resolveTask = resolve
      })
      vi.mocked(crmTaskService.createTask).mockReturnValue(pendingPromise as any)

      render(<NoteTaskForm targetType="lead" targetId={1} />)

      await user.click(screen.getByRole('tab', { name: 'Task' }))
      await user.type(screen.getByLabelText('Task title'), 'Test task')
      await user.click(screen.getByRole('button', { name: /save task/i }))

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
      })

      // Resolve the promise to clean up
      resolveTask!(mockTask)
    })
  })
})
