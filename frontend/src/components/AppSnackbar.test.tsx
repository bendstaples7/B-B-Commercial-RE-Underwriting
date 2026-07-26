import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppSnackbar, APP_TOAST_DURATION_MS, appToastDuration } from './AppSnackbar'
import { NotificationProvider, useNotification } from '@/context/NotificationContext'

describe('appToastDuration', () => {
  it('auto-dismisses success/info and keeps error/warning sticky', () => {
    expect(appToastDuration('error')).toBeNull()
    expect(appToastDuration('warning')).toBeNull()
    expect(appToastDuration('success')).toBe(APP_TOAST_DURATION_MS.default)
    expect(appToastDuration('info')).toBe(APP_TOAST_DURATION_MS.default)
  })
})

describe('AppSnackbar', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('anchors bottom-center and fades out after the default duration', async () => {
    const onClose = vi.fn()
    render(
      <AppSnackbar
        open
        onClose={onClose}
        message="Saved"
        severity="success"
        data-testid="app-snackbar"
      />,
    )

    const snackbar = screen.getByTestId('app-snackbar')
    expect(snackbar.className).toMatch(/MuiSnackbar-anchorOriginBottomCenter/)
    expect(screen.getByText('Saved')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(APP_TOAST_DURATION_MS.default + 100)
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('does not auto-dismiss errors', async () => {
    const onClose = vi.fn()
    render(
      <AppSnackbar
        open
        onClose={onClose}
        message="Failed"
        severity="error"
        data-testid="app-snackbar-error"
      />,
    )

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('ignores clickaway for errors but still allows the Alert close button', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const onClose = vi.fn()
    render(
      <AppSnackbar
        open
        onClose={onClose}
        message="Failed"
        severity="error"
        data-testid="app-snackbar-error"
      />,
    )

    await user.click(screen.getByRole('button', { name: /close/i }))
    expect(onClose).toHaveBeenCalled()
  })
})

function ProbeButton() {
  const { showSuccess, showError } = useNotification()
  return (
    <>
      <button type="button" onClick={() => showSuccess('All good')}>
        Success
      </button>
      <button type="button" onClick={() => showError('Nope')}>
        Error
      </button>
    </>
  )
}

describe('NotificationProvider', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows a bottom-center success toast that auto-dismisses', async () => {
    render(
      <NotificationProvider>
        <ProbeButton />
      </NotificationProvider>,
    )

    await act(async () => {
      screen.getByRole('button', { name: 'Success' }).click()
    })

    const snackbar = await screen.findByTestId('global-notification-snackbar')
    expect(snackbar.className).toMatch(/MuiSnackbar-anchorOriginBottomCenter/)
    expect(screen.getByText('All good')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(APP_TOAST_DURATION_MS.default + 100)
    })
    await waitFor(() => {
      expect(screen.queryByText('All good')).not.toBeInTheDocument()
    })
  })

  it('keeps global errors until dismissed', async () => {
    render(
      <NotificationProvider>
        <ProbeButton />
      </NotificationProvider>,
    )

    await act(async () => {
      screen.getByRole('button', { name: 'Error' }).click()
    })

    expect(await screen.findByText('Nope')).toBeInTheDocument()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(screen.getByText('Nope')).toBeInTheDocument()
  })
})
