import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import {
  QueueAdvanceHoldBanner,
  QUEUE_ADVANCE_HOLD_MS,
  QUEUE_ADVANCE_HOLD_Z_INDEX,
  QUEUE_ADVANCE_NEXT_LABEL,
  QUEUE_ADVANCE_QUEUE_LABEL,
  queueAdvanceDrainTransition,
} from '@/components/lead-detail/QueueAdvanceHoldBanner'

describe('QueueAdvanceHoldBanner', () => {
  it('settles with progress landmark, message, and Pause control', async () => {
    const onPause = vi.fn()
    render(
      <QueueAdvanceHoldBanner
        message="Lead deprioritized"
        onPause={onPause}
      />,
    )

    const hold = screen.getByTestId('queue-advance-hold')
    expect(hold).toBeInTheDocument()
    expect(hold).toHaveTextContent('Lead deprioritized')
    expect(hold).toHaveTextContent(QUEUE_ADVANCE_NEXT_LABEL)
    const bar = screen.getByRole('progressbar', { name: QUEUE_ADVANCE_NEXT_LABEL })
    expect(bar).toBeInTheDocument()
    expect(bar).toHaveAttribute('data-drain-ms', String(QUEUE_ADVANCE_HOLD_MS))
    expect(QUEUE_ADVANCE_HOLD_MS).toBe(5000)
    expect(screen.getByTestId('queue-advance-pause')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('queue-advance-pause'))
    expect(onPause).toHaveBeenCalledTimes(1)
  })

  it('pauses when Escape is pressed', async () => {
    const onPause = vi.fn()
    render(
      <QueueAdvanceHoldBanner
        message="Task completed"
        onPause={onPause}
      />,
    )

    await userEvent.keyboard('{Escape}')
    expect(onPause).toHaveBeenCalledTimes(1)
  })

  it('names the end-of-queue destination instead of next lead', () => {
    render(
      <QueueAdvanceHoldBanner
        message="Task completed"
        destinationLabel={QUEUE_ADVANCE_QUEUE_LABEL}
        onPause={() => {}}
      />,
    )

    const hold = screen.getByTestId('queue-advance-hold')
    expect(hold).toHaveTextContent(QUEUE_ADVANCE_QUEUE_LABEL)
    expect(hold).not.toHaveTextContent(QUEUE_ADVANCE_NEXT_LABEL)
    expect(screen.getByRole('progressbar', { name: QUEUE_ADVANCE_QUEUE_LABEL })).toBeInTheDocument()
  })

  it('starts full then commits a CSS drain matching the hold duration', async () => {
    render(
      <QueueAdvanceHoldBanner
        message="Activity saved"
        durationMs={QUEUE_ADVANCE_HOLD_MS}
        onPause={() => {}}
      />,
    )

    const bar = screen.getByTestId('queue-advance-hold-bar')
    expect(bar).toHaveAttribute('aria-valuenow', '100')
    expect(queueAdvanceDrainTransition(QUEUE_ADVANCE_HOLD_MS)).toBe(
      `transform ${QUEUE_ADVANCE_HOLD_MS}ms linear`,
    )
    await waitFor(() => {
      expect(bar).toHaveAttribute('aria-valuenow', '0')
    })
  })

  it('keeps the bar full when the user prefers reduced motion', () => {
    const originalMatchMedia = window.matchMedia
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))

    try {
      render(
        <QueueAdvanceHoldBanner
          message="Activity saved"
          onPause={() => {}}
        />,
      )

      const bar = screen.getByTestId('queue-advance-hold-bar')
      expect(bar).toHaveAttribute('aria-valuenow', '100')
      expect(bar).toHaveAttribute('data-drain-ms', '0')
    } finally {
      window.matchMedia = originalMatchMedia
    }
  })

  it('overlays cc-sticky-chrome with zero in-flow height instead of pushing content down', () => {
    render(
      <QueueAdvanceHoldBanner
        message="Lead deprioritized"
        onPause={() => {}}
      />,
    )

    const hold = screen.getByTestId('queue-advance-hold')
    const style = getComputedStyle(hold)
    // Absolute + top/left/right 0 removes the banner from normal flow so it
    // cannot push Property Overview (rendered after it) further down.
    expect(style.position).toBe('absolute')
    expect(style.top).toBe('0px')
    expect(style.left).toBe('0px')
    expect(style.right).toBe('0px')
    // Above cc-sticky-chrome's own z-index (100) so it wins the stack.
    expect(Number(style.zIndex)).toBe(QUEUE_ADVANCE_HOLD_Z_INDEX)
    expect(Number(style.zIndex)).toBeGreaterThan(100)
  })
})
