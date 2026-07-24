import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  HeaderLeadScorePanel,
  resolveTopScoreDrivers,
  scorePriorityLabel,
} from './HeaderLeadScorePanel'
import type { PropertyScoreRecord } from '@/types'

function makeScore(overrides: Partial<PropertyScoreRecord> = {}): PropertyScoreRecord {
  return {
    id: 1,
    lead_id: 1,
    total_score: 87,
    score_tier: 'A',
    score_version: 'residential_v1_internal_data',
    score_details: {
      mailing_equity: 18,
      absentee_owner: 12,
      tax_delinquency: 10,
      years_owned: 8,
    },
    top_signals: [
      { dimension: 'mailing_equity', points: 18 },
      { dimension: 'absentee_owner', points: 12 },
      { dimension: 'tax_delinquency', points: 10 },
      { dimension: 'years_owned', points: 8 },
    ],
    created_at: '2024-07-08T12:00:00Z',
    ...overrides,
  } as PropertyScoreRecord
}

describe('resolveTopScoreDrivers', () => {
  it('prefers positive top_signals over score_details (top 4)', () => {
    const drivers = resolveTopScoreDrivers(makeScore())
    expect(drivers.map((d) => d.dimension)).toEqual([
      'mailing_equity',
      'absentee_owner',
      'tax_delinquency',
      'years_owned',
    ])
  })

  it('falls back to score_details when top_signals empty', () => {
    const drivers = resolveTopScoreDrivers(makeScore({ top_signals: [] }))
    expect(drivers[0]?.dimension).toBe('mailing_equity')
  })
})

describe('HeaderLeadScorePanel', () => {
  it('renders gauge score, priority, drivers, and model updated date', () => {
    render(
      <HeaderLeadScorePanel score={87} tier="A" scoreRecord={makeScore()} />,
    )
    expect(screen.getByTestId('header-lead-score')).toHaveTextContent('87')
    expect(screen.getByTestId('header-lead-score')).toHaveTextContent(
      scorePriorityLabel('A'),
    )
    expect(screen.getByTestId('header-score-updated')).toBeInTheDocument()
    expect(screen.getByText(/Lead signals/i)).toBeInTheDocument()
  })

  it('calls onOpenBreakdown when clicked and a score record exists', async () => {
    const user = userEvent.setup()
    const onOpenBreakdown = vi.fn()
    render(
      <HeaderLeadScorePanel
        score={87}
        tier="A"
        scoreRecord={makeScore()}
        onOpenBreakdown={onOpenBreakdown}
      />,
    )
    await user.click(screen.getByTestId('header-lead-score'))
    expect(onOpenBreakdown).toHaveBeenCalledTimes(1)
  })

  it('shows em dash and Unscored when score is null (not 0 / Low Priority)', () => {
    render(<HeaderLeadScorePanel score={null} tier={null} />)
    expect(screen.getByTestId('header-lead-score-value')).toHaveTextContent('—')
    expect(screen.getByTestId('header-lead-score')).toHaveTextContent('Unscored')
    expect(screen.getByTestId('header-lead-score')).not.toHaveTextContent('Low Priority')
  })
})
