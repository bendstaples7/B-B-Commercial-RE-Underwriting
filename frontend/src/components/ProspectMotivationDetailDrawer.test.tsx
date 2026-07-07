/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProspectMotivationDetailDrawer } from '@/components/ProspectMotivationDetailDrawer'
import type { ProspectCandidate } from '@/types'

const sampleCandidate: ProspectCandidate = {
  id: 1,
  pin: '14-28-400-008-0003',
  property_street: '100 MAIN ST',
  property_city: 'Chicago',
  property_state: 'IL',
  location_hint: null,
  primary_signal_type: 'FORECLOSURE_AUCTION',
  motivation_score: 14.5,
  motivation_pct: 58,
  signals: [
    {
      signal_type: 'FORECLOSURE_AUCTION',
      severity: 'high',
      points: 12,
      label: 'Sheriff foreclosure auction',
      evidence: { case_number: '2024CH08121', auction_date: '2026-08-01' },
    },
    {
      signal_type: 'BUILDING_VIOLATION',
      severity: 'medium',
      points: 2.5,
      base_points: 5,
      recency_multiplier: 0.5,
      label: 'Building violation',
      evidence: {
        violation_code: 'CN',
        violation_description: 'Failed inspection',
        violation_date: '2024-01-15T00:00:00.000',
      },
    },
  ],
  source_feed: 'stacked',
  status: 'pending',
  duplicate_lead_id: null,
  imported_lead_id: null,
  created_at: '2026-07-06T23:00:00Z',
  reviewed_at: null,
}

describe('ProspectMotivationDetailDrawer', () => {
  it('shows stacked signals and total when open', () => {
    render(
      <ProspectMotivationDetailDrawer
        candidate={sampleCandidate}
        open
        onClose={vi.fn()}
      />,
    )

    expect(screen.getByText('Motivation breakdown')).toBeInTheDocument()
    expect(screen.getByText('58%')).toBeInTheDocument()
    expect(screen.getByText('Sheriff foreclosure auction')).toBeInTheDocument()
    expect(screen.getByText('Building violation')).toBeInTheDocument()
    expect(screen.getByText(/Case 2024CH08121/)).toBeInTheDocument()
    expect(screen.getByText('CN: Failed inspection')).toBeInTheDocument()
    expect(screen.getByText(/50% recency weight/)).toBeInTheDocument()
    expect(screen.getByText('14.5')).toBeInTheDocument()
  })

  it('calls onClose when close button is clicked', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <ProspectMotivationDetailDrawer
        candidate={sampleCandidate}
        open
        onClose={onClose}
      />,
    )

    await user.click(screen.getByRole('button', { name: /Close motivation details/i }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
