/**
 * Activity Goals Dashboard — CRM home showing outreach counts vs weekly/monthly goals,
 * with WoW/MoM trends and charts. Desktop layout fits the viewport without scrolling.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
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
import { formatShortCalendarDay, formatUtcDateRange } from '@/utils/helpers'

const cardSx = {
  p: 1.25,
  height: '100%',
  border: 1,
  borderColor: 'divider',
  borderRadius: 1,
  boxShadow: 'none',
  bgcolor: 'background.paper',
} as const

function periodToType(period: ActivityPeriod): ActivityPeriodType {
  return period === 'week' ? 'weekly' : 'monthly'
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
  goalsDisabled: boolean
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
  goalsDisabled,
  onDraftChange,
  onStartEdit,
}: MetricCardProps) {
  const goalSet = goal != null
  const hasPositiveGoal = goal != null && goal > 0
  const pct = progress ?? 0
  const barPct = Math.min(Math.max(pct, 0), 100)
  const chip = formatTrendChip(trend, trendLabel)

  return (
    <Paper elevation={0} sx={cardSx}>
      <Stack spacing={0.75}>
        <Typography
          variant="caption"
          color="text.secondary"
          fontWeight={600}
          sx={{ textTransform: 'uppercase', letterSpacing: 0.04, lineHeight: 1.2 }}
        >
          {METRIC_LABELS[metric]}
        </Typography>
        <Typography variant="h5" fontWeight={700} lineHeight={1.1}>
          {count}
        </Typography>
        <Chip
          size="small"
          icon={<chip.Icon sx={{ fontSize: '14px !important' }} />}
          label={chip.text}
          color={chip.color === 'default' ? 'default' : chip.color}
          variant="outlined"
          sx={{
            alignSelf: 'flex-start',
            height: 22,
            '& .MuiChip-label': { px: 0.75, fontSize: '0.7rem' },
          }}
        />

        {editing ? (
          <TextField
            size="small"
            type="number"
            label="Goal"
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            inputProps={{ min: 0, step: 1, 'aria-label': `${METRIC_LABELS[metric]} goal` }}
            disabled={goalsDisabled}
            fullWidth
          />
        ) : hasPositiveGoal ? (
          <>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <Typography variant="caption" color="text.secondary">
                Goal {goal}
              </Typography>
              <Typography variant="caption" fontWeight={700}>
                {pct}%
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={barPct}
              sx={{ height: 5, borderRadius: 1 }}
              aria-label={`${METRIC_LABELS[metric]} progress`}
            />
          </>
        ) : goalSet ? (
          <Typography variant="caption" color="text.secondary">
            Goal {goal}
          </Typography>
        ) : (
          <Button
            size="small"
            startIcon={<EditIcon sx={{ fontSize: 14 }} />}
            onClick={onStartEdit}
            disabled={goalsDisabled}
            sx={{ alignSelf: 'flex-start', minHeight: 0, py: 0.25, px: 0.5, fontSize: '0.75rem' }}
          >
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
    <Paper
      elevation={0}
      sx={{
        ...cardSx,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        height: '100%',
      }}
    >
      <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5, flexShrink: 0 }}>
        This period vs previous ({trendLabel})
      </Typography>
      <Box sx={{ flex: 1, minHeight: 0, width: '100%' }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="Current" fill={theme.palette.primary.main} radius={[3, 3, 0, 0]} />
            <Bar dataKey="Previous" fill={theme.palette.grey[400]} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Box>
    </Paper>
  )
}

function DailyTrendChart({ data }: { data: ActivityDashboardResponse }) {
  const theme = useTheme()
  const chartPeriod = data.period
  const chartData = useMemo(() => {
    if (chartPeriod === 'week') {
      return data.series.daily.map((day, index) => ({
        label: formatShortCalendarDay(day.date),
        Current: day.total,
        Previous: data.series.previous_daily[index]?.total ?? null,
      }))
    }
    const prevByDom = new Map(
      data.series.previous_daily.map((d) => [Number(d.date.slice(8, 10)), d.total]),
    )
    return data.series.daily.map((day) => {
      const dom = Number(day.date.slice(8, 10))
      return {
        label: formatShortCalendarDay(day.date),
        Current: day.total,
        Previous: prevByDom.has(dom) ? prevByDom.get(dom)! : null,
      }
    })
  }, [data.series.daily, data.series.previous_daily, chartPeriod])

  return (
    <Paper
      elevation={0}
      sx={{
        ...cardSx,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        height: '100%',
      }}
    >
      <Stack
        direction="row"
        alignItems="baseline"
        justifyContent="space-between"
        spacing={1}
        sx={{ mb: 0.5, flexShrink: 0 }}
      >
        <Typography variant="subtitle2" fontWeight={700}>
          Daily activity
        </Typography>
        <Typography variant="caption" color="text.secondary" noWrap>
          Solid = current · Dashed = previous
        </Typography>
      </Stack>
      <Box sx={{ flex: 1, minHeight: 0, width: '100%' }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="Current"
              stroke={theme.palette.primary.main}
              strokeWidth={2}
              dot={{ r: 2 }}
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
      </Box>
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

  const { data, isLoading, isError, error, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['dashboard', 'activity', period],
    queryFn: () => dashboardService.getActivity(period),
    placeholderData: keepPreviousData,
  })

  const goalsDisabled = isFetching || isPlaceholderData

  const saveMutation = useMutation({
    mutationFn: (targets: Partial<Record<ActivityMetric, number | null>>) =>
      dashboardService.upsertGoals(periodToType(period), targets),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', 'activity'] })
      setEditing(false)
      setGoalError(null)
    },
  })

  const startEditing = () => {
    if (!data || goalsDisabled) return
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
    if (!data || goalsDisabled) return
    const targets: Partial<Record<ActivityMetric, number | null>> = {}
    let hasChange = false
    for (const key of METRIC_KEYS) {
      const raw = drafts[key].trim()
      const previous = data.goals[key]
      if (raw === '') {
        if (previous != null) {
          targets[key] = null
          hasChange = true
        }
        continue
      }
      const value = Number(raw)
      if (!Number.isFinite(value) || value < 0 || !Number.isInteger(value)) {
        setGoalError('Goals must be non-negative whole numbers.')
        return
      }
      if (previous !== value) {
        targets[key] = value
        hasChange = true
      }
    }
    if (!hasChange) {
      setGoalError('Enter or clear at least one goal to save.')
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
    <Box
      data-testid="activity-dashboard"
      sx={{
        // Cancel App main padding so the page can fill the viewport on desktop.
        mx: { sm: -3 },
        mt: { sm: -3 },
        mb: { sm: -3 },
        height: { md: 'calc(100vh - 64px)' },
        maxHeight: { md: 'calc(100vh - 64px)' },
        display: 'flex',
        flexDirection: 'column',
        overflow: { xs: 'auto', md: 'hidden' },
        p: { xs: 1.5, md: 2 },
        gap: { xs: 1.5, md: 1.25 },
        boxSizing: 'border-box',
      }}
    >
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        alignItems={{ sm: 'center' }}
        justifyContent="space-between"
        sx={{ flexShrink: 0 }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h6" fontWeight={700} lineHeight={1.25}>
            Activity Goals
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap component="div">
            Completed outreach
            {data ? ` · ${formatUtcDateRange(data.range.start, data.range.end)}` : ''}
            {data ? ` · vs ${formatUtcDateRange(data.previous_range.start, data.previous_range.end)}` : ''}
            {isFetching && !isLoading ? ' · updating…' : ''}
          </Typography>
        </Box>

        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={period}
            onChange={handlePeriodChange}
            aria-label="Period"
          >
            <ToggleButton value="week" sx={{ px: 1.25, py: 0.5 }}>
              Week
            </ToggleButton>
            <ToggleButton value="month" sx={{ px: 1.25, py: 0.5 }}>
              Month
            </ToggleButton>
          </ToggleButtonGroup>

          {editing ? (
            <>
              <Button
                variant="contained"
                size="small"
                startIcon={<SaveIcon />}
                onClick={saveGoals}
                disabled={goalsDisabled || saveMutation.isPending}
              >
                Save
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
              disabled={!data || goalsDisabled}
            >
              Edit goals
            </Button>
          )}
        </Stack>
      </Stack>

      {isLoading && !data && (
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flex: 1 }}>
          <CircularProgress aria-label="Loading activity dashboard" />
        </Box>
      )}

      {isError && (
        <Alert severity="error" sx={{ flexShrink: 0 }}>
          {(error as Error)?.message ?? 'Failed to load activity dashboard.'}
        </Alert>
      )}

      {goalError && (
        <Alert severity="warning" sx={{ flexShrink: 0 }}>
          {goalError}
        </Alert>
      )}

      {saveMutation.isError && (
        <Alert severity="error" sx={{ flexShrink: 0 }}>
          {(saveMutation.error as Error)?.message ?? 'Failed to save goals.'}
        </Alert>
      )}

      {data && (
        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: { xs: 1.5, md: 1.25 },
          }}
        >
          <Box
            sx={{
              flexShrink: 0,
              display: 'grid',
              gap: 1,
              gridTemplateColumns: {
                xs: '1fr',
                sm: 'repeat(2, minmax(0, 1fr))',
                md: 'repeat(5, minmax(0, 1fr))',
              },
            }}
          >
            {METRIC_KEYS.map((metric) => (
              <MetricCard
                key={metric}
                metric={metric}
                count={data.counts[metric]}
                goal={data.goals[metric]}
                progress={data.progress[metric]}
                trend={data.trends[metric]}
                trendLabel={data.trend_label}
                editing={editing}
                draft={drafts[metric]}
                goalsDisabled={goalsDisabled}
                onDraftChange={(value) =>
                  setDrafts((prev) => ({ ...prev, [metric]: value }))
                }
                onStartEdit={startEditing}
              />
            ))}
          </Box>

          <Box
            sx={{
              flex: 1,
              minHeight: { xs: 420, md: 0 },
              display: 'grid',
              gap: 1.25,
              gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
              gridTemplateRows: { xs: 'minmax(200px, 1fr) minmax(200px, 1fr)', md: 'minmax(0, 1fr)' },
            }}
          >
            <ComparisonChart data={data} trendLabel={data.trend_label} />
            <DailyTrendChart data={data} />
          </Box>
        </Box>
      )}
    </Box>
  )
}
