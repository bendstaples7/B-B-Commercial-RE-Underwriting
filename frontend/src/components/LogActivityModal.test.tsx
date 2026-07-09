/**
 * Tests for LogActivityModal component
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LogActivityModal } from './LogActivityModal'
import type { LeadTimelineEntry } from '@/types'

vi.mock('@/services/api', () => ({
  callLogService: {
    logNote: vi.fn(),
    logCall: vi.fn(),
  },
  contactService: {
    getPropertyContacts: vi.fn().mockResolvedValue([]),
  },
}))

import { callLogService } from '@/services/api'

const mockLogNote = callLogService.logNote as ReturnType<typeof vi.fn>
const user = userEvent.setup({ pointerEventsCheck: 0 })

function makeEntry(overrides: Partial<LeadTimelineEntry> = {}): LeadTimelineEntry {
  return {
    id: 1,
    lead_id: 1,
    event_type: 'note_added',
    occurred_at: '2024-01-01T00:00:00Z',
    source: 'manual',
    actor: 'user',
    summary: 'Saved note',
    metadata: { body: 'Saved note' },
    hubspot_activity_id: null,
    is_deleted: false,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LogActivityModal', () => {
  it('renders the note form when activityType is note', () => {
    render(
      <LogActivityModal
        open
        activityType="note"
        leadId={1}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    )

    expect(screen.getByTestId('log-activity-modal-note')).toBeInTheDocument()
    expect(screen.getByTestId('log-note-form')).toBeInTheDocument()
  })

  it('calls onClose when Cancel is clicked', async () => {
    const onClose = vi.fn()

    render(
      <LogActivityModal
        open
        activityType="note"
        leadId={1}
        onClose={onClose}
        onSaved={vi.fn()}
      />,
    )

    await user.click(screen.getByTestId('note-cancel-btn'))
    expect(onClose).toHaveBeenCalled()
  })

  it('calls onSaved with entry and activity type on successful save', async () => {
    const entry = makeEntry()
    mockLogNote.mockResolvedValue(entry)
    const onSaved = vi.fn()

    render(
      <LogActivityModal
        open
        activityType="note"
        leadId={1}
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    )

    await user.type(screen.getByTestId('note-body-input'), 'Saved note')
    await user.click(screen.getByTestId('note-save-btn'))

    await waitFor(() => {
      expect(onSaved).toHaveBeenCalledWith(
        expect.objectContaining({ summary: 'Saved note' }),
        'note',
        undefined,
      )
    })
  })
})
