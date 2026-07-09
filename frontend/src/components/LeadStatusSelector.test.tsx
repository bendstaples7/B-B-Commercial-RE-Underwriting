import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { LeadStatusSelector } from './LeadStatusSelector'
import { ALL_LEAD_STATUSES } from '@/constants/leadStatuses'
import { commandCenterService } from '@/services/api'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    updateStatus: vi.fn().mockResolvedValue({ lead_status: 'skip_trace' }),
  },
}))

describe('LeadStatusSelector', () => {
  it('shows current status label on the chip', () => {
    render(
      <LeadStatusSelector
        leadId={1}
        status="negotiating_remote"
        allStatuses={ALL_LEAD_STATUSES}
        onStatusChanged={vi.fn()}
      />,
    )
    expect(screen.getByTestId('lead-status-selector')).toHaveTextContent('Negotiating Remote')
  })

  it('opens menu with other statuses when chip is clicked', async () => {
    const user = userEvent.setup()
    render(
      <LeadStatusSelector
        leadId={1}
        status="negotiating_remote"
        allStatuses={ALL_LEAD_STATUSES}
        onStatusChanged={vi.fn()}
      />,
    )
    await user.click(screen.getByTestId('lead-status-selector'))
    expect(screen.getByTestId('lead-status-menu')).toBeInTheDocument()
    expect(screen.getByTestId('lead-status-option-deal_won')).toHaveTextContent('Deal Won')
    expect(screen.queryByTestId('lead-status-option-negotiating_remote')).not.toBeInTheDocument()
  })

  it('shows optimistic status from PATCH response after confirm', async () => {
    const user = userEvent.setup()
    const onStatusChanged = vi.fn().mockResolvedValue(undefined)

    render(
      <LeadStatusSelector
        leadId={1}
        status="mailing_no_contact_made"
        allStatuses={ALL_LEAD_STATUSES}
        onStatusChanged={onStatusChanged}
      />,
    )

    await user.click(screen.getByTestId('lead-status-selector'))
    await user.click(screen.getByTestId('lead-status-option-skip_trace'))
    await user.click(screen.getByTestId('status-submit-btn'))

    expect(commandCenterService.updateStatus).toHaveBeenCalledWith(
      1,
      'skip_trace',
      undefined,
    )
    await vi.waitFor(() => {
      expect(screen.getByTestId('lead-status-selector')).toHaveTextContent('Skip Trace')
    })
    expect(onStatusChanged).toHaveBeenCalled()
  })
})
