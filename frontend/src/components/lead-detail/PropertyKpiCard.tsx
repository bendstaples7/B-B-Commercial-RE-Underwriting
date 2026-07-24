/**
 * At a glance — compact metric grid under Key Contact (label-over-value cells).
 */
import { Box, Link, Paper, Typography } from '@mui/material'
import type { CommandCenterPayload, PropertyDetail } from '@/types'
import {
  ccCardSx,
  ccMetaSx,
  ccSectionTitleSx,
} from '@/components/lead-detail/commandCenterChrome'
import { resolveMailerHistorySummary } from '@/utils/mailerHistory'

export interface PropertyKpiCardProps {
  commandCenterData: CommandCenterPayload
  propertyDetail?: PropertyDetail | null
}

export type AtAGlanceRow = {
  id: string
  label: string
  value: string
  /** Long-form rows sit under the metric grid. */
  wide?: boolean
}

type GridCell =
  | { kind: 'metric'; row: AtAGlanceRow }
  | { kind: 'see-more' }
  | { kind: 'empty' }

function money(value: number | string | null | undefined): string | null {
  if (value == null || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return null
  return `$${n.toLocaleString()}`
}

function bedsBaths(
  bedrooms: number | null | undefined,
  bathrooms: number | null | undefined,
): string | null {
  if (bedrooms == null && bathrooms == null) return null
  return `${bedrooms ?? '—'} bd / ${bathrooms ?? '—'} ba`
}

function squareFeet(value: number | null | undefined): string | null {
  if (value == null || !Number.isFinite(Number(value))) return null
  return `${Number(value).toLocaleString()} SF`
}

function formatMailerGlance(commandCenterData: CommandCenterPayload): string | null {
  const summary = resolveMailerHistorySummary(
    commandCenterData.mailer_history_summary,
    (commandCenterData as { mailer_history?: unknown }).mailer_history,
  )
  if (summary.count <= 0) return null
  const last = summary.last_sent_at ? ` · Last ${summary.last_sent_at}` : ''
  const latest = summary.rows[0]
  const latestLine = latest
    ? `\n${latest.sent_at ? `${latest.sent_at}: ` : ''}${latest.label}`
    : ''
  return `${summary.count} mailer${summary.count === 1 ? '' : 's'}${last}${latestLine}`
}

export function buildAtAGlanceRows(
  commandCenterData: CommandCenterPayload,
  propertyDetail?: PropertyDetail | null,
): AtAGlanceRow[] {
  const tax = money(
    propertyDetail?.tax_bill_2021 ?? commandCenterData.tax_bill_2021 ?? null,
  )

  const mailer = formatMailerGlance(commandCenterData)
  const dealSource = commandCenterData.deal_source?.trim() || null
  const dealDescription = commandCenterData.deal_description?.trim() || null

  const candidates: Array<AtAGlanceRow | { id: string; label: string; value: string | null; wide?: boolean }> = [
    // Type/units live in Property Overview Quick Stats — omit here to avoid duplication.
    {
      id: 'beds-baths',
      label: 'Beds / baths',
      value: bedsBaths(
        commandCenterData.bedrooms ?? propertyDetail?.bedrooms,
        commandCenterData.bathrooms ?? propertyDetail?.bathrooms,
      ),
    },
    {
      id: 'sqft',
      label: 'Sq ft',
      value: squareFeet(
        commandCenterData.square_footage ?? propertyDetail?.square_footage,
      ),
    },
    {
      id: 'year-built',
      label: 'Year built',
      value:
        commandCenterData.year_built != null
          ? String(commandCenterData.year_built)
          : propertyDetail?.year_built != null
            ? String(propertyDetail.year_built)
            : null,
    },
    { id: 'tax', label: 'Tax', value: tax },
    { id: 'deal-source', label: 'Deal source', value: dealSource },
    {
      id: 'deal-description',
      label: 'Deal description',
      value: dealDescription,
      wide: true,
    },
    {
      id: 'mailer-history',
      label: 'Mailer history',
      value: mailer,
      wide: true,
    },
  ]

  return candidates.filter(
    (row): row is AtAGlanceRow => Boolean(row.value),
  )
}

/** Metric cells + trailing See more, padded so the 3-column grid stays full. */
export function buildMetricGridCells(metricRows: AtAGlanceRow[]): GridCell[] {
  const cells: GridCell[] = metricRows.map((row) => ({ kind: 'metric', row }))
  cells.push({ kind: 'see-more' })
  while (cells.length % 3 !== 0) {
    cells.push({ kind: 'empty' })
  }
  return cells
}

function scrollToDeepDive() {
  const el = document.getElementById('deep-dive-details')
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  window.history.replaceState(null, '', '#deep-dive-details')
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

function MetricCell({ row }: { row: AtAGlanceRow }) {
  return (
    <Box
      data-testid={`kpi-${row.id}`}
      sx={{
        px: 1.25,
        py: 1.25,
        minWidth: 0,
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      <Typography
        sx={{
          fontSize: '0.7rem',
          fontWeight: 500,
          letterSpacing: 0.01,
          lineHeight: 1.2,
          color: 'text.secondary',
          mb: 0.5,
        }}
      >
        {row.label}
      </Typography>
      <Typography
        sx={{
          fontSize: '0.8rem',
          fontWeight: 400,
          lineHeight: 1.3,
          color: 'text.primary',
          overflowWrap: 'anywhere',
          wordBreak: 'break-word',
          whiteSpace: 'pre-line',
        }}
      >
        {row.value}
      </Typography>
    </Box>
  )
}

function SeeMoreCell() {
  return (
    <Box
      data-testid="kpi-see-more"
      sx={{
        px: 1.25,
        py: 1.25,
        minWidth: 0,
        height: '100%',
        boxSizing: 'border-box',
        display: 'flex',
        alignItems: 'center',
      }}
    >
      <Link
        href="#deep-dive-details"
        underline="hover"
        onClick={(event) => {
          event.preventDefault()
          scrollToDeepDive()
        }}
        sx={{
          fontSize: '0.8rem',
          fontWeight: 600,
          color: 'primary.main',
          cursor: 'pointer',
        }}
      >
        See more
      </Link>
    </Box>
  )
}

function MetricGrid({ cells }: { cells: GridCell[] }) {
  return (
    <Box
      data-testid="kpi-metric-grid"
      sx={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
        borderTop: '1px solid',
        borderLeft: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        overflow: 'hidden',
        bgcolor: 'background.paper',
      }}
    >
      {cells.map((cell, idx) => (
        <Box
          key={
            cell.kind === 'metric'
              ? cell.row.id
              : cell.kind === 'see-more'
                ? 'see-more'
                : `pad-${idx}`
          }
          sx={{
            borderRight: '1px solid',
            borderBottom: '1px solid',
            borderColor: 'divider',
            minWidth: 0,
            minHeight: 64,
          }}
        >
          {cell.kind === 'metric' ? <MetricCell row={cell.row} /> : null}
          {cell.kind === 'see-more' ? <SeeMoreCell /> : null}
        </Box>
      ))}
    </Box>
  )
}

/**
 * Sibling summary card under Key Contact — 3-column metric grid with hairline rules.
 */
export function PropertyKpiCard({
  commandCenterData,
  propertyDetail,
}: PropertyKpiCardProps) {
  const rows = buildAtAGlanceRows(commandCenterData, propertyDetail)
  const metricRows = rows.filter((r) => !r.wide)
  const wideRows = rows.filter((r) => r.wide)
  const gridCells = buildMetricGridCells(metricRows)

  return (
    <Paper data-testid="property-kpi-card" elevation={0} sx={ccCardSx}>
      <Typography sx={ccSectionTitleSx} component="h2">
        At a glance
      </Typography>
      <MetricGrid cells={gridCells} />
      {metricRows.length === 0 && wideRows.length === 0 ? (
        <Typography sx={{ ...ccMetaSx, mt: 1.25 }} data-testid="kpi-empty">
          No summary metrics on file
        </Typography>
      ) : null}
      {wideRows.map((row) => (
        <Box
          key={row.id}
          data-testid={`kpi-${row.id}`}
          sx={{
            mt: 1.5,
            pt: 1.25,
            borderTop: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Typography
            sx={{
              fontSize: '0.7rem',
              fontWeight: 500,
              color: 'text.secondary',
              mb: 0.5,
              lineHeight: 1.2,
            }}
          >
            {row.label}
          </Typography>
          <Typography
            sx={{
              fontSize: '0.8rem',
              fontWeight: 400,
              color: 'text.primary',
              lineHeight: 1.35,
              whiteSpace: 'pre-line',
              overflowWrap: 'anywhere',
              wordBreak: 'break-word',
            }}
          >
            {row.value}
          </Typography>
        </Box>
      ))}
    </Paper>
  )
}

export default PropertyKpiCard
