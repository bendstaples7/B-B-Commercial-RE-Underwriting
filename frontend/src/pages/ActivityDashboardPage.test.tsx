import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ActivityDashboardPage } from './ActivityDashboardPage'
import { dashboardService, type ActivityDashboardResponse } from '@/services/dashboardApi'

vi.mock('@/services/dashboardApi', async () => {
  const actual = await vi.importActual<typeof import('@/services/dashboardApi')>(
    '@/services/dashboardApi',
  )
  return {
    ...actual,
    dashboardService: {
      getActivity: vi.fn(),
      upsertGoals: vi.fn(),
    },
  }
})

const baseResponse: ActivityDashboardResponse = {
  period: 'week',
  period_type: 'weekly',
  trend_label: 'WoW',
  range: { start: '2026-07-20T00:00:00Z', end: '2026-07-26T00:00:00Z' },
  previous_range: { start: '2026-07-13T00:00:00Z', end: '2026-07-19T00:00:00Z' },
  counts: { calls: 3, mailers: 1, emails: 0, notes: 2, tasks: 1 },
  previous_counts: { calls: 1, mailers: 1, emails: 0, notes: 1, tasks: 0 },
  goals: { calls: 10, mailers: null, emails: null, notes: null, tasks: null },
  progress: { calls: 30, mailers: null, emails: null, notes: null, tasks: null },
  trends: {
    calls: { delta: 2, pct_change: 200, previous: 1 },
    mailers: { delta: 0, pct_change: 0, previous: 1 },
    emails: { delta: 0, pct_change: null, previous: 0 },
    notes: { delta: 1, pct_change: 100, previous: 1 },
    tasks: { delta: 1, pct_change: null, previous: 0 },
  },
  series: {
    comparison: [
      { metric: 'calls', current: 3, previous: 1 },
      { metric: 'mailers', current: 1, previous: 1 },
      { metric: 'emails', current: 0, previous: 0 },
      { metric: 'notes', current: 2, previous: 1 },
      { metric: 'tasks', current: 1, previous: 0 },
    ],
    daily: [],
    previous_daily: [],
  },
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ActivityDashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ActivityDashboardPage first paint', () => {
  beforeEach(() => {
    vi.mocked(dashboardService.getActivity).mockResolvedValue(baseResponse)
  })

  it('settles metric cards with one Activity Goals title and percent-only trends', async () => {
    renderPage()

    expect(screen.getByTestId('activity-dashboard')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('Calls')).toBeInTheDocument()
    })

    expect(screen.getAllByText('Activity Goals')).toHaveLength(1)
    expect(screen.getByTestId('metric-stat-row-calls')).toBeInTheDocument()
    expect(screen.getAllByText('WoW').length).toBeGreaterThan(0)
    expect(screen.getByText('+200%')).toBeInTheDocument()
    expect(screen.queryByText(/WoW \+2/)).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Set goal/i }).length).toBeGreaterThan(0)
  })
})
