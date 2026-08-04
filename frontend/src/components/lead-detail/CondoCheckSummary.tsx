/**
 * Shared condo-check summary — gauge % + verdict + driver chips.
 * Used by header Condo check panel and Building ownership card.
 */
import type { ReactElement } from 'react'
import {
  Box,
  Chip,
  CircularProgress,
  Typography,
  type SxProps,
  type Theme,
} from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import ApartmentIcon from '@mui/icons-material/Apartment'
import type { CommandCenterPayload } from '@/types'
import { formatDateOnly } from '@/utils/helpers'
import {
  mapCondoConfidencePercent,
  resolveCondoCheckLines,
} from '@/components/lead-detail/PropertyOverviewQuickStats'

const GAUGE_SIZE = 56

const RULE_LABELS: Record<string, string> = {
  rule_7_missing_data: 'Missing PINs / data',
  rule_1_single_pin: 'Single PIN',
  rule_2_multi_pin: 'Multiple PINs',
  rule_3_condo_language: 'Condo language',
  rule_4_unit_numbers: 'Unit numbers',
  rule_5_owner_count: 'Owner count',
  rule_6_mixed_signals: 'Mixed signals',
}

export function humanizeCondoDriver(rule: string): string {
  const key = String(rule || '').trim()
  if (!key) return ''
  if (RULE_LABELS[key]) return RULE_LABELS[key]
  return key
    .replace(/^rule_\d+_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function condoGaugeColor(verdict: string, pct: number | null): string {
  if (verdict === 'Not checked' || verdict.startsWith('Checking')) return '#CBD5E1'
  if (verdict === 'Not condos') return '#22C55E'
  if (verdict === 'Condos') return '#F59E0B'
  if (pct != null && pct <= 30) return '#F59E0B'
  return '#94A3B8'
}

function iconForDriver(label: string): ReactElement {
  const lower = label.toLowerCase()
  if (lower.includes('missing') || lower.includes('incomplete')) {
    return <WarningAmberIcon sx={{ fontSize: 12 }} />
  }
  if (lower.includes('condo')) {
    return <ApartmentIcon sx={{ fontSize: 12 }} />
  }
  if (lower.includes('not') || lower.includes('clear')) {
    return <CheckCircleOutlineIcon sx={{ fontSize: 12 }} />
  }
  return <HelpOutlineIcon sx={{ fontSize: 12 }} />
}

export interface CondoCheckSummaryProps {
  commandCenterData: CommandCenterPayload
  /**
   * Test id stem. Root is `${stem}-check`; children use `${stem}-confidence-value`, etc.
   * Default `header-condo` preserves existing header panel contracts.
   */
  testIdStem?: string
  /** Hide the Updated stamp (e.g. when parent already shows last check). */
  hideUpdated?: boolean
  sx?: SxProps<Theme>
}

export function CondoCheckSummary({
  commandCenterData,
  testIdStem = 'header-condo',
  hideUpdated = false,
  sx,
}: CondoCheckSummaryProps) {
  const lines = resolveCondoCheckLines(commandCenterData)
  const pct =
    mapCondoConfidencePercent(commandCenterData.condo_confidence)
    ?? (lines.confidenceLine ? 30 : null)
  const gaugeValue = pct ?? 0
  const color = condoGaugeColor(lines.verdict, pct)
  const updatedAt = commandCenterData.condo_checked_at
    ? formatDateOnly(commandCenterData.condo_checked_at)
      || commandCenterData.condo_checked_at.slice(0, 10)
    : null

  const drivers: string[] = []
  const rawDrivers = commandCenterData.condo_check_drivers
  if (Array.isArray(rawDrivers)) {
    for (const rule of rawDrivers) {
      const label = humanizeCondoDriver(rule)
      if (label && !drivers.includes(label)) drivers.push(label)
    }
  }
  if (lines.reasonLine && drivers.length === 0) {
    drivers.push(lines.reasonLine)
  }

  return (
    <Box
      data-testid={`${testIdStem}-check`}
      sx={[
        {
          boxSizing: 'border-box',
          display: 'flex',
          flexDirection: 'row',
          alignItems: 'center',
          gap: 1.25,
          py: 1,
          px: 1.75,
          borderRadius: 1,
          border: '1px solid',
          borderColor: 'divider',
          bgcolor: 'background.paper',
          textAlign: 'left',
          minWidth: 0,
          width: '100%',
          overflow: 'visible',
        },
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
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
          value={pct != null ? gaugeValue : 0}
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
            data-testid={`${testIdStem}-confidence-value`}
            sx={{ fontSize: '1.05rem', fontWeight: 800, lineHeight: 1, color: 'text.primary' }}
          >
            {pct != null ? `${pct}%` : '—'}
          </Typography>
          <Typography
            component="div"
            sx={{
              mt: 0.15,
              fontSize: '0.5rem',
              fontWeight: 700,
              lineHeight: 1.1,
              color: 'text.secondary',
              maxWidth: 48,
              textTransform: 'uppercase',
            }}
          >
            conf.
          </Typography>
        </Box>
      </Box>

      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 0.45 }}>
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0.15, minWidth: 0 }}>
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
            Condo check
          </Typography>
          {!hideUpdated && (
            <Typography
              variant="caption"
              color="text.disabled"
              data-testid={`${testIdStem}-updated`}
              sx={{ fontSize: '0.65rem', lineHeight: 1.2, whiteSpace: 'nowrap' }}
              title={updatedAt ? `Checked ${updatedAt}` : undefined}
            >
              Updated: {updatedAt ?? '—'}
            </Typography>
          )}
        </Box>

        <Typography
          data-testid={`${testIdStem}-verdict`}
          sx={{
            fontSize: '0.8rem',
            fontWeight: 700,
            lineHeight: 1.25,
            color: 'text.primary',
          }}
        >
          {lines.verdict}
        </Typography>

        {drivers.length === 0 ? (
          <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.7rem' }}>
            {lines.reasonLine ?? 'No condo-check drivers yet.'}
          </Typography>
        ) : (
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'column',
              gap: 0.5,
              width: '100%',
              minWidth: 0,
            }}
            data-testid={`${testIdStem}-drivers`}
          >
            {drivers.slice(0, 2).map((driver) => (
              <Chip
                key={driver}
                size="small"
                icon={iconForDriver(driver)}
                label={driver}
                title={driver}
                data-testid={`${testIdStem}-driver-chip`}
                sx={{
                  width: '100%',
                  maxWidth: '100%',
                  height: 'auto',
                  minHeight: 24,
                  justifyContent: 'flex-start',
                  borderRadius: 0.75,
                  bgcolor: 'rgba(245, 158, 11, 0.12)',
                  color: '#B45309',
                  fontWeight: 600,
                  fontSize: '0.65rem',
                  py: 0.35,
                  overflow: 'visible',
                  '& .MuiChip-icon': {
                    color: '#B45309',
                    ml: 0.35,
                    mr: -0.15,
                    flexShrink: 0,
                  },
                  '& .MuiChip-label': {
                    px: 0.5,
                    whiteSpace: 'normal',
                    overflow: 'visible',
                    textOverflow: 'clip',
                    display: 'block',
                    lineHeight: 1.25,
                  },
                }}
              />
            ))}
          </Box>
        )}
      </Box>
    </Box>
  )
}

export default CondoCheckSummary
