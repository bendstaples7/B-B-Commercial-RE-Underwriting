import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import {
  QueueAdvanceHoldBanner,
  QUEUE_ADVANCE_HOLD_MS,
  QUEUE_ADVANCE_HOLD_Z_INDEX,
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
    expect(hold).toHaveTextContent('Next lead…')
    const bar = screen.getByRole('progressbar', { name: 'Advancing to next lead' })
    expect(bar).toBeInTheDocument()
    expect(bar).toHaveAttribute('data-drain-ms', String(QUEUE_ADVANCE_HOLD_MS))
    expect(QUEUE_ADVANCE_HOLD_MS).toBe(5000)
    expect(screen.getByTestId('queue-advance-pause')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('queue-advance-pause'))
    expect(onPause).toHaveBeenCalledTimes(1)
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
