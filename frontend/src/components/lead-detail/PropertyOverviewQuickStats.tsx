/**
 * Property Overview Quick-Stats — Est. value / Last sale / Units in the header middle band.
 * Condo check lives in HeaderCondoCheckPanel (score-style), not in this grid.
 */
import React from 'react'
import { Box, Tooltip, Typography } from '@mui/material'
import type { CommandCenterPayload, CondoRiskStatus } from '@/types'
import {
  ccHeaderQuickStatsSx,
  ccHeaderQuickStatsCenteredSx,
  ccKpiLabelSx,
  ccKpiValueSx,
} from '@/components/lead-detail/commandCenterChrome'
import {
  formatLeadCategoryLabel,
  formatMoneyValue,
  formatPropertyTypeLabel,
} from '@/utils/formatters'
import { formatSaleDateFreshness } from '@/utils/saleDateFreshness'
import { formatNoteUnitMixLabel } from '@/utils/notePropertyFacts'

const EM_DASH = '—'

export { formatMoneyValue } from '@/utils/formatters'

const CONFIDENCE_PERCENT: Record<string, number> = {
  high: 90,
  medium: 60,
  low: 30,
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
 * Last sale cell: date + amount on one line when both exist.
 * e.g. "01/03/1989 · $305,000"
 */
export function formatLastSaleCell(
  price: number | null | undefined,
  saleDisplay: string | null | undefined,
): string | null {
  const money = formatMoneyValue(price ?? null)
  const datePart = formatSaleDatePart(saleDisplay)
  if (money && datePart) return `${datePart} · ${money}`
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

/**
 * Explicit copy for the "Assessor ladder ran, no sale on file" case — never a
 * bare em-dash. See `docs/cook-county-sale-history-sources.md` and
 * `backend/app/services/helpers/cook_county_sale_date_resolver.py` (primary
 * Assessor → related PIN → MyDec). Do not scrape Redfin for this gap.
 */
export function resolveNoSaleCopy(
  commandCenterData: CommandCenterPayload,
): string | null {
  const meta = commandCenterData.sale_date_meta
  if (!meta || meta.status !== 'no_sale') return null
  return formatSaleDateFreshness(meta, { hasDisplayedSale: false })
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

export function mapCondoConfidencePercent(
  confidence: string | null | undefined,
): number | null {
  if (!confidence) return null
  const key = String(confidence).trim().toLowerCase()
  return CONFIDENCE_PERCENT[key] ?? null
}

/** CRM deal sources that imply commercial inventory (fill-if-blank on backend). */
const COMMERCIAL_DEAL_SOURCES = new Set([
  'costar',
  'cityscape',
  'cityscape unused zoning capacity',
])

export function shouldShowCondoCheckCell(commandCenterData: CommandCenterPayload): boolean {
  const category = (commandCenterData.lead_category ?? '').toLowerCase()
  const propertyType = (commandCenterData.property_type ?? '').toLowerCase()
  const dealSource = (commandCenterData.deal_source ?? '').trim().toLowerCase()
  const street = commandCenterData.property_street ?? ''
  const multiUnitRange = /\d+\s*-\s*\d+/.test(street)
  return (
    category === 'commercial'
    || propertyType.includes('commercial')
    || COMMERCIAL_DEAL_SOURCES.has(dealSource)
    || multiUnitRange
    || Boolean(commandCenterData.condo_analysis_id)
    || Boolean(commandCenterData.condo_risk_status)
    || Boolean(commandCenterData.building_sale_possible)
  )
}

export type CondoCheckLines = {
  verdict: string
  confidenceLine: string | null
  reasonLine: string | null
  tooltip?: string
}

export function resolveCondoCheckLines(
  commandCenterData: CommandCenterPayload,
): CondoCheckLines {
  const status = commandCenterData.condo_risk_status as CondoRiskStatus | null | undefined
  const pct = mapCondoConfidencePercent(commandCenterData.condo_confidence)
  const confidenceLine = pct != null ? `${pct}% confidence` : null
  const reason = (commandCenterData.condo_check_reason || '').trim() || null

  if (commandCenterData.building_ownership_pending) {
    return {
      verdict: 'Checking…',
      confidenceLine: null,
      reasonLine: 'Condo check running',
      tooltip: 'Building ownership analysis is in progress',
    }
  }

  if (!status && !commandCenterData.condo_analysis_id) {
    return {
      verdict: 'Not checked',
      confidenceLine: null,
      reasonLine: 'Run condo check below',
      tooltip: 'Open Building ownership to run the condo check',
    }
  }

  if (status === 'likely_not_condo') {
    return {
      verdict: 'Not condos',
      confidenceLine,
      reasonLine: reason,
      tooltip: reason ?? undefined,
    }
  }
  if (status === 'likely_condo') {
    return {
      verdict: 'Condos',
      confidenceLine,
      reasonLine: reason,
      tooltip: reason ?? undefined,
    }
  }

  return {
    verdict: 'Check unclear',
    confidenceLine: confidenceLine ?? (pct == null ? '30% confidence' : null),
    reasonLine: reason ?? 'Condo check needs more research',
    tooltip: reason ?? undefined,
  }
}

export interface PropertyOverviewQuickStatsProps {
  commandCenterData: CommandCenterPayload
  /** Residential (no condo): center the 2×2 in the address↔score gap. */
  centerInGap?: boolean
}

export function PropertyOverviewQuickStats({
  commandCenterData,
  centerInGap = false,
}: PropertyOverviewQuickStatsProps) {
  const estValue = formatMoneyValue(commandCenterData.assessed_value ?? null)
  const lastSale = resolveLastSaleCell(commandCenterData)
  const noSaleCopy = lastSale ? null : resolveNoSaleCopy(commandCenterData)
  const unitsDetails = formatUnitsDetailsCell(
    commandCenterData.units ?? null,
    commandCenterData.property_type ?? null,
  )
  const categoryLabel = formatLeadCategoryLabel(commandCenterData.lead_category ?? null)
  const noteUnitsHint =
    commandCenterData.note_property_facts?.units != null
      ? `Units from notes${
          commandCenterData.note_property_facts.unit_mix?.length
            ? ` (${formatNoteUnitMixLabel(commandCenterData.note_property_facts.unit_mix)})`
            : ''
        }`
      : undefined

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
    {
      id: 'last-sale',
      label: 'Last sale',
      value: lastSale ?? noSaleCopy ?? EM_DASH,
      // Prefer single line; wrap only as CSS overflow fallback is via nowrap+ellipsis.
      allowWrap: false,
    },
    {
      id: 'units-details',
      label: 'Units / details',
      // User lock 1B: Units may wrap — never nowrap into Category / condo.
      value: unitsDetails ?? EM_DASH,
      allowWrap: true,
      tooltip: noteUnitsHint,
    },
    {
      id: 'category',
      label: 'Category',
      value: categoryLabel || EM_DASH,
      allowWrap: true,
    },
  ]

  return (
    <Box
      data-testid="property-overview-quick-stats"
      data-cc-kpi-band={centerInGap ? 'centered-residential' : 'tight-with-condo'}
      sx={centerInGap ? ccHeaderQuickStatsCenteredSx : ccHeaderQuickStatsSx}
    >
      {cells.map((cell) => {
        const body = (
          <Box
            data-testid={`quick-stat-${cell.id}`}
            sx={{
              minWidth: 0,
              maxWidth: '100%',
              overflow: 'hidden',
              contain: 'layout style',
              isolation: 'isolate',
            }}
          >
            <Typography sx={{ ...ccKpiLabelSx, fontSize: '0.65rem' }}>{cell.label}</Typography>
            <Typography
              data-testid={`quick-stat-${cell.id}-value`}
              sx={{
                ...ccKpiValueSx,
                fontSize: '0.875rem',
                mt: 0.125,
                lineHeight: 1.25,
                minWidth: 0,
                maxWidth: '100%',
                // Last sale: one line. Units/Category: wrap within cell only (no Category spill).
                whiteSpace: cell.allowWrap ? 'normal' : 'nowrap',
                overflowWrap: cell.allowWrap ? 'break-word' : undefined,
                wordBreak: cell.allowWrap ? 'break-word' : undefined,
                textOverflow: cell.allowWrap ? undefined : 'ellipsis',
                overflow: 'hidden',
              }}
              title={cell.tooltip ? undefined : cell.value.replace(/\n/g, ' · ')}
            >
              {cell.value}
            </Typography>
          </Box>
        )

        return cell.tooltip ? (
          <Tooltip key={cell.id} title={cell.tooltip} enterDelay={400}>
            <Box sx={{ minWidth: 0 }}>{body}</Box>
          </Tooltip>
        ) : (
          <React.Fragment key={cell.id}>{body}</React.Fragment>
        )
      })}
    </Box>
  )
}

export default PropertyOverviewQuickStats
