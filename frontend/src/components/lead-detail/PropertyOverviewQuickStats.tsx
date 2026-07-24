/**
 * Property Overview Quick-Stats — 2×2 metric cells in the header middle band.
 */
import React from 'react'
import { Box, Tooltip, Typography } from '@mui/material'
import type { CommandCenterPayload } from '@/types'
import { ccKpiLabelSx, ccKpiValueSx } from '@/components/lead-detail/commandCenterChrome'
import { formatPropertyTypeLabel } from '@/utils/formatters'

const EM_DASH = '—'

export function formatMoneyValue(value: number | string | null | undefined): string | null {
  if (value == null || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return null
  return `$${Math.round(n).toLocaleString()}`
}

/** Normalize sale display strings to a readable date (prefer MM/DD/YYYY). */
export function formatSaleDatePart(saleDisplay: string | null | undefined): string | null {
  if (!saleDisplay) return null
  const raw = String(saleDisplay).trim()
  if (!raw) return null
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso) {
    return `${iso[2]}/${iso[3]}/${iso[1]}`
  }
  return raw
}

/**
 * Last sale cell: always surface date + amount when both exist (two lines).
 * e.g. "01/03/1989\\n$305,000"
 */
export function formatLastSaleCell(
  price: number | null | undefined,
  saleDisplay: string | null | undefined,
): string | null {
  const money = formatMoneyValue(price ?? null)
  const datePart = formatSaleDatePart(saleDisplay)
  if (money && datePart) return `${datePart}\n${money}`
  if (money) return money
  if (datePart) return datePart
  return null
}

/** Prefer lead fields; fill gaps from newest sale_history row when present. */
export function resolveLastSaleCell(commandCenterData: CommandCenterPayload): string | null {
  let price = commandCenterData.most_recent_sale_price ?? null
  let display =
    commandCenterData.most_recent_sale_display
    ?? commandCenterData.most_recent_sale
    ?? null

  const history = commandCenterData.sale_history
  if (Array.isArray(history) && history.length > 0) {
    const newest = history[0]
    if (price == null && newest?.sale_price != null) {
      price = newest.sale_price
    }
    if (!display && newest?.sale_date) {
      display = newest.sale_date
    }
  }

  return formatLastSaleCell(price, display)
}

export function formatUnitsDetailsCell(
  units: number | null | undefined,
  propertyType: string | null | undefined,
): string | null {
  const typeLabel = formatPropertyTypeLabel(propertyType)
  const unitsPart =
    units != null && Number.isFinite(Number(units))
      ? `${Number(units)} Unit${Number(units) === 1 ? '' : 's'}`
      : null
  if (unitsPart && typeLabel) return `${unitsPart} · ${typeLabel}`
  if (unitsPart) return unitsPart
  if (typeLabel) return typeLabel
  return null
}

export interface PropertyOverviewQuickStatsProps {
  commandCenterData: CommandCenterPayload
}

export function PropertyOverviewQuickStats({ commandCenterData }: PropertyOverviewQuickStatsProps) {
  const estValue = formatMoneyValue(commandCenterData.assessed_value ?? null)
  // Est. rent has no lead field yet — omit the cell until a source exists.
  const estRent: string | null = null
  const lastSale = resolveLastSaleCell(commandCenterData)
  const unitsDetails = formatUnitsDetailsCell(
    commandCenterData.units ?? null,
    commandCenterData.property_type ?? null,
  )

  const cells: {
    id: string
    label: string
    value: string
    tooltip?: string
    allowWrap?: boolean
  }[] = [
    {
      id: 'est-value',
      label: 'Est. value',
      value: estValue ?? EM_DASH,
      tooltip: 'Assessor assessed value (not analysis ARV)',
    },
    ...(estRent
      ? [{ id: 'est-rent', label: 'Est. rent', value: estRent }]
      : []),
    {
      id: 'last-sale',
      label: 'Last sale',
      value: lastSale ?? EM_DASH,
      allowWrap: true,
    },
    {
      id: 'units-details',
      label: 'Units / details',
      value: unitsDetails ?? EM_DASH,
    },
  ]

  return (
    <Box
      data-testid="property-overview-quick-stats"
      sx={{
        // Compact even 2×2 — leave horizontal room for the score panel.
        flex: { xs: '1 1 100%', md: '0 1 280px' },
        minWidth: { xs: '100%', md: 240 },
        maxWidth: { xs: '100%', md: 300 },
        display: 'grid',
        gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
        columnGap: { xs: 1.5, md: 2 },
        rowGap: { xs: 0.75, md: 1 },
        alignContent: 'center',
        justifyItems: 'stretch',
        px: { md: 0.5 },
        mr: { md: 0.5 },
      }}
    >
      {cells.map((cell) => {
        const body = (
          <Box data-testid={`quick-stat-${cell.id}`} sx={{ minWidth: 0 }}>
            <Typography sx={{ ...ccKpiLabelSx, fontSize: '0.65rem' }}>{cell.label}</Typography>
            <Typography
              sx={{
                ...ccKpiValueSx,
                fontSize: '0.875rem',
                mt: 0.125,
                lineHeight: 1.25,
                whiteSpace: cell.allowWrap ? 'pre-line' : 'nowrap',
              }}
              title={cell.value.replace(/\n/g, ' · ')}
            >
              {cell.value}
            </Typography>
          </Box>
        )
        return cell.tooltip ? (
          <Tooltip key={cell.id} title={cell.tooltip} enterDelay={400}>
            {body}
          </Tooltip>
        ) : (
          <React.Fragment key={cell.id}>{body}</React.Fragment>
        )
      })}
    </Box>
  )
}

export default PropertyOverviewQuickStats
