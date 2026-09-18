import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import {
  HeaderLeadScorePanel,
  resolveHeaderCurrentQueues,
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
  it('prefers positive top_signals over score_details (top 2 full labels)', () => {
    const drivers = resolveTopScoreDrivers(makeScore())
    expect(drivers.map((d) => d.dimension)).toEqual([
      'mailing_equity',
      'absentee_owner',
    ])
  })

  it('honors explicit higher limit when requested', () => {
    const drivers = resolveTopScoreDrivers(makeScore(), 4)
    expect(drivers).toHaveLength(4)
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
    await user.click(screen.getByRole('button', { name: /Lead score 87/ }))
    expect(onOpenBreakdown).toHaveBeenCalledTimes(1)
  })

  it('renders at most two driver chips with full labels (no ellipsis sx)', () => {
    render(
      <HeaderLeadScorePanel score={87} tier="A" scoreRecord={makeScore()} />,
    )
    const drivers = screen.getByTestId('header-score-drivers')
    expect(drivers.querySelectorAll('.MuiChip-root')).toHaveLength(2)
    expect(drivers).toHaveTextContent(/Mailing|Equity|Absentee/i)
    expect(screen.queryByText(/\$ Hi/)).not.toBeInTheDocument()
  })

  it('shows em dash and Unscored when score is null (not 0 / Low Priority)', () => {
    render(<HeaderLeadScorePanel score={null} tier={null} />)
    expect(screen.getByTestId('header-lead-score-value')).toHaveTextContent('—')
    expect(screen.getByTestId('header-lead-score')).toHaveTextContent('Unscored')
    expect(screen.getByTestId('header-lead-score')).not.toHaveTextContent('Low Priority')
  })

  it('shows a score flash pill when provided', () => {
    render(
      <HeaderLeadScorePanel
        score={87}
        tier="A"
        scoreRecord={makeScore()}
        flash={{ label: '+5', tone: 'up' }}
      />,
    )
    expect(screen.getByTestId('header-lead-score-flash')).toHaveTextContent('+5')
  })

  it('omits the flash pill when none is provided', () => {
    render(<HeaderLeadScorePanel score={87} tier="A" scoreRecord={makeScore()} />)
    expect(screen.queryByTestId('header-lead-score-flash')).not.toBeInTheDocument()
  })

  it('driver chip labels wrap (no nowrap+ellipsis truncation)', () => {
    render(
      <HeaderLeadScorePanel score={87} tier="A" scoreRecord={makeScore()} />,
    )
    const drivers = screen.getByTestId('header-score-drivers')
    const chip = drivers.querySelector('.MuiChip-root') as HTMLElement
    expect(chip).toBeTruthy()
    const label = chip.querySelector('.MuiChip-label') as HTMLElement
    expect(getComputedStyle(label).whiteSpace).toMatch(/normal|pre-wrap/)
    expect(getComputedStyle(label).textOverflow).not.toBe('ellipsis')
  })
})

describe('resolveHeaderCurrentQueues', () => {
  it('keeps membership order and prepends viewing-from when missing', () => {
    const queues = resolveHeaderCurrentQueues(
      [{ key: 'follow-up-overdue', label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue' }],
      { key: 'todays-action', label: "Today's Action" },
    )
    expect(queues.map((q) => q.key)).toEqual(['todays-action', 'follow-up-overdue'])
  })

  it('does not duplicate the viewing-from queue', () => {
    const queues = resolveHeaderCurrentQueues(
      [{ key: 'todays-action', label: "Today's Action", path: '/queues/todays-action' }],
      { key: 'todays-action', label: "Today's Action" },
    )
    expect(queues).toHaveLength(1)
  })

  it('adds Needs Review when review is active but missing from membership', () => {
    const queues = resolveHeaderCurrentQueues([], null, { reviewActive: true })
    expect(queues.map((q) => q.key)).toEqual(['needs-review'])
  })
})

describe('HeaderLeadScorePanel current queues', () => {
  it('lists current queues and bolds the viewing-from queue', () => {
    render(
      <MemoryRouter>
        <HeaderLeadScorePanel
          score={87}
          tier="A"
          scoreRecord={makeScore()}
          currentQueues={[
            { key: 'todays-action', label: "Today's Action", path: '/queues/todays-action' },
            { key: 'follow-up-overdue', label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue' },
          ]}
          viewingFromQueueKey="todays-action"
        />
      </MemoryRouter>,
    )
    const line = screen.getByTestId('header-current-queues')
    expect(line).toHaveTextContent("Current queues: Today's Action, Follow-Up Overdue")
    expect(screen.getByTestId('work-queue-strip-todays-action')).toHaveAttribute(
      'data-viewing-from',
      'true',
    )
    expect(screen.getByTestId('work-queue-strip-follow-up-overdue')).not.toHaveAttribute(
      'data-viewing-from',
    )
    expect(screen.getByTestId('work-queue-strip-todays-action').querySelector('strong')).toHaveTextContent(
      "Today's Action",
    )
    expect(screen.getByTestId('work-queue-strip-follow-up-overdue').querySelector('strong')).toBeNull()
  })

  it('shows None when membership is empty', () => {
    render(
      <MemoryRouter>
        <HeaderLeadScorePanel score={87} tier="A" scoreRecord={makeScore()} currentQueues={[]} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('header-current-queues')).toHaveTextContent('Current queues: None')
    expect(screen.getByTestId('work-queue-strip-empty')).toBeInTheDocument()
  })

  it('omits the line when currentQueues is not passed', () => {
    render(<HeaderLeadScorePanel score={87} tier="A" scoreRecord={makeScore()} />)
    expect(screen.queryByTestId('header-current-queues')).not.toBeInTheDocument()
  })
})

