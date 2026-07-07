/**
 * ProspectReviewQueue — review Cook County prospect feeder candidates before import.
 */
import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Link,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ProspectAreaFilterPanel } from '@/components/ProspectAreaFilterPanel'
import { ProspectMotivationDetailDrawer } from '@/components/ProspectMotivationDetailDrawer'
import { useGoogleMapsLoaded } from '@/context/GoogleMapsContext'
import { prospectService } from '@/services/api'
import type { ProspectCandidate } from '@/types'
import { computeTotalPages, clampPage } from '@/utils/pagination'
import { formatDateTime } from '@/utils/formatters'
import {
  PROSPECT_SIGNAL_LABELS,
  formatProspectAddressLines,
  formatProspectMotivationPct,
  prospectSignalLabel,
  sortedProspectSignals,
} from '@/utils/prospectMotivation'

/** Nightly Celery schedule: 4:00 AM UTC ≈ 11:00 PM Central (previous calendar day). */
const FEED_SCHEDULE_LABEL = '11:00 PM Central (nightly)'

const MOTIVATION_TOOLTIP =
  'Distress signal strength as a percentage (0–100%). Signals from multiple feeds stack by PIN ' +
  '(e.g. tax sale + violation). Violations and similar signals decay with age (100% through 90 days). ' +
  'Only prospects at 60% or higher with a resolved street address appear here. ' +
  'This is not the same as lead score after import.'

function signalLabel(candidate: ProspectCandidate): string {
  const top = sortedProspectSignals(candidate)[0]
  if (top) return prospectSignalLabel(top)
  return PROSPECT_SIGNAL_LABELS[candidate.primary_signal_type] ?? candidate.primary_signal_type
}

export function ProspectReviewQueue() {
  const queryClient = useQueryClient()
  const mapsLoaded = useGoogleMapsLoaded()
  const [page, setPage] = useState(1)
  const [selectedCandidate, setSelectedCandidate] = useState<ProspectCandidate | null>(null)
  const perPage = 20

  const { data: areaFilterConfig } = useQuery({
    queryKey: ['prospect-area-filter'],
    queryFn: () => prospectService.getAreaFilter(),
  })

  const { data: feedStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['prospect-feed-status'],
    queryFn: () => prospectService.getStatus(),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['prospect-candidates', page],
    queryFn: () => prospectService.getCandidates(page, perPage, 'pending'),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

  const [actionError, setActionError] = useState<string | null>(null)

  const approveMutation = useMutation({
    mutationFn: (id: number) => prospectService.approveCandidate(id),
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['prospect-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    },
    onError: () => {
      setActionError('Failed to approve prospect. Try again.')
    },
  })

  const rejectMutation = useMutation({
    mutationFn: (id: number) => prospectService.rejectCandidate(id),
    onSuccess: () => {
      setActionError(null)
      queryClient.invalidateQueries({ queryKey: ['prospect-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    },
    onError: () => {
      setActionError('Failed to reject prospect. Try again.')
    },
  })

  const syncMutation = useMutation({
    mutationFn: () => prospectService.syncFeeds(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prospect-candidates'] })
      queryClient.invalidateQueries({ queryKey: ['prospect-feed-status'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
      refetchStatus()
    },
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const areaFilterStats = data?.area_filter
  const totalPages = computeTotalPages(total, perPage)
  const lastSyncedAt = syncMutation.data?.last_sync_at ?? feedStatus?.last_sync_at

  if (isLoading && rows.length === 0) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box data-testid="prospect-review-queue" sx={{ p: 2 }}>
      <Typography variant="h5" component="h1" gutterBottom>
        Prospect Review Queue
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Cook County distress signals stacked by PIN with a resolved address and at least 60%
        motivation. Approve to create a lead and run enrichment. Scheduled pull:{' '}
        {FEED_SCHEDULE_LABEL}.
      </Typography>

      {feedStatus?.chicago_api_configured === false && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Chicago feeds run without an app token (lower rate limits). For higher limits, add a
          Socrata <strong>App Token</strong> (not OAuth key/secret) as{' '}
          <code>CHICAGO_DATA_API_KEY</code> — create one at{' '}
          <Link href="https://data.cityofchicago.org/profile/app_tokens" target="_blank" rel="noopener">
            data.cityofchicago.org/profile/app_tokens
          </Link>
          .
        </Alert>
      )}

      <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <Button
          variant="outlined"
          size="small"
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
        >
          {syncMutation.isPending ? 'Syncing feeds…' : 'Sync feeds now'}
        </Button>
        {lastSyncedAt && (
          <Typography variant="body2" color="text.secondary" data-testid="prospect-last-synced">
            Last synced: {formatDateTime(lastSyncedAt)}
          </Typography>
        )}
        {syncMutation.isError && (
          <Typography variant="body2" color="error">
            Feed sync failed. Try again in a moment.
          </Typography>
        )}
        {syncMutation.isSuccess && (
          <Typography variant="body2" color="text.secondary">
            Sync complete — {syncMutation.data?.prospect_candidates ?? 0} pending in your queue.
          </Typography>
        )}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} action={<Button onClick={() => refetch()}>Retry</Button>}>
          Failed to load prospect candidates.
        </Alert>
      )}

      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <ProspectAreaFilterPanel
        mapsLoaded={mapsLoaded}
        config={areaFilterConfig}
        filterStats={areaFilterStats}
        onChanged={() => {
          queryClient.invalidateQueries({ queryKey: ['prospect-candidates'] })
        }}
      />

      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Address</TableCell>
              <TableCell>PIN</TableCell>
              <TableCell>Signal</TableCell>
              <TableCell align="right">
                <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                  Motivation
                  <Tooltip title={MOTIVATION_TOOLTIP} arrow>
                    <InfoOutlinedIcon sx={{ fontSize: 16, color: 'text.disabled', cursor: 'help' }} />
                  </Tooltip>
                </Box>
              </TableCell>
              <TableCell>Feed</TableCell>
              <TableCell>Detected</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7}>
                  <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
                    {areaFilterStats?.filter_enabled &&
                    (areaFilterStats.total_unfiltered ?? 0) > 0 &&
                    total === 0
                      ? `No prospects in your target area (${areaFilterStats.total_unfiltered} total qualify county-wide). Adjust or disable the area filter above.`
                      : 'No qualifying prospects yet. Sync pulls Cook County feeds, stacks signals by PIN, resolves addresses, and only admits properties at 60% motivation or higher with a street address.'}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const address = formatProspectAddressLines(row)
                return (
                  <TableRow
                    key={row.id}
                    hover
                    tabIndex={0}
                    role="button"
                    aria-label={`View motivation details for ${address.primary}`}
                    onClick={() => setSelectedCandidate(row)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelectedCandidate(row)
                      }
                    }}
                    sx={{ cursor: 'pointer' }}
                    selected={selectedCandidate?.id === row.id}
                  >
                    <TableCell>
                      <Typography variant="body2">{address.primary}</Typography>
                      {address.secondary && (
                        <Typography variant="caption" color="text.secondary" display="block">
                          {address.secondary}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>{row.pin ?? '—'}</TableCell>
                    <TableCell>
                      <Chip size="small" label={signalLabel(row)} color="warning" variant="outlined" />
                    </TableCell>
                    <TableCell align="right">
                      <Typography
                        component="span"
                        variant="body2"
                        sx={{ color: 'primary.main', textDecoration: 'underline', textUnderlineOffset: 3 }}
                      >
                        {formatProspectMotivationPct(row)}
                      </Typography>
                    </TableCell>
                    <TableCell>{row.source_feed}</TableCell>
                    <TableCell>
                      {formatDateTime(row.created_at)}
                    </TableCell>
                    <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                      <Button
                        size="small"
                        color="success"
                        startIcon={<CheckIcon />}
                        disabled={approveMutation.isPending}
                        onClick={() => approveMutation.mutate(row.id)}
                        sx={{ mr: 1 }}
                      >
                        Approve
                      </Button>
                      <Button
                        size="small"
                        color="inherit"
                        startIcon={<CloseIcon />}
                        disabled={rejectMutation.isPending}
                        onClick={() => rejectMutation.mutate(row.id)}
                      >
                        Reject
                      </Button>
                      {row.imported_lead_id && (
                        <Link component={RouterLink} to={`/leads/${row.imported_lead_id}`} sx={{ ml: 1 }}>
                          View lead
                        </Link>
                      )}
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <ProspectMotivationDetailDrawer
        candidate={selectedCandidate}
        open={selectedCandidate != null}
        onClose={() => setSelectedCandidate(null)}
      />

      {totalPages > 1 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', gap: 1, mt: 2 }}>
          <Button disabled={page <= 1} onClick={() => setPage((p) => clampPage(p - 1, totalPages))}>
            Previous
          </Button>
          <Typography variant="body2" sx={{ alignSelf: 'center' }}>
            Page {page} of {totalPages} ({total} total)
          </Typography>
          <Button disabled={page >= totalPages} onClick={() => setPage((p) => clampPage(p + 1, totalPages))}>
            Next
          </Button>
        </Box>
      )}
    </Box>
  )
}

export default ProspectReviewQueue
