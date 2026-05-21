/**
 * Tests for LeadTaskList component
 *
 * Covers:
 * - task ordering: due_date asc, nulls last
 * - inline form opens and closes
 * - validation error on empty title
 * - list updates on successful save (calls onTaskCreated, closes form)
 * - form preserved on server error (error shown, form stays open with data)
 * - create_task CTA shown when RA is create_task and no open tasks
 * - create_task CTA not shown when open tasks exist
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LeadTaskList } from './LeadTaskList'
import type { LeadTask, CRMRecommendedAction } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  leadTaskService: {
    createTask: vi.fn(),
  },
}))

import { leadTaskService } from '@/services/api'

// Cast to access the mock function
const mockCreateTask = leadTaskService.createTask as ReturnType<typeof vi.fn>

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeTask(
  id: number,
  overrides: Partial<LeadTask> = {}
): LeadTask {
  return {
    id,
    lead_id: 1,
    task_type: 'custom',
    title: `Task ${id}`,
    status: 'open',
    due_date: null,
    created_at: '2024-01-01T00:00:00Z',
    completed_at: null,
    created_by: 'user',
    ...overrides,
  }
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

describe('LeadTaskList', () => {
  // -------------------------------------------------------------------------
  // Task ordering
  // -------------------------------------------------------------------------

  describe('task ordering', () => {
    it('displays tasks ordered by due_date ascending', () => {
      const tasks = [
        makeTask(1, { due_date: '2024-03-15', title: 'Task C' }),
        makeTask(2, { due_date: '2024-01-10', title: 'Task A' }),
        makeTask(3, { due_date: '2024-02-20', title: 'Task B' }),
      ]

      render(
        <LeadTaskList
          leadId={1}
          tasks={tasks}
          onTaskCreated={vi.fn()}
        />
      )

      const taskList = screen.getByTestId('task-list')
      const items = within(taskList).getAllByRole('listitem')

      // Task A (Jan 10) should be first, Task B (Feb 20) second, Task C (Mar 15) third
      expect(items[0]).toHaveTextContent('Task A')
      expect(items[1]).toHaveTextContent('Task B')
      expect(items[2]).toHaveTextContent('Task C')
    })

    it('displays tasks with null due_date last', () => {
      const tasks = [
        makeTask(1, { due_date: null, title: 'No Date Task' }),
        makeTask(2, { due_date: '2024-01-10', title: 'Has Date Task' }),
      ]

      render(
        <LeadTaskList
          leadId={1}
          tasks={tasks}
          onTaskCreated={vi.fn()}
        />
      )

      const taskList = screen.getByTestId('task-list')
      const items = within(taskList).getAllByRole('listitem')

      expect(items[0]).toHaveTextContent('Has Date Task')
      expect(items[1]).toHaveTextContent('No Date Task')
    })

    it('places multiple null due_date tasks after all dated tasks', () => {
      const tasks = [
        makeTask(1, { due_date: null, title: 'No Date 1' }),
        makeTask(2, { due_date: '2024-06-01', title: 'June Task' }),
        makeTask(3, { due_date: null, title: 'No Date 2' }),
        makeTask(4, { due_date: '2024-01-01', title: 'Jan Task' }),
      ]

      render(
        <LeadTaskList
          leadId={1}
          tasks={tasks}
          onTaskCreated={vi.fn()}
        />
      )

      const taskList = screen.getByTestId('task-list')
      const items = within(taskList).getAllByRole('listitem')

      // Dated tasks first (Jan, June), then null tasks
      expect(items[0]).toHaveTextContent('Jan Task')
      expect(items[1]).toHaveTextContent('June Task')
      // items[2] and items[3] are the null-date tasks (order between them is stable)
      expect(items[2]).toHaveTextContent('No Date')
      expect(items[3]).toHaveTextContent('No Date')
    })

    it('only shows open tasks (filters out completed/cancelled)', () => {
      const tasks = [
        makeTask(1, { status: 'open', title: 'Open Task' }),
        makeTask(2, { status: 'completed', title: 'Completed Task' }),
        makeTask(3, { status: 'cancelled', title: 'Cancelled Task' }),
      ]

      render(
        <LeadTaskList
          leadId={1}
          tasks={tasks}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.getByText('Open Task')).toBeInTheDocument()
      expect(screen.queryByText('Completed Task')).not.toBeInTheDocument()
      expect(screen.queryByText('Cancelled Task')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Inline form opens and closes
  // -------------------------------------------------------------------------

  describe('inline form opens and closes', () => {
    it('does not show the form initially', () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.queryByTestId('task-creation-form')).not.toBeInTheDocument()
    })

    it('shows the form when "Add Task" button is clicked', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))

      expect(screen.getByTestId('task-creation-form')).toBeInTheDocument()
    })

    it('hides the form when Cancel is clicked', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      expect(screen.getByTestId('task-creation-form')).toBeInTheDocument()

      await user.click(screen.getByTestId('cancel-task-btn'))
      expect(screen.queryByTestId('task-creation-form')).not.toBeInTheDocument()
    })

    it('clears form fields when form is closed and reopened', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'My Task')
      await user.click(screen.getByTestId('cancel-task-btn'))

      await user.click(screen.getByTestId('open-task-form-btn'))
      expect(screen.getByTestId('task-title-input')).toHaveValue('')
    })

    it('hides "Add Task" button while form is open', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      expect(screen.queryByTestId('open-task-form-btn')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Validation error on empty title
  // -------------------------------------------------------------------------

  describe('validation error on empty title', () => {
    it('shows validation error when Save is clicked with empty title', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.click(screen.getByTestId('save-task-btn'))

      expect(screen.getByText('Title is required.')).toBeInTheDocument()
    })

    it('shows validation error when title is only whitespace', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), '   ')
      await user.click(screen.getByTestId('save-task-btn'))

      expect(screen.getByText('Title is required.')).toBeInTheDocument()
    })

    it('shows validation error when title exceeds 255 characters', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      // Type a 256-char string (bypassing maxLength via direct value change)
      const input = screen.getByTestId('task-title-input')
      // Use fireEvent to bypass maxLength attribute
      const { fireEvent } = await import('@testing-library/react')
      fireEvent.change(input, { target: { value: 'a'.repeat(256) } })
      await user.click(screen.getByTestId('save-task-btn'))

      expect(screen.getByText('Title must be 255 characters or fewer.')).toBeInTheDocument()
    })

    it('does not call createTask when title is empty', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.click(screen.getByTestId('save-task-btn'))

      expect(mockCreateTask).not.toHaveBeenCalled()
    })

    it('clears validation error when user starts typing', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.click(screen.getByTestId('save-task-btn'))
      expect(screen.getByText('Title is required.')).toBeInTheDocument()

      await user.type(screen.getByTestId('task-title-input'), 'A')
      expect(screen.queryByText('Title is required.')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // List updates on successful save
  // -------------------------------------------------------------------------

  describe('list updates on save', () => {
    it('calls onTaskCreated with the new task on successful save', async () => {
      const newTask = makeTask(99, { title: 'New Task' })
      mockCreateTask.mockResolvedValue(newTask)
      const onTaskCreated = vi.fn()

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={onTaskCreated}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'New Task')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(onTaskCreated).toHaveBeenCalledWith(newTask)
      })
    })

    it('closes the form after successful save', async () => {
      const newTask = makeTask(99, { title: 'New Task' })
      mockCreateTask.mockResolvedValue(newTask)

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'New Task')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(screen.queryByTestId('task-creation-form')).not.toBeInTheDocument()
      })
    })

    it('calls createTask with correct leadId and title', async () => {
      const newTask = makeTask(99, { title: 'Call owner' })
      mockCreateTask.mockResolvedValue(newTask)

      render(
        <LeadTaskList
          leadId={42}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'Call owner')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(mockCreateTask).toHaveBeenCalledWith(42, {
          title: 'Call owner',
          task_type: 'custom',
          due_date: null,
        })
      })
    })

    it('passes due_date when provided', async () => {
      const newTask = makeTask(99, { title: 'Task with date', due_date: '2025-06-15' })
      mockCreateTask.mockResolvedValue(newTask)

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'Task with date')
      // Set due date via fireEvent since date inputs can be tricky with userEvent
      const { fireEvent } = await import('@testing-library/react')
      fireEvent.change(screen.getByTestId('task-due-date-input'), {
        target: { value: '2025-06-15' },
      })
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(mockCreateTask).toHaveBeenCalledWith(1, {
          title: 'Task with date',
          task_type: 'custom',
          due_date: '2025-06-15',
        })
      })
    })
  })

  // -------------------------------------------------------------------------
  // Form preserved on server error
  // -------------------------------------------------------------------------

  describe('form preserved on server error', () => {
    it('shows inline error when createTask rejects', async () => {
      mockCreateTask.mockRejectedValue(new Error('Server error'))

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'My Task')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('task-submit-error')).toHaveTextContent('Server error')
      })
    })

    it('keeps the form open after server error', async () => {
      mockCreateTask.mockRejectedValue(new Error('Server error'))

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'My Task')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('task-submit-error')).toBeInTheDocument()
      })

      // Form should still be open
      expect(screen.getByTestId('task-creation-form')).toBeInTheDocument()
    })

    it('preserves title field data after server error', async () => {
      mockCreateTask.mockRejectedValue(new Error('Server error'))

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'My Task')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('task-submit-error')).toBeInTheDocument()
      })

      // Title should still be present
      expect(screen.getByTestId('task-title-input')).toHaveValue('My Task')
    })

    it('does not call onTaskCreated on server error', async () => {
      mockCreateTask.mockRejectedValue(new Error('Server error'))
      const onTaskCreated = vi.fn()

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={onTaskCreated}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'My Task')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('task-submit-error')).toBeInTheDocument()
      })

      expect(onTaskCreated).not.toHaveBeenCalled()
    })

    it('shows generic error message when rejection is not an Error instance', async () => {
      mockCreateTask.mockRejectedValue('string error')

      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('open-task-form-btn'))
      await user.type(screen.getByTestId('task-title-input'), 'My Task')
      await user.click(screen.getByTestId('save-task-btn'))

      await waitFor(() => {
        expect(screen.getByTestId('task-submit-error')).toHaveTextContent(
          'Failed to create task. Please try again.'
        )
      })
    })
  })

  // -------------------------------------------------------------------------
  // create_task CTA
  // -------------------------------------------------------------------------

  describe('create_task CTA', () => {
    it('shows Create Task CTA when RA is create_task and no open tasks', () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          recommendedAction={'create_task' as CRMRecommendedAction}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.getByTestId('create-task-cta')).toBeInTheDocument()
      expect(screen.getByTestId('create-task-cta-button')).toBeInTheDocument()
    })

    it('does NOT show Create Task CTA when RA is create_task but open tasks exist', () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[makeTask(1)]}
          recommendedAction={'create_task' as CRMRecommendedAction}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.queryByTestId('create-task-cta')).not.toBeInTheDocument()
    })

    it('does NOT show Create Task CTA when RA is not create_task', () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          recommendedAction={'follow_up_now' as CRMRecommendedAction}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.queryByTestId('create-task-cta')).not.toBeInTheDocument()
    })

    it('does NOT show Create Task CTA when recommendedAction is null', () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          recommendedAction={null}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.queryByTestId('create-task-cta')).not.toBeInTheDocument()
    })

    it('opens the task creation form when Create Task CTA is clicked', async () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          recommendedAction={'create_task' as CRMRecommendedAction}
          onTaskCreated={vi.fn()}
        />
      )

      await user.click(screen.getByTestId('create-task-cta-button'))
      expect(screen.getByTestId('task-creation-form')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Empty state
  // -------------------------------------------------------------------------

  describe('empty state', () => {
    it('shows "No open tasks." when no tasks and no create_task CTA', () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.getByTestId('no-tasks-message')).toHaveTextContent('No open tasks.')
    })

    it('does not show "No open tasks." when create_task CTA is shown', () => {
      render(
        <LeadTaskList
          leadId={1}
          tasks={[]}
          recommendedAction={'create_task' as CRMRecommendedAction}
          onTaskCreated={vi.fn()}
        />
      )

      expect(screen.queryByTestId('no-tasks-message')).not.toBeInTheDocument()
    })
  })
})
