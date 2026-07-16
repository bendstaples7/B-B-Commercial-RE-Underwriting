/**
 * CRM activity dashboard API — counts, goals, trends, and chart series.
 */
import api from '@/services/api'

export type ActivityMetric = 'calls' | 'mailers' | 'emails' | 'notes' | 'tasks'
export type ActivityPeriod = 'week' | 'month'
export type ActivityPeriodType = 'weekly' | 'monthly'

export type ActivityCounts = Record<ActivityMetric, number>
export type ActivityGoals = Record<ActivityMetric, number | null>
export type ActivityProgress = Record<ActivityMetric, number | null>

export interface ActivityTrend {
  delta: number
  pct_change: number | null
  previous: number
}

export interface ActivityDailyPoint extends ActivityCounts {
  date: string
  total: number
}

export interface ActivityComparisonPoint {
  metric: ActivityMetric
  current: number
  previous: number
}

export interface ActivityDashboardResponse {
  period: ActivityPeriod
  period_type: ActivityPeriodType
  trend_label: 'WoW' | 'MoM'
  range: { start: string; end: string }
  previous_range: { start: string; end: string }
  comparable_range?: { start: string; end: string }
  counts: ActivityCounts
  previous_counts: ActivityCounts
  goals: ActivityGoals
  progress: ActivityProgress
  trends: Record<ActivityMetric, ActivityTrend>
  series: {
    comparison: ActivityComparisonPoint[]
    daily: ActivityDailyPoint[]
    previous_daily: ActivityDailyPoint[]
  }
}

export interface UpsertGoalsResponse {
  period_type: ActivityPeriodType
  goals: ActivityGoals
}

export const METRIC_LABELS: Record<ActivityMetric, string> = {
  calls: 'Calls',
  mailers: 'Mailers',
  emails: 'Emails',
  notes: 'Notes',
  tasks: 'Tasks completed',
}

export const METRIC_KEYS: ActivityMetric[] = [
  'calls',
  'mailers',
  'emails',
  'notes',
  'tasks',
]

export const dashboardService = {
  getActivity(period: ActivityPeriod = 'week'): Promise<ActivityDashboardResponse> {
    return api
      .get<ActivityDashboardResponse>('/dashboard/activity', { params: { period } })
      .then((r) => r.data)
  },

  upsertGoals(
    periodType: ActivityPeriodType,
    targets: Partial<Record<ActivityMetric, number | null>>,
  ): Promise<UpsertGoalsResponse> {
    return api
      .put<UpsertGoalsResponse>('/dashboard/goals', {
        period_type: periodType,
        targets,
      })
      .then((r) => r.data)
  },
}
