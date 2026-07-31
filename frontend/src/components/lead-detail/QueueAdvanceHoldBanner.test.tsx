import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { QueueAdvanceHoldBanner } from '@/components/lead-detail/QueueAdvanceHoldBanner'

describe('QueueAdvanceHoldBanner', () => {
  it('settles with progress landmark, message, and Pause control', async () => {
    const onPause = vi.fn()
    render(
      <QueueAdvanceHoldBanner
        message="Lead deprioritized"
        progress={72}
        onPause={onPause}
      />,
    )

    const hold = screen.getByTestId('queue-advance-hold')
    expect(hold).toBeInTheDocument()
    expect(hold).toHaveTextContent('Lead deprioritized')
    expect(hold).toHaveTextContent('Next lead…')
    expect(screen.getByRole('progressbar', { name: 'Advancing to next lead' })).toBeInTheDocument()
    expect(screen.getByTestId('queue-advance-pause')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('queue-advance-pause'))
    expect(onPause).toHaveBeenCalledTimes(1)
  })
})
