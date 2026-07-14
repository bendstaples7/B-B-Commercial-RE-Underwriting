/**
 * DataSourcesPanel — read-only diagnostic UI for data source health.
 *
 * This file is built up across multiple tasks:
 *   Task 6.1 — DataSourcesPanel (top-level), DataSourcesSkeleton, DataSourcesError
 *   Task 6.2 — StatusChip, StatusSummaryBanner  ← this file starts here
 *   Task 6.3 — SocrataSourceCard
 *   Task 6.4 — CoverageBar, EnrichmentSourceCard
 *   Task 6.5 — ImportSourceCard, HubSpotSourceCard
 *   Task 6.6 — wires all sub-components into the loaded state
 *
 * NOTE on aria-label for StatusChip icons:
 *   StatusChip itself does not know the source name, so it cannot produce
 *   the full `aria-label="{name}: {status}"` required by Req 7.3.
 *   Callers (SocrataSourceCard, EnrichmentSourceCard, etc.) must wrap the
 *   chip or its parent container with an appropriate aria-label, e.g.:
 *     <Box aria-label={`${source.name}: ${source.status}`}>
 *       <StatusChip status={source.status} />
 *     </Box>
 */

import React from 'react'
import { Alert, Box, Button, Card, CardContent, Chip, LinearProgress, Link, Skeleton, Typography } from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import ErrorIcon from '@mui/icons-material/Error'
import { useQuery } from '@tanstack/react-query'

import { dataSourcesService } from '@/services/api'
import type { DataSourceStatus, EnrichmentSourceStatus, GISConnectorStatus, HubSpotSourceStatus, ImportSourceStatus, SocrataDatasetStatus } from '@/types'

// ---------------------------------------------------------------------------
// StatusChip
// ---------------------------------------------------------------------------

type ChipColor = 'success' | 'warning' | 'error' | 'default'

interface StatusChipConfig {
  color: ChipColor
  icon: React.ReactElement
  label: string
}

const STATUS_CHIP_CONFIG: Record<string, StatusChipConfig> = {
  fresh: { color: 'success', icon: <CheckCircleIcon />, label: 'Fresh' },
  stale: { color: 'warning', icon: <WarningAmberIcon />, label: 'Stale' },
  empty: { color: 'error', icon: <ErrorIcon />, label: 'Empty' },
  never_synced: { color: 'error', icon: <ErrorIcon />, label: 'Never Synced' },
  active: { color: 'success', icon: <CheckCircleIcon />, label: 'Active' },
  inactive: { color: 'default', icon: <ErrorIcon />, label: 'Inactive' },
}

const DEFAULT_STATUS_CHIP_CONFIG = (status: string): StatusChipConfig => ({
  color: 'default',
  icon: <ErrorIcon />,
  label: status,
})

/**
 * Small MUI Chip mapping a status string to the appropriate color and icon.
 *
 * NOTE: This component does not receive a source name, so it cannot set
 * `aria-label="{name}: {status}"` on its own. The calling component is
 * responsible for wrapping this chip (or its icon) with an aria-label that
 * includes the source name. See the file-level comment for the pattern.
 */
export function StatusChip({ status }: { status: string }) {
  const config = STATUS_CHIP_CONFIG[status] ?? DEFAULT_STATUS_CHIP_CONFIG(status)
  return (
    <Chip
      size="small"
      color={config.color}
      icon={config.icon}
      label={config.label}
    />
  )
}

// ---------------------------------------------------------------------------
// StatusSummaryBanner
// ---------------------------------------------------------------------------

/**
 * Green summary banner when all sources are healthy; amber or red otherwise.
 *
 * "All healthy" means:
 *   - Every Socrata dataset has status === 'fresh'
 *   - Every enrichment source has is_active === true
 *   - No enrichment source has failed_count > 0 (proxy for recent failures)
 *
 * Satisfies Requirement 6.5.
 */
export function StatusSummaryBanner({ data }: { data: DataSourceStatus }) {
  const allSocrataFresh = data.socrata_datasets.every(ds => ds.status === 'fresh')
  const allEnrichmentActive = data.enrichment_sources.every(es => es.is_active)
  const noEnrichmentFailures = data.enrichment_sources.every(es => es.failed_count === 0)

  const isAllHealthy = allSocrataFresh && allEnrichmentActive && noEnrichmentFailures

  if (isAllHealthy) {
    return (
      <Alert severity="success" icon={<CheckCircleIcon />} sx={{ mb: 2 }}>
        All data sources are current.
      </Alert>
    )
  }

  const issues: string[] = []
  if (!allSocrataFresh) issues.push('Some Socrata datasets are not fresh')
  if (!allEnrichmentActive) issues.push('Some enrichment sources are inactive')
  if (!noEnrichmentFailures) issues.push('Some enrichment sources have failures')

  // Red when any dataset is in a hard-error state; amber for stale/inactive
  const hasHardError = data.socrata_datasets.some(
    ds => ds.status === 'never_synced' || ds.status === 'empty',
  )
  const severity = !allSocrataFresh && hasHardError ? 'error' : 'warning'

  return (
    <Alert severity={severity} sx={{ mb: 2 }}>
      {issues.join('. ')}
    </Alert>
  )
}

// ---------------------------------------------------------------------------
// DataSourcesSkeleton
// ---------------------------------------------------------------------------

/**
 * Loading skeleton — one rectangular Skeleton row per expected source.
 * Uses 7 rows: 3 Socrata + ~2 enrichment + 1 import + 1 HubSpot.
 * Requirements: 7.1
 */
export function DataSourcesSkeleton() {
  return (
    <Box sx={{ p: 2 }} aria-label="Loading data sources">
      {Array.from({ length: 7 }).map((_, i) => (
        <Skeleton
          key={i}
          variant="rectangular"
          height={80}
          sx={{ mb: 2, borderRadius: 1 }}
        />
      ))}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// DataSourcesError
// ---------------------------------------------------------------------------

/**
 * Error state with message Alert and Retry button.
 * Retry bypasses the 60-second stale cache via cancelRefetch.
 * Requirements: 7.2, 7.4
 */
export function DataSourcesError({ onRetry }: { onRetry: () => void }) {
  return (
    <Box sx={{ p: 2 }}>
      <Alert severity="error" sx={{ mb: 2 }}>
        Data source status could not be loaded.
      </Alert>
      <Button variant="outlined" onClick={onRetry}>
        Retry
      </Button>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// formatTimestamp — shared helper
// ---------------------------------------------------------------------------

/**
 * Formats an ISO-8601 UTC timestamp as "MM/DD/YYYY HH:MM" in the local timezone.
 * Returns "No successful sync has occurred" when the input is null.
 */
export function formatTimestamp(isoString: string | null): string {
  if (!isoString) return 'No successful sync has occurred'
  const d = new Date(isoString)
  if (isNaN(d.getTime())) return isoString   // fall back to raw string if unparseable
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const yyyy = d.getFullYear()
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${mm}/${dd}/${yyyy} ${hh}:${min}`
}

/**
 * Returns the next Sunday at 02:00 UTC formatted as "MM/DD/YYYY" in UTC.
 * The Celery Beat schedule runs every Sunday at 02:00 UTC.
 * If today is Sunday and the 02:00 UTC refresh hasn't happened yet, returns today.
 */
function nextSundayRefresh(): string {
  const now = new Date()
  const utcDay = now.getUTCDay()       // 0=Sun, 1=Mon, ..., 6=Sat
  let daysUntilSunday: number
  if (utcDay === 0) {
    // It's Sunday — check if 02:00 UTC refresh has already run today
    daysUntilSunday = now.getUTCHours() < 2 ? 0 : 7
  } else {
    daysUntilSunday = 7 - utcDay
  }
  const next = new Date(Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + daysUntilSunday,
    2, 0, 0,
  ))
  // Format using UTC date parts so the date matches the UTC schedule
  const mm = String(next.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(next.getUTCDate()).padStart(2, '0')
  const yyyy = next.getUTCFullYear()
  return `${mm}/${dd}/${yyyy}`
}

// ---------------------------------------------------------------------------
// CoverageBar
// ---------------------------------------------------------------------------

interface CoverageBarProps {
  successCount: number
  failedCount: number
  noResultsCount: number
  notRunCount: number
  totalLeadsCount: number
}

/**
 * MUI LinearProgress bar showing enrichment coverage.
 * Value clamped to [0, 100]. Shows "0 / 0 (N/A)" when total is 0.
 * Legend: "Enriched X | Failed Y | Not Run Z"
 *
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
 */
export function CoverageBar({ successCount, failedCount, noResultsCount, notRunCount, totalLeadsCount }: CoverageBarProps) {
  const pct = totalLeadsCount > 0 ? Math.min(100, Math.max(0, (successCount / totalLeadsCount) * 100)) : 0
  const coverageText = totalLeadsCount === 0
    ? '0 / 0 (N/A)'
    : `${successCount} / ${totalLeadsCount} (${pct.toFixed(0)}%)`

  return (
    <Box sx={{ mt: 1 }}>
      <LinearProgress
        variant="determinate"
        value={pct}
        color={pct === 100 ? 'success' : 'primary'}
        sx={{ height: 8, borderRadius: 4, mb: 0.5 }}
      />
      <Typography variant="caption" sx={{ color: pct === 0 ? 'text.secondary' : 'text.primary' }}>
        {coverageText}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
        Enriched {successCount} | Failed {failedCount} | No Data {noResultsCount} | Not Run {notRunCount}
      </Typography>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// EnrichmentSourceCard
// ---------------------------------------------------------------------------

interface EnrichmentSourceCardProps {
  source: EnrichmentSourceStatus
  dataUpdatedAt: number  // from React Query — milliseconds since epoch
}

/**
 * Card for one enrichment plugin. Displays:
 * - Source name, refresh type label (Automatic / On Demand)
 * - CoverageBar with enriched/failed/not-run counts
 * - Last updated timestamp with staleness note when data is > 60s old
 * - Amber warning when failures exist
 * - Reduced opacity + "Inactive" label when is_active === false
 *
 * Requirements: 1.1, 1.5, 2.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 6.4
 */
export function EnrichmentSourceCard({ source, dataUpdatedAt }: EnrichmentSourceCardProps) {
  const isInactive = !source.is_active
  const isStale = Date.now() - dataUpdatedAt > 60_000

  return (
    <Card sx={{ mb: 2, opacity: isInactive ? 0.5 : 1 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Typography variant="subtitle1" fontWeight="bold">
            {source.name}
            {isInactive && (
              <Typography component="span" variant="caption" sx={{ ml: 1, color: 'text.secondary' }}>
                (Inactive)
              </Typography>
            )}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {source.refresh_type === 'automatic' ? 'Automatic' : 'On Demand'}
          </Typography>
        </Box>

        <CoverageBar
          successCount={source.success_count}
          failedCount={source.failed_count}
          noResultsCount={source.no_results_count}
          notRunCount={source.not_run_count}
          totalLeadsCount={source.total_leads_count}
        />

        {source.last_refreshed_at && (
          <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'text.secondary' }}>
            Last updated: {formatTimestamp(source.last_refreshed_at)}
            {isStale && ' (data may be stale)'}
          </Typography>
        )}

        {source.failed_count > 0 && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 1 }}>
            <WarningAmberIcon color="warning" fontSize="small" />
            <Typography variant="body2" color="warning.main">
              {source.failed_count} failure{source.failed_count !== 1 ? 's' : ''} in last 30 days
            </Typography>
          </Box>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// DataSourcesPanel (top-level — default export)
// ---------------------------------------------------------------------------

/**
 * Top-level panel component. Owns the React Query call and orchestrates all
 * sub-components.
 *
 * Requirements: 1.6, 7.1, 7.2, 7.4, 7.5
 */
export default function DataSourcesPanel() {
  const {
    data,
    isLoading,
    isError,
    dataUpdatedAt,
    refetch,
  } = useQuery<DataSourceStatus, Error>({
    queryKey: ['dataSourceStatus'],
    queryFn: dataSourcesService.getStatus,
    staleTime: 60_000,   // Req 7.5 — do not re-fetch more than once per 60s
  })

  if (isLoading) return <DataSourcesSkeleton />
  if (isError) return <DataSourcesError onRetry={() => refetch({ cancelRefetch: true })} />
  if (!data) return <DataSourcesSkeleton />
  // Only show "no data sources" when all four source categories are empty/null
  const allEmpty = data.socrata_datasets.length === 0 &&
                   data.enrichment_sources.length === 0 &&
                   !data.import_source &&
                   !data.hubspot_source &&
                   (!data.gis_connectors || data.gis_connectors.length === 0)

  return (
    <Box sx={{ p: { xs: 1, sm: 2 }, maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      <Typography variant="h5" gutterBottom>Data Sources</Typography>

      {allEmpty ? (
        <Typography color="text.secondary">No data sources are configured.</Typography>
      ) : (
        <>
          <StatusSummaryBanner data={data} />
          {/* Socrata Datasets section */}
          {data.socrata_datasets.length > 0 && (
            <>
              <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>Socrata Datasets</Typography>
              {data.socrata_datasets.map(ds => (
                <SocrataSourceCard key={ds.name} source={ds} />
              ))}
            </>
          )}

          {/* Enrichment Sources section */}
          <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>Enrichment Sources</Typography>
          {data.enrichment_sources.length === 0 ? (
            <Typography color="text.secondary" sx={{ mb: 2 }}>No enrichment sources configured.</Typography>
          ) : (
            data.enrichment_sources.map(es => (
              <EnrichmentSourceCard key={es.name} source={es} dataUpdatedAt={dataUpdatedAt} />
            ))
          )}

          {/* Import Source section */}
          <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>Import Source</Typography>
          <ImportSourceCard source={data.import_source} />

          {/* HubSpot section */}
          <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>HubSpot</Typography>
          <HubSpotSourceCard source={data.hubspot_source} />

          {/* GIS Connectors section */}
          {data.gis_connectors && data.gis_connectors.length > 0 && (
            <>
              <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>GIS Parcel Connectors</Typography>
              {data.gis_connectors.map(gc => (
                <GISConnectorCard key={gc.market} source={gc} />
              ))}
            </>
          )}
        </>
      )}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// SocrataSourceCard
// ---------------------------------------------------------------------------

/**
 * Card displaying health and metadata for a single Socrata dataset.
 *
 * - Shows "Periodic" refresh-type label
 * - Shows a StatusChip for the dataset status
 * - Amber WarningAmberIcon when status === 'stale'; includes days-since-sync count
 * - Red ErrorIcon when status === 'never_synced' or 'empty'
 * - "No successful sync has occurred" when last_refreshed_at is null
 * - Shows last_error when present; falls back to "Sync failed — no details available."
 * - Reduced opacity (0.5) and "(Inactive)" label when is_active === false
 *
 * Requirements: 1.2, 1.5, 2.1, 2.2, 3.1, 3.2, 6.1, 6.2, 6.3
 */
export function SocrataSourceCard({ source }: { source: SocrataDatasetStatus }) {
  const isInactive = !source.is_active
  const isStale = source.status === 'stale'
  const isError = source.status === 'never_synced' || source.status === 'empty'

  return (
    <Card sx={{ mb: 2, opacity: isInactive ? 0.5 : 1 }}>
      <CardContent>
        {/* Header row: name, inactive label, refresh type, status chip, warning/error icons */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
          <Typography variant="subtitle1" fontWeight="bold">
            {source.name}
            {isInactive && (
              <Typography
                component="span"
                variant="caption"
                sx={{ ml: 1, color: 'text.secondary' }}
              >
                (Inactive)
              </Typography>
            )}
          </Typography>

          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Periodic
          </Typography>

          <Box aria-label={`${source.name}: ${source.status}`}>
            <StatusChip status={source.status} />
          </Box>

          {isStale && (
            <WarningAmberIcon
              color="warning"
              fontSize="small"
              aria-label={`${source.name}: stale`}
            />
          )}

          {isError && (
            <ErrorIcon
              color="error"
              fontSize="small"
              aria-label={`${source.name}: ${source.status}`}
            />
          )}
        </Box>

        {/* Last refreshed timestamp */}
        <Typography variant="body2" color="text.secondary">
          {source.last_refreshed_at
            ? <>Last refreshed: {formatTimestamp(source.last_refreshed_at)}</>
            : source.status === 'never_synced'
              ? 'Cache not yet populated on this environment.'
              : 'No successful sync has occurred.'
          }
        </Typography>

        {/* Next scheduled refresh */}
        <Typography variant="body2" color="text.secondary">
          Next refresh: {nextSundayRefresh()} (weekly, every Sunday)
        </Typography>

        {/* Days since last sync (stale only) */}
        {isStale && source.days_since_sync !== null && (
          <Typography variant="body2" color="warning.main">
            {source.days_since_sync} day{source.days_since_sync !== 1 ? 's' : ''} since last sync
          </Typography>
        )}

        {/* Last error message — only shown when status is degraded (empty/never_synced) */}
        {(source.last_error !== null && source.last_error !== undefined) && (source.status === 'empty' || source.status === 'never_synced') && (
          <Typography variant="body2" color="error.main" sx={{ mt: 1 }}>
            {source.last_error || 'Sync failed — no details available.'}
          </Typography>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// ImportSourceCard
// ---------------------------------------------------------------------------

/**
 * Card for the Google Sheets / static import source.
 *
 * - Shows "Static" refresh type label
 * - When a completed import exists: shows last import timestamp (YYYY-MM-DD HH:MM
 *   local time) and the number of rows imported
 * - Otherwise shows "No imports yet."
 *
 * Requirements: 1.3, 2.4, 3.3
 */
export function ImportSourceCard({ source }: { source: ImportSourceStatus }) {
  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Typography variant="subtitle1" fontWeight="bold">{source.name}</Typography>
          <Typography variant="caption" color="text.secondary">Static</Typography>
        </Box>

        {source.last_refreshed_at ? (
          <>
            <Typography variant="body2">
              Last import: {formatTimestamp(source.last_refreshed_at)}
              {source.scope === 'org' ? ' (team import)' : source.scope === 'user' ? ' (your import)' : ''}
            </Typography>
            {source.rows_imported !== null && (
              <Typography variant="body2" color="text.secondary">
                {source.rows_imported} rows imported
                {(source.completed_import_count ?? 0) > 1
                  ? ` · ${source.completed_import_count} successful imports`
                  : ''}
              </Typography>
            )}
            <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
              <Link href="/import" underline="hover">View import history</Link>
            </Typography>
          </>
        ) : (
          <Typography variant="body2" color="text.secondary">
            No imports yet.
          </Typography>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// HubSpotSourceCard
// ---------------------------------------------------------------------------

/**
 * Card for the HubSpot integration source.
 *
 * - Shows "On Demand" refresh type label
 * - Green "Connected" chip when connected === true
 * - Grey "Not configured" chip otherwise
 *
 * Requirements: 1.4, 2.4, 3.3
 */
export function HubSpotSourceCard({ source }: { source: HubSpotSourceStatus }) {
  return (
    <Card sx={{ mb: 2 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Typography variant="subtitle1" fontWeight="bold">{source.name}</Typography>
          <Typography variant="caption" color="text.secondary">On Demand</Typography>
          {source.connected ? (
            <Chip size="small" color="success" icon={<CheckCircleIcon />} label="Connected" />
          ) : (
            <Chip size="small" color="default" label="Not configured" />
          )}
        </Box>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// GISConnectorCard
// ---------------------------------------------------------------------------

/**
 * Card displaying match coverage for a single GIS county connector.
 *
 * Shows:
 * - Connector name and county(ies) covered
 * - "Automatic" refresh type badge
 * - Active/Inactive chip
 * - Match coverage bar: matched vs unmatched vs total
 * - API source URL
 */
export function GISConnectorCard({ source }: { source: GISConnectorStatus }) {
  const rawMatchPct = source.total_count > 0
    ? Math.round((source.matched_count / source.total_count) * 100)
    : 0
  // Clamp to [0, 100] and guard NaN/undefined → 0 so the bar and label never
  // exceed 100% even if matched_count > total_count in the source data.
  const matchPct = Number.isFinite(rawMatchPct)
    ? Math.min(100, Math.max(0, rawMatchPct))
    : 0

  return (
    <Card sx={{ mb: 2, opacity: source.is_active ? 1 : 0.5 }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1, flexWrap: 'wrap' }}>
          <Typography variant="subtitle1" fontWeight="bold">{source.name}</Typography>
          <Typography variant="caption" color="text.secondary">Automatic · {source.counties.join(', ')} County</Typography>
          {source.is_active ? (
            <Chip size="small" color="success" icon={<CheckCircleIcon />} label="Active" />
          ) : (
            <Chip size="small" color="default" label="Inactive" />
          )}
        </Box>

        {source.total_count > 0 && (
          <Box sx={{ mb: 1 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="caption" color="text.secondary">
                PIN match coverage
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {source.matched_count.toLocaleString()} / {source.total_count.toLocaleString()} leads ({matchPct}%)
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={matchPct}
              color={matchPct >= 80 ? 'success' : matchPct >= 40 ? 'warning' : 'error'}
              sx={{ height: 8, borderRadius: 4 }}
            />
            {source.unmatched_count > 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                {source.unmatched_count.toLocaleString()} leads pending GIS match (backfill runs every 6 hours)
              </Typography>
            )}
          </Box>
        )}

        <Typography variant="caption" color="text.secondary">
          Source: {source.api_url}
        </Typography>
      </CardContent>
    </Card>
  )
}
