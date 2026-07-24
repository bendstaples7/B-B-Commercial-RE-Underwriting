/**
 * Right-aligned Property Overview lead-score panel — compact gauge + driver chips.
 */
import type React from 'react'
import {
  Box,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from '@mui/material'
import AttachMoneyIcon from '@mui/icons-material/AttachMoney'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth'
import ApartmentIcon from '@mui/icons-material/Apartment'
import HomeWorkIcon from '@mui/icons-material/HomeWork'
import LocalFireDepartmentIcon from '@mui/icons-material/LocalFireDepartment'
import InsightsIcon from '@mui/icons-material/Insights'
import type { PropertyScoreRecord, ScoreSignal } from '@/types'
import type { ScoreTier } from '@/components/LeadScoreBadge'
import { getDimensionMeta } from '@/utils/scoreDimensionMeta'
import { formatDateOnly } from '@/utils/helpers'

const ATTRIBUTION_ONLY = new Set(['notes_keywords'])
const GAUGE_SIZE = 56

export function scorePriorityLabel(tier: ScoreTier): string {
  if (tier === 'A') return 'High Priority'
  if (tier === 'B') return 'Good Fit'
  if (tier === 'C') return 'Moderate'
  return 'Low Priority'
}

export function scoreGaugeColor(tier: ScoreTier): string {
  if (tier === 'A') return '#F59E0B'
  if (tier === 'B') return '#3B82F6'
  if (tier === 'C') return '#94A3B8'
  return '#CBD5E1'
}

type ChipTone = { bg: string; fg: string }

function chipToneForDimension(dimension: string): ChipTone {
  if (dimension.includes('absentee') || dimension.includes('owner')) {
    return { bg: 'rgba(59, 130, 246, 0.12)', fg: '#1D4ED8' }
  }
  if (dimension.includes('tax') || dimension.includes('distress') || dimension.includes('source')) {
    return { bg: 'rgba(245, 158, 11, 0.14)', fg: '#B45309' }
  }
  if (dimension.includes('years') || dimension.includes('owned') || dimension.includes('calendar')) {
    return { bg: 'rgba(139, 92, 246, 0.12)', fg: '#6D28D9' }
  }
  if (dimension.includes('equity') || dimension.includes('money') || dimension.includes('mailing')) {
    return { bg: 'rgba(14, 165, 233, 0.12)', fg: '#0369A1' }
  }
  if (dimension.includes('motivation') || dimension.includes('notes')) {
    return { bg: 'rgba(239, 68, 68, 0.10)', fg: '#B91C1C' }
  }
  return { bg: 'rgba(100, 116, 139, 0.12)', fg: '#475569' }
}

function iconForDimension(dimension: string) {
  if (dimension.includes('absentee') || dimension.includes('owner_concentration')) {
    return <PersonOutlineIcon sx={{ fontSize: 12 }} />
  }
  if (dimension.includes('tax') || dimension.includes('distress') || dimension.includes('source')) {
    return <WarningAmberIcon sx={{ fontSize: 12 }} />
  }
  if (
    dimension.includes('years')
    || dimension.includes('owned')
    || dimension.includes('ownership_duration')
  ) {
    return <CalendarMonthIcon sx={{ fontSize: 12 }} />
  }
  if (dimension.includes('unit')) {
    return <ApartmentIcon sx={{ fontSize: 12 }} />
  }
  if (
    dimension.includes('property_type')
    || dimension.includes('building')
    || dimension.includes('heuristics')
  ) {
    return <HomeWorkIcon sx={{ fontSize: 12 }} />
  }
  if (dimension.includes('motivation') || dimension.includes('notes')) {
    return <LocalFireDepartmentIcon sx={{ fontSize: 12 }} />
  }
  if (
    dimension.includes('mailing')
    || dimension.includes('equity')
  ) {
    return <AttachMoneyIcon sx={{ fontSize: 12 }} />
  }
  if (dimension.includes('contactability') || dimension.includes('engagement')) {
    return <PersonOutlineIcon sx={{ fontSize: 12 }} />
  }
  return <InsightsIcon sx={{ fontSize: 12 }} />
}

/** Top positive drivers for the compact header chips (max 4). */
export function resolveTopScoreDrivers(
  score: PropertyScoreRecord | null | undefined,
  limit = 4,
): ScoreSignal[] {
  if (!score) return []
  const fromSignals = (score.top_signals ?? [])
    .filter((s) => s && s.points > 0 && !ATTRIBUTION_ONLY.has(s.dimension))
    .sort((a, b) => b.points - a.points)
  if (fromSignals.length > 0) return fromSignals.slice(0, limit)

  return Object.entries(score.score_details ?? {})
    .filter(([key, points]) => !ATTRIBUTION_ONLY.has(key) && points > 0)
    .sort(([, a], [, b]) => b - a)
    .slice(0, limit)
    .map(([dimension, points]) => ({ dimension, points }))
}

export interface HeaderLeadScorePanelProps {
  score: number | null | undefined
  tier: ScoreTier | null | undefined
  scoreRecord?: PropertyScoreRecord | null
  onOpenBreakdown?: () => void
}

export function HeaderLeadScorePanel({
  score,
  tier,
  scoreRecord,
  onOpenBreakdown,
}: HeaderLeadScorePanelProps) {
  const hasScore = score != null && Number.isFinite(Number(score))
  const rounded = hasScore ? Math.round(Number(score)) : null
  const clamped = rounded != null ? Math.min(100, Math.max(0, rounded)) : 0
  const effectiveTier: ScoreTier = tier ?? 'D'
  const color = hasScore ? scoreGaugeColor(effectiveTier) : 'grey.300'
  const priority = hasScore ? scorePriorityLabel(effectiveTier) : 'Unscored'
  const drivers = resolveTopScoreDrivers(scoreRecord)
  const updatedAt = scoreRecord?.created_at
    ? formatDateOnly(scoreRecord.created_at) || scoreRecord.created_at.slice(0, 10)
    : null
  const clickable = Boolean(scoreRecord && onOpenBreakdown)

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!clickable) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onOpenBreakdown?.()
    }
  }

  return (
    <Box
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? onOpenBreakdown : undefined}
      onKeyDown={clickable ? handleKeyDown : undefined}
      data-testid="header-lead-score"
      aria-label={
        clickable
          ? 'View lead score breakdown'
          : hasScore
            ? `Lead score ${rounded}`
            : 'Lead score not available'
      }
      sx={{
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 1.25,
        flex: { xs: '1 1 100%', md: '0 0 auto' },
        width: { md: 400 },
        minWidth: { md: 380 },
        maxWidth: { xs: '100%', md: 440 },
        flexShrink: 0,
        ml: { md: 'auto' },
        py: 0.5,
        px: 1.25,
        borderRadius: 1,
        border: '1px solid',
        borderColor: 'divider',
        bgcolor: 'background.paper',
        cursor: clickable ? 'pointer' : 'default',
        textAlign: 'left',
        '&:hover': clickable
          ? { borderColor: 'text.disabled', bgcolor: 'action.hover' }
          : undefined,
        '&:focus-visible': {
          outline: '2px solid',
          outlineColor: 'primary.main',
          outlineOffset: 2,
        },
      }}
    >
      <Box
        sx={{
          position: 'relative',
          width: GAUGE_SIZE,
          height: GAUGE_SIZE,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <CircularProgress
          variant="determinate"
          value={100}
          size={GAUGE_SIZE}
          thickness={3.75}
          sx={{ position: 'absolute', color: 'grey.200' }}
        />
        <CircularProgress
          variant="determinate"
          value={hasScore ? clamped : 0}
          size={GAUGE_SIZE}
          thickness={3.75}
          sx={{
            position: 'absolute',
            color,
            transform: 'rotate(-90deg) !important',
            '& .MuiCircularProgress-circle': { strokeLinecap: 'round' },
          }}
        />
        <Box sx={{ textAlign: 'center', px: 0.25, zIndex: 1 }}>
          <Typography
            component="div"
            data-testid="header-lead-score-value"
            sx={{ fontSize: '1.1rem', fontWeight: 800, lineHeight: 1, color: 'text.primary' }}
          >
            {hasScore ? rounded : '—'}
          </Typography>
          <Typography
            component="div"
            sx={{
              mt: 0.15,
              fontSize: '0.55rem',
              fontWeight: 700,
              lineHeight: 1.1,
              color: hasScore ? color : 'text.secondary',
              maxWidth: 48,
            }}
          >
            {priority}
          </Typography>
        </Box>
      </Box>

      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="baseline"
          spacing={1}
          sx={{ minWidth: 0 }}
        >
          <Typography
            variant="caption"
            fontWeight={700}
            color="text.secondary"
            sx={{
              textTransform: 'uppercase',
              letterSpacing: 0.04,
              lineHeight: 1.2,
              fontSize: '0.65rem',
            }}
          >
            Lead signals / score
          </Typography>
          <Typography
            variant="caption"
            color="text.disabled"
            data-testid="header-score-updated"
            sx={{ fontSize: '0.65rem', lineHeight: 1.2, flexShrink: 0 }}
            title={updatedAt ? `Model updated ${updatedAt}` : undefined}
          >
            Updated: {updatedAt ?? '—'}
          </Typography>
        </Stack>

        {drivers.length === 0 ? (
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
            {scoreRecord ? 'No top drivers yet.' : 'Breakdown unavailable.'}
          </Typography>
        ) : (
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gridTemplateRows: 'auto auto',
              gap: 0.5,
              width: '100%',
              alignItems: 'stretch',
            }}
          >
            {drivers.map((driver) => {
              const meta = getDimensionMeta(driver.dimension, scoreRecord?.score_version ?? '')
              const tone = chipToneForDimension(driver.dimension)
              return (
                <Chip
                  key={driver.dimension}
                  size="small"
                  icon={iconForDimension(driver.dimension)}
                  label={meta.label}
                  title={meta.label}
                  sx={{
                    width: '100%',
                    maxWidth: '100%',
                    height: 24,
                    justifyContent: 'flex-start',
                    borderRadius: 0.75,
                    bgcolor: tone.bg,
                    color: tone.fg,
                    fontWeight: 600,
                    fontSize: '0.65rem',
                    '& .MuiChip-icon': {
                      color: tone.fg,
                      ml: 0.35,
                      mr: -0.15,
                      flexShrink: 0,
                    },
                    '& .MuiChip-label': {
                      px: 0.5,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      display: 'block',
                    },
                  }}
                />
              )
            })}
          </Box>
        )}
      </Box>
    </Box>
  )
}

export default HeaderLeadScorePanel
