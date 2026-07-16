/**
 * Activity Goals Dashboard — CRM home showing outreach counts vs weekly/monthly goals,
 * with WoW/MoM trends and charts.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Grid,
  LinearProgress,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  useTheme,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import SaveIcon from '@mui/icons-material/Save'
import CloseIcon from '@mui/icons-material/Close'
import TrendingUpIcon from '@mui/icons-material/TrendingUp'
import TrendingDownIcon from '@mui/icons-material/TrendingDown'
import TrendingFlatIcon from '@mui/icons-material/TrendingFlat'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  LineChart,
  Line,
} from 'recharts'
import {
  dashboardService,
  METRIC_KEYS,
  METRIC_LABELS,
  type ActivityDashboardResponse,
  type ActivityMetric,
  type ActivityPeriod,
  type ActivityPeriodType,
  type ActivityTrend,
} from '@/services/dashboardApi'

function periodToType(period: ActivityPeriod): ActivityPeriodType {
  return period === 'week' ? 'weekly' : 'monthly'
}

/** Format a UTC ISO timestamp using its calendar date (avoid local TZ day shift). */
function formatRange(startIso: string, endIso: string): string {
  const start = new Date(`${startIso.slice(0, 10)}T12:00:00`)
  const endExclusive = endIso.slice(0, 10)
  const endDate = new Date(`${endExclusive}T12:00:00`)
  endDate.setDate(endDate.getDate() - 1)
  const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
  return `${start.toLocaleDateString(undefined, opts)} – ${endDate.toLocaleDateString(undefined, opts)}`
}

function formatShortDay(isoDate: string): string {
  const d = new Date(`${isoDate}T12:00:00`)
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'numeric', day: 'numeric' })
}

function formatTrendChip(trend: ActivityTrend, label: string): {
  text: string
  color: 'success' | 'error' | 'default'
  Icon: typeof TrendingUpIcon
} {
  if (trend.delta === 0) {
    return { text: `${label} flat`, color: 'default', Icon: TrendingFlatIcon }
  }
  const sign = trend.delta > 0 ? '+' : ''
  const pct =
    trend.pct_change == null
      ? ''
      : ` (${sign}${trend.pct_change}%)`
  return {
    text: `${label} ${sign}${trend.delta}${pct}`,
    color: trend.delta > 0 ? 'success' : 'error',
    Icon: trend.delta > 0 ? TrendingUpIcon : TrendingDownIcon,
  }
}

interface MetricCardProps {
  metric: ActivityMetric
  count: number
  goal: number | null
  progress: number | null
  trend: ActivityTrend
  trendLabel: string
  editing: boolean
  draft: string
  onDraftChange: (value: string) => void
  onStartEdit: () => void
}

function MetricCard({
  metric,
  count,
  goal,
  progress,
  trend,
  trendLabel,
  editing,
  draft,
  onDraftChange,
  onStartEdit,
}: MetricCardProps) {
  const goalSet = goal != null
  const hasPositiveGoal = goal != null && goal > 0
  const pct = progress ?? 0
  const barPct = Math.min(Math.max(pct, 0), 100)
  const chip = formatTrendChip(trend, trendLabel)

  return (
    <Paper elevation={1} sx={{ p: 2.5, height: '100%' }}>
      <Stack spacing={1.5}>
        <Typography variant="subtitle2" color="text.secondary">
          {METRIC_LABELS[metric]}
        </Typography>
        <Typography variant="h3" fontWeight={700} lineHeight={1.1}>
          {count}
        </Typography>
        <Chip
          size="small"
          icon={<chip.Icon />}
          label={chip.text}
          color={chip.color === 'default' ? 'default' : chip.color}
          variant={chip.color === 'default' ? 'outlined' : 'filled'}
          sx={{ alignSelf: 'flex-start' }}
        />

        {editing ? (
          <TextField
            size="small"
            type="number"
            label={`${METRIC_LABELS[metric]} goal`}
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            inputProps={{ min: 0, step: 1, 'aria-label': `${METRIC_LABELS[metric]} goal` }}
            fullWidth
          />
        ) : hasPositiveGoal ? (
          <>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <Typography variant="body2" color="text.secondary">
                Goal: {goal}
              </Typography>
              <Typography variant="body2" fontWeight={600}>
                {pct}%
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={barPct}
              sx={{ height: 8, borderRadius: 1 }}
              aria-label={`${METRIC_LABELS[metric]} progress`}
            />
          </>
        ) : goalSet ? (
          <Typography variant="body2" color="text.secondary">
            Goal: {goal}
          </Typography>
        ) : (
          <Button size="small" startIcon={<EditIcon />} onClick={onStartEdit} sx={{ alignSelf: 'flex-start' }}>
            Set goal
          </Button>
        )}
      </Stack>
    </Paper>
  )
}

function ComparisonChart({ data, trendLabel }: { data: ActivityDashboardResponse; trendLabel: string }) {
  const theme = useTheme()
  const chartData = useMemo(
    () =>
      data.series.comparison.map((row) => ({
        name: METRIC_LABELS[row.metric],
        Current: row.current,
        Previous: row.previous,
      })),
    [data.series.comparison],
  )

  return (
    <Paper elevation={1} sx={{ p: 2.5, height: 340 }}>
      <Typography variant="h6" gutterBottom>
        This period vs previous ({trendLabel})
      </Typography>
      <ResponsiveContainer width="100%" height="85%">
        <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
          <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
          <Tooltip />
          <Legend />
          <Bar dataKey="Current" fill={theme.palette.primary.main} radius={[4, 4, 0, 0]} />
          <Bar dataKey="Previous" fill={theme.palette.grey[400]} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </Paper>
  )
}

function DailyTrendChart({
  data,
  period,
}: {
  data: ActivityDashboardResponse
  period: ActivityPeriod
}) {
  const theme = useTheme()
  const chartData = useMemo(() => {
    if (period === 'week') {
      // Align by weekday index (both series are length 7 Mon–Sun).
      return data.series.daily.map((day, index) => ({
        label: formatShortDay(day.date),
        Current: day.total,
        Previous: data.series.previous_daily[index]?.total ?? null,
      }))
    }
    // Align by day-of-month; missing previous days stay null (not zero).
    const prevByDom = new Map(
      data.series.previous_daily.map((d) => [Number(d.date.slice(8, 10)), d.total]),
    )
    return data.series.daily.map((day) => {
      const dom = Number(day.date.slice(8, 10))
      return {
        label: formatShortDay(day.date),
        Current: day.total,
        Previous: prevByDom.has(dom) ? prevByDom.get(dom)! : null,
      }
    })
  }, [data.series.daily, data.series.previous_daily, period])

  return (
    <Paper elevation={1} sx={{ p: 2.5, height: 340 }}>
      <Typography variant="h6" gutterBottom>
        Daily activity (all metrics)
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Solid = current period · Dashed = previous period
      </Typography>
      <ResponsiveContainer width="100%" height="78%">
        <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
          <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
          <Tooltip />
          <Legend />
          <Line
            type="monotone"
            dataKey="Current"
            stroke={theme.palette.primary.main}
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="Previous"
            stroke={theme.palette.grey[500]}
            strokeWidth={2}
            strokeDasharray="5 5"
            dot={false}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </Paper>
  )
}

export function ActivityDashboardPage() {
  const queryClient = useQueryClient()
  const [period, setPeriod] = useState<ActivityPeriod>('week')
  const [editing, setEditing] = useState(false)
  const [goalError, setGoalError] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<ActivityMetric, string>>({
    calls: '',
    mailers: '',
    emails: '',
    notes: '',
    tasks: '',
  })

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['dashboard', 'activity', period],
    queryFn: () => dashboardService.getActivity(period),
    placeholderData: keepPreviousData,
  })

  const saveMutation = useMutation({
    mutationFn: (targets: Partial<Record<ActivityMetric, number>>) =>
      dashboardService.upsertGoals(periodToType(period), targets),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'activity'] })
      setEditing(false)
      setGoalError(null)
    },
  })

  const startEditing = () => {
    if (!data) return
    const next = { ...drafts }
    for (const key of METRIC_KEYS) {
      next[key] = data.goals[key] != null ? String(data.goals[key]) : ''
    }
    setDrafts(next)
    setGoalError(null)
    setEditing(true)
  }

  const cancelEditing = () => {
    setEditing(false)
    setGoalError(null)
    saveMutation.reset()
  }

  const saveGoals = () => {
    const targets: Partial<Record<ActivityMetric, number>> = {}
    for (const key of METRIC_KEYS) {
      const raw = drafts[key].trim()
      if (raw === '') continue
      const value = Number(raw)
      if (!Number.isFinite(value) || value < 0 || !Number.isInteger(value)) {
        setGoalError('Goals must be non-negative whole numbers.')
        return
      }
      targets[key] = value
    }
    if (Object.keys(targets).length === 0) {
      setGoalError('Enter at least one goal to save.')
      return
    }
    setGoalError(null)
    saveMutation.mutate(targets)
  }

  const handlePeriodChange = (_: unknown, value: ActivityPeriod | null) => {
    if (!value) return
    setPeriod(value)
    setEditing(false)
    setGoalError(null)
  }

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1200, mx: 'auto' }}>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems={{ sm: 'center' }}
        justifyContent="space-between"
        sx={{ mb: 3 }}
      >
        <Box>
          <Typography variant="h4" fontWeight={700} gutterBottom>
            Activity Dashboard
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Your completed outreach
            {data ? ` · ${formatRange(data.range.start, data.range.end)}` : ''}
            {data ? ` · vs ${formatRange(data.previous_range.start, data.previous_range.end)}` : ''}
            {isFetching && !isLoading ? ' · updating…' : ''}
          </Typography>
        </Box>

        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <ToggleButtonGroup
            exclusive
            size="small"
            value={period}
            onChange={handlePeriodChange}
            aria-label="Period"
          >
            <ToggleButton value="week">This week</ToggleButton>
            <ToggleButton value="month">This month</ToggleButton>
          </ToggleButtonGroup>

          {editing ? (
            <>
              <Button
                variant="contained"
                size="small"
                startIcon={<SaveIcon />}
                onClick={saveGoals}
                disabled={saveMutation.isPending}
              >
                Save goals
              </Button>
              <Button
                size="small"
                startIcon={<CloseIcon />}
                onClick={cancelEditing}
                disabled={saveMutation.isPending}
              >
                Cancel
              </Button>
            </>
          ) : (
            <Button
              size="small"
              startIcon={<EditIcon />}
              onClick={startEditing}
              disabled={!data}
            >
              Edit goals
            </Button>
          )}
        </Stack>
      </Stack>

      {isLoading && !data && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress aria-label="Loading activity dashboard" />
        </Box>
      )}

      {isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(error as Error)?.message ?? 'Failed to load activity dashboard.'}
        </Alert>
      )}

      {goalError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {goalError}
        </Alert>
      )}

      {saveMutation.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(saveMutation.error as Error)?.message ?? 'Failed to save goals.'}
        </Alert>
      )}

      {data && (
        <Stack spacing={3}>
          <Grid container spacing={2}>
            {METRIC_KEYS.map((metric) => (
              <Grid item xs={12} sm={6} md={4} key={metric}>
                <MetricCard
                  metric={metric}
                  count={data.counts[metric]}
                  goal={data.goals[metric]}
                  progress={data.progress[metric]}
                  trend={data.trends[metric]}
                  trendLabel={data.trend_label}
                  editing={editing}
                  draft={drafts[metric]}
                  onDraftChange={(value) =>
                    setDrafts((prev) => ({ ...prev, [metric]: value }))
                  }
                  onStartEdit={startEditing}
                />
              </Grid>
            ))}
          </Grid>

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <ComparisonChart data={data} trendLabel={data.trend_label} />
            </Grid>
            <Grid item xs={12} md={6}>
              <DailyTrendChart data={data} period={period} />
            </Grid>
          </Grid>
        </Stack>
      )}
    </Box>
  )
}
