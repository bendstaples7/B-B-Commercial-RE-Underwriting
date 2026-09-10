import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MailQueueStagedTable } from './MailQueueStagedTable'
import { NotificationProvider, globalNotify } from '@/context/NotificationContext'
import openLetterService, { type MailQueueItem } from '@/services/openLetterApi'
import { userFacingApiErrorMessage } from '@/services/httpClient'

vi.mock('@/services/openLetterApi', () => ({
  default: {
    removeFromQueue: vi.fn(),
    removeManyFromQueue: vi.fn(),
  },
}))

const items: MailQueueItem[] = [
  {
    id: 11,
    lead_id: 101,
    user_id: 'u1',
    status: 'queued',
    owner_name: 'Ada Lovelace',
    property_street: '1 Analytical Engine St',
    mailing_address: '1 Analytical Engine St',
    mailing_city: 'Chicago',
    mailing_state: 'IL',
    mailing_zip: '60601',
    created_at: '2026-07-01T12:00:00Z',
  },
  {
    id: 12,
    lead_id: 102,
    user_id: 'u1',
    status: 'queued',
    owner_name: 'Grace Hopper',
    property_street: '2 Compiler Ave',
    mailing_address: '2 Compiler Ave',
    mailing_city: 'Chicago',
    mailing_state: 'IL',
    mailing_zip: '60602',
    created_at: '2026-07-02T12:00:00Z',
  },
]

/** Mirrors main.tsx MutationCache → globalNotify toast wiring. */
function createMailQueueTestQueryClient(): QueryClient {
  return new QueryClient({
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.options.onError) return
        globalNotify.showError((error as Error)?.message ?? 'An unexpected error occurred.')
      },
    }),
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function renderTable(rows: MailQueueItem[] = items) {
  const queryClient = createMailQueueTestQueryClient()
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NotificationProvider>
          <MailQueueStagedTable items={rows} />
        </NotificationProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, queryClient }
}

describe('MailQueueStagedTable', () => {
  beforeEach(() => {
    vi.mocked(openLetterService.removeFromQueue).mockReset()
    vi.mocked(openLetterService.removeManyFromQueue).mockReset()
  })

  it('unwraps Mail queue error envelopes for toasts', () => {
    expect(userFacingApiErrorMessage({
      error: 'Mail queue error',
      message: 'Only queued items can be removed (status is sent)',
    })).toBe('Only queued items can be removed (status is sent)')
  })

  it('toasts the server message when single remove fails', async () => {
    const user = userEvent.setup()
    vi.mocked(openLetterService.removeFromQueue).mockRejectedValue(
      new Error('Only queued items can be removed (status is sent)'),
    )
    renderTable()

    await user.click(screen.getAllByRole('button', { name: 'Remove from batch' })[0])

    await waitFor(() => {
      expect(screen.getByTestId('global-notification-snackbar')).toHaveTextContent(
        'Only queued items can be removed (status is sent)',
      )
    })
    expect(screen.queryByText('Mail queue error')).not.toBeInTheDocument()
  })

  it('supports checkbox multi-select bulk remove', async () => {
    const user = userEvent.setup()
    vi.mocked(openLetterService.removeManyFromQueue).mockResolvedValue({
      removed: 2,
      already_removed: 0,
      blocked: [],
      queued_count: 0,
      batch_minimum: 50,
      allow_send_below_minimum: false,
      can_send: false,
      items: [],
    })
    renderTable()

    await user.click(screen.getByTestId('mail-queue-staged-select-all'))
    expect(screen.getByTestId('mail-queue-staged-bulk-bar')).toHaveTextContent('2 selected')

    await user.click(screen.getByTestId('mail-queue-staged-bulk-remove'))

    await waitFor(() => {
      expect(openLetterService.removeManyFromQueue).toHaveBeenCalledWith([11, 12])
    })
  })

  it('selects individual rows before bulk remove', async () => {
    const user = userEvent.setup()
    vi.mocked(openLetterService.removeManyFromQueue).mockResolvedValue({
      removed: 1,
      already_removed: 0,
      blocked: [],
      queued_count: 1,
      batch_minimum: 50,
      allow_send_below_minimum: false,
      can_send: false,
      items: [items[1]],
    })
    renderTable()

    await user.click(screen.getByTestId('mail-queue-staged-select-11'))
    const bar = screen.getByTestId('mail-queue-staged-bulk-bar')
    expect(within(bar).getByText('1 selected')).toBeInTheDocument()
    await user.click(screen.getByTestId('mail-queue-staged-bulk-remove'))
    await waitFor(() => {
      expect(openLetterService.removeManyFromQueue).toHaveBeenCalledWith([11])
    })
  })
})
