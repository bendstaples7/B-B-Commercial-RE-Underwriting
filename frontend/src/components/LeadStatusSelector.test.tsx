import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { LeadStatusSelector } from './LeadStatusSelector'
import { ALL_LEAD_STATUSES } from './UnifiedLeadCommandCenter'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    updateStatus: vi.fn().mockResolvedValue({ lead_status: 'deal_won' }),
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
})
