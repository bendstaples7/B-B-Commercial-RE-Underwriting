import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { ScoreBreakdownDialog } from './ScoreBreakdownDialog'
import type { PropertyScoreRecord } from '@/types'

const score: PropertyScoreRecord = {
  id: 1,
  property_id: 11129,
  score_version: 'residential_v1_internal_data',
  total_score: 43,
  score_tier: 'C',
  data_quality_score: 0,
  recommended_action: 'nurture',
  top_signals: [{ dimension: 'unit_count_fit', points: 15 }],
  score_details: {
    unit_count_fit: 15,
    absentee_owner: 10,
  },
  missing_data: ['pin'],
  created_at: '2024-01-01T00:00:00Z',
}

describe('ScoreBreakdownDialog', () => {
  it('shows breakdown and closes via Close button', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    render(
      <ScoreBreakdownDialog score={score} open onClose={onClose} />,
    )

    expect(screen.getByTestId('score-breakdown-dialog')).toBeInTheDocument()
    expect(screen.getByText('Ideal unit count')).toBeInTheDocument()
    expect(screen.getByText('Absentee owner')).toBeInTheDocument()

    await user.click(screen.getByTestId('score-breakdown-done'))
    expect(onClose).toHaveBeenCalled()
  })

  it('closes via header X button', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    render(
      <ScoreBreakdownDialog score={score} open onClose={onClose} />,
    )

    await user.click(screen.getByTestId('score-breakdown-close'))
    expect(onClose).toHaveBeenCalled()
  })
})
