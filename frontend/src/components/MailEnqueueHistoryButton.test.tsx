import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor } from '@/test/testUtils'
import openLetterService from '@/services/openLetterApi'
import { MailEnqueueHistoryButton } from './MailEnqueueHistoryButton'

vi.mock('@/services/openLetterApi', () => ({
  default: {
    listEnqueueAttempts: vi.fn(),
    getEnqueueAttempt: vi.fn(),
  },
}))

describe('MailEnqueueHistoryButton', () => {
  it('does not open fetched details after the history dialog is closed', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    let resolveDetail: ((value: {
      id: number
      requested_count: number
      added: number
      skipped: number
      invalid: number
      results: []
    }) => void) | undefined
    vi.mocked(openLetterService.listEnqueueAttempts).mockResolvedValue({
      attempts: [{
        id: 7,
        requested_count: 1,
        added: 1,
        skipped: 0,
        invalid: 0,
        created_at: '2026-07-15T18:00:00Z',
      }],
    })
    vi.mocked(openLetterService.getEnqueueAttempt).mockReturnValue(
      new Promise((resolve) => {
        resolveDetail = resolve
      }),
    )

    render(<MailEnqueueHistoryButton />)
    await user.click(screen.getByRole('button', { name: 'Recent mail attempts' }))
    await user.click(await screen.findByText('1 staged · 0 need attention'))
    await user.click(screen.getByRole('button', { name: 'Close' }))

    resolveDetail?.({
      id: 7,
      requested_count: 1,
      added: 1,
      skipped: 0,
      invalid: 0,
      results: [],
    })

    await waitFor(() => {
      expect(screen.queryByText('Direct mail attempt')).not.toBeInTheDocument()
    })
  })
})
