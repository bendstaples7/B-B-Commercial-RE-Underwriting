import React, { useState, useEffect } from 'react'
import {
  Box,
  Paper,
  Typography,
  Tabs,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableRow,
  TableHead,
  Button,
  Chip,
  CircularProgress,
  Alert,
  Divider,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import { useQuery } from '@tanstack/react-query'
import type {
  LeadDetail,
  EnrichmentRecord,
  LeadMarketingListMembership,
  LeadScoreResponse,
} from '@/types'
import { leadService } from '@/services/leadApi'
import { leadScoreService } from '@/services/api'
import { LeadScoreBadge } from '@/components/LeadScoreBadge'
import { ScoreBreakdownCard } from '@/components/ScoreBreakdownCard'
import { ScoreHistoryTimeline } from '@/components/ScoreHistoryTimeline'
import { RecalculateButton } from '@/components/RecalculateButton'
import { ScoreLegend } from '@/components/ScoreLegend'

/** Props accepted by LeadDetailPage. */
export interface LeadDetailPageProps {
  /** The lead ID to display. */
  leadId: number
  /** Called when the user clicks the back button. */
  onBack?: () => void
  /** Called when an analysis session is started, with the new session ID. */
  onAnalysisStarted?: (sessionId: string) => void
}

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

const TabPanel: React.FC<TabPanelProps> = ({ children, value, index }) => (
  <Box
    role="tabpanel"
    hidden={value !== index}
    id={`lead-tabpanel-${index}`}
    aria-labelledby={`lead-tab-${index}`}
    sx={{ py: 2 }}
  >
    {value === index && children}
  </Box>
)

function a11yTabProps(index: number) {
  return {
    id: `lead-tab-${index}`,
    'aria-controls': `lead-tabpanel-${index}`,
  }
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

const formatDate = (dateStr: string | null | undefined): string => {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return '—'
  }
}

const formatDateTime = (dateStr: string | null | undefined): string => {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return '—'
  }
}

const getScoreColor = (score: number): 'success' | 'warning' | 'error' | 'default' => {
  if (score >= 70) return 'success'
  if (score >= 40) return 'warning'
  if (score > 0) return 'error'
  return 'default'
}

const getEnrichmentStatusColor = (
  status: string,
): 'success' | 'error' | 'warning' | 'default' => {
  switch (status) {
    case 'success':
      return 'success'
    case 'failed':
      return 'error'
    case 'pending':
      return 'warning'
    case 'no_results':
      return 'default'
    default:
      return 'default'
  }
}

const getOutreachStatusColor = (
  status: string,
): 'success' | 'info' | 'warning' | 'error' | 'default' => {
  switch (status) {
    case 'converted':
      return 'success'
    case 'responded':
      return 'info'
    case 'contacted':
      return 'warning'
    case 'opted_out':
      return 'error'
    default:
      return 'default'
  }
}

const outreachStatusLabel = (status: string): string =>
  status
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')

// ---------------------------------------------------------------------------
// Sub-components for each tab
// ---------------------------------------------------------------------------

/** Info tab — all lead fields grouped by category. */
const InfoTab: React.FC<{ lead: LeadDetail }> = ({ lead }) => {
  const fieldGroup = (title: string, fields: [string, string | number | null | undefined][]) => (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
        {title}
      </Typography>
      <TableContainer>
        <Table size="small" aria-label={`${title} fields`}>
          <TableBody>
            {fields.map(([label, value]) => (
              <TableRow key={label}>
                <TableCell sx={{ width: '40%', color: 'text.secondary' }}>{label}</TableCell>
                <TableCell>{value ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )

  return (
    <>
      {fieldGroup('Property Details', [
        ['Street', lead.property_street],
        ['City', lead.property_city],
        ['State', lead.property_state],
        ['Zip Code', lead.property_zip],
        ['Property Type', lead.property_type],
        ['Bedrooms', lead.bedrooms],
        ['Bathrooms', lead.bathrooms],
        ['Square Footage', lead.square_footage?.toLocaleString()],
        ['Lot Size', lead.lot_size?.toLocaleString()],
        ['Year Built', lead.year_built],
        ['Units', lead.units],
        ['Units Allowed', lead.units_allowed],
        ['Zoning', lead.zoning],
        ['County Assessor PIN', lead.county_assessor_pin],
        ['Tax Bill 2021', lead.tax_bill_2021 != null ? `$${lead.tax_bill_2021.toLocaleString()}` : null],
        ['Most Recent Sale', lead.most_recent_sale],
      ])}
      {fieldGroup('Owner Information', [
        ['Owner First Name', lead.owner_first_name],
        ['Owner Last Name', lead.owner_last_name],
        ['Ownership Type', lead.ownership_type],
        ['Acquisition Date', formatDate(lead.acquisition_date)],
        ['Owner 2 First Name', lead.owner_2_first_name],
        ['Owner 2 Last Name', lead.owner_2_last_name],
      ])}
      {fieldGroup('Contact Information', [
        ['Phone 1', lead.phone_1],
        ['Phone 2', lead.phone_2],
        ['Phone 3', lead.phone_3],
        ['Phone 4', lead.phone_4],
        ['Phone 5', lead.phone_5],
        ['Phone 6', lead.phone_6],
        ['Phone 7', lead.phone_7],
        ['Email 1', lead.email_1],
        ['Email 2', lead.email_2],
        ['Email 3', lead.email_3],
        ['Email 4', lead.email_4],
        ['Email 5', lead.email_5],
        ['Socials', lead.socials],
      ])}
      {fieldGroup('Mailing Information', [
        ['Mailing Address', lead.mailing_address],
        ['City', lead.mailing_city],
        ['State', lead.mailing_state],
        ['Zip Code', lead.mailing_zip],
        ['Address 2', lead.address_2],
        ['Returned Addresses', lead.returned_addresses],
      ])}
      {fieldGroup('Research & Tracking', [
        ['Source', lead.source],
        ['Date Identified', formatDate(lead.date_identified)],
        ['Notes', lead.notes],
        ['Needs Skip Trace', lead.needs_skip_trace != null ? (lead.needs_skip_trace ? 'Yes' : 'No') : null],
        ['Skip Tracer', lead.skip_tracer],
        ['Date Skip Traced', formatDate(lead.date_skip_traced)],
        ['Date Added to HubSpot', formatDate(lead.date_added_to_hubspot)],
      ])}
      {fieldGroup('Mailing Campaigns', [
        ['Up Next to Mail', lead.up_next_to_mail != null ? (lead.up_next_to_mail ? 'Yes' : 'No') : null],
        ['Mailer History', lead.mailer_history ? JSON.stringify(lead.mailer_history) : null],
      ])}
      {fieldGroup('Metadata', [
        ['Data Source', lead.data_source],
        ['Created', formatDateTime(lead.created_at)],
        ['Updated', formatDateTime(lead.updated_at)],
      ])}
    </>
  )
}

/**
 * Score tab — new deterministic lead-score UI.
 *
 * Fetches `/api/lead-scores/:leadId` via React Query. When a score record
 * exists we render the full `ScoreBreakdownCard` plus a
 * `ScoreHistoryTimeline` of past records. When no score record exists yet
 * we show a "Not scored" empty state. The single-lead `RecalculateButton`
 * is always rendered so the user can trigger a (re)calculation from any
 * state. A successful recalculation invalidates the query cache, which
 * triggers a refetch and replaces the empty state with real data.
 *
 * Satisfies Requirements 11.1, 11.2, 11.3, 11.4, 11.5.
 */
const ScoreTab: React.FC<{ leadId: number }> = ({ leadId }) => {
  const { data, isLoading, error } = useQuery<LeadScoreResponse>({
    queryKey: ['leadScore', leadId],
    queryFn: async () => {
      const response = await leadScoreService.getLeadScore(leadId)
      return response.data
    },
  })

  return (
    <Box>
      <Box sx={{ mb: 2, display: 'flex', justifyContent: 'flex-end' }}>
        <RecalculateButton mode="single" leadId={leadId} />
      </Box>

      <Box sx={{ mb: 2 }}>
        <ScoreLegend />
      </Box>

      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={32} aria-label="Loading score" />
        </Box>
      )}

      {error && !isLoading && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert">
          {error instanceof Error ? error.message : 'Failed to load score.'}
        </Alert>
      )}

      {!isLoading && !error && data && !data.latest && (
        <Alert severity="info" sx={{ mb: 2 }}>
          This lead has not been scored yet. Use the Recalculate button above
          to generate the first score.
        </Alert>
      )}

      {!isLoading && !error && data?.latest && (
        <>
          <Box sx={{ mb: 2 }}>
            <ScoreBreakdownCard score={data.latest} />
          </Box>
          <ScoreHistoryTimeline history={data.history} />
        </>
      )}
    </Box>
  )
}

/** Enrichment tab — list of enrichment records with source attribution. */
const EnrichmentTab: React.FC<{ records: EnrichmentRecord[] }> = ({ records }) => {
  if (records.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No enrichment records yet. Use the Enrich action to pull data from external sources.
      </Typography>
    )
  }

  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label="Enrichment records">
        <TableHead>
          <TableRow>
            <TableCell sx={{ fontWeight: 'bold' }}>Source</TableCell>
            <TableCell sx={{ fontWeight: 'bold' }}>Status</TableCell>
            <TableCell sx={{ fontWeight: 'bold' }}>Date</TableCell>
            <TableCell sx={{ fontWeight: 'bold' }}>Details</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {records.map((rec) => (
            <TableRow key={rec.id}>
              <TableCell>{rec.data_source_name || `Source #${rec.data_source_id}`}</TableCell>
              <TableCell>
                <Chip
                  label={rec.status}
                  size="small"
                  color={getEnrichmentStatusColor(rec.status)}
                />
              </TableCell>
              <TableCell>{formatDateTime(rec.created_at)}</TableCell>
              <TableCell>
                {rec.status === 'success' && rec.retrieved_data
                  ? `${Object.keys(rec.retrieved_data).length} field(s) enriched`
                  : rec.error_reason || '—'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

/** Marketing tab — list memberships and outreach status. */
const MarketingTab: React.FC<{ memberships: LeadMarketingListMembership[] }> = ({
  memberships,
}) => {
  if (memberships.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        This lead is not a member of any marketing lists.
      </Typography>
    )
  }

  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small" aria-label="Marketing list memberships">
        <TableHead>
          <TableRow>
            <TableCell sx={{ fontWeight: 'bold' }}>List</TableCell>
            <TableCell sx={{ fontWeight: 'bold' }}>Outreach Status</TableCell>
            <TableCell sx={{ fontWeight: 'bold' }}>Added</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {memberships.map((m) => (
            <TableRow key={m.marketing_list_id}>
              <TableCell>{m.marketing_list_name || `List #${m.marketing_list_id}`}</TableCell>
              <TableCell>
                <Chip
                  label={outreachStatusLabel(m.outreach_status)}
                  size="small"
                  color={getOutreachStatusColor(m.outreach_status)}
                />
              </TableCell>
              <TableCell>{formatDateTime(m.added_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

/** Analysis tab — linked analysis session info or start-analysis button. */
const AnalysisTab: React.FC<{
  lead: LeadDetail
  onStartAnalysis: () => void
  analysisLoading: boolean
}> = ({ lead, onStartAnalysis, analysisLoading }) => {
  const session = lead.analysis_session

  if (!session) {
    return (
      <Box sx={{ textAlign: 'center', py: 4 }}>
        <Typography variant="body1" gutterBottom>
          No analysis has been started for this lead yet.
        </Typography>
        <Button
          variant="contained"
          startIcon={analysisLoading ? <CircularProgress size={18} /> : <PlayArrowIcon />}
          onClick={onStartAnalysis}
          disabled={analysisLoading}
          aria-label="Start analysis from this lead"
          sx={{ mt: 1 }}
        >
          Start Analysis
        </Button>
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
        Linked Analysis Session
      </Typography>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="Analysis session details">
          <TableBody>
            <TableRow>
              <TableCell sx={{ width: '40%', color: 'text.secondary' }}>Session ID</TableCell>
              <TableCell>{session.session_id}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ color: 'text.secondary' }}>Current Step</TableCell>
              <TableCell>{session.current_step}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ color: 'text.secondary' }}>Created</TableCell>
              <TableCell>{formatDateTime(session.created_at)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell sx={{ color: 'text.secondary' }}>Updated</TableCell>
              <TableCell>{formatDateTime(session.updated_at)}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * Full lead detail view with tabbed sections: Info, Score, Enrichment,
 * Marketing, and Analysis.
 *
 * Requirements: 5.5, 6.5, 9.1, 9.3
 */
export const LeadDetailPage: React.FC<LeadDetailPageProps> = ({
  leadId,
  onBack,
  onAnalysisStarted,
}) => {
  const [lead, setLead] = useState<LeadDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tabIndex, setTabIndex] = useState(0)
  const [analysisLoading, setAnalysisLoading] = useState(false)

  // Fetch the latest score record so the header can show the current tier.
  // The ScoreTab component also reads this cache key, so both stay in sync.
  const { data: scoreData } = useQuery<LeadScoreResponse>({
    queryKey: ['leadScore', leadId],
    queryFn: async () => {
      const response = await leadScoreService.getLeadScore(leadId)
      return response.data
    },
  })

  // Fetch lead detail
  useEffect(() => {
    let cancelled = false
    const fetchLead = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await leadService.getLeadDetail(leadId)
        if (!cancelled) setLead(data)
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Failed to load lead details.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchLead()
    return () => {
      cancelled = true
    }
  }, [leadId])

  // Start analysis from lead
  const handleStartAnalysis = async () => {
    setAnalysisLoading(true)
    try {
      const result = await leadService.analyzeLead(leadId)
      // Refresh lead detail to show linked session
      const updated = await leadService.getLeadDetail(leadId)
      setLead(updated)
      onAnalysisStarted?.(result.session_id)
    } catch (err: any) {
      setError(err.message || 'Failed to start analysis.')
    } finally {
      setAnalysisLoading(false)
    }
  }

  // Loading state
  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress aria-label="Loading lead details" />
      </Box>
    )
  }

  // Error state
  if (error && !lead) {
    return (
      <Box sx={{ px: { xs: 1, sm: 2 } }}>
        {onBack && (
          <Button startIcon={<ArrowBackIcon />} onClick={onBack} sx={{ mb: 2 }}>
            Back to Leads
          </Button>
        )}
        <Alert severity="error" role="alert">
          {error}
        </Alert>
      </Box>
    )
  }

  if (!lead) return null

  return (
    <Box component="section" aria-labelledby="lead-detail-heading" sx={{ px: { xs: 1, sm: 2 } }}>
      {/* Header */}
      <Box sx={{ mb: 2 }}>
        {onBack && (
          <Button startIcon={<ArrowBackIcon />} onClick={onBack} sx={{ mb: 1 }}>
            Back to Leads
          </Button>
        )}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <Typography variant="h5" id="lead-detail-heading" component="h2">
            {lead.property_street}
          </Typography>
          {scoreData?.latest ? (
            <>
              <Chip
                label={`Score: ${Math.round(scoreData.latest.total_score)}`}
                size="medium"
              />
              <LeadScoreBadge tier={scoreData.latest.score_tier} size="medium" />
            </>
          ) : (
            <Chip
              label={`Score: ${lead.lead_score.toFixed(1)}`}
              color={getScoreColor(lead.lead_score)}
              size="medium"
            />
          )}
        </Box>
        <Typography variant="body2" color="text.secondary">
          Owner: {lead.owner_first_name} {lead.owner_last_name}
          {lead.property_type ? ` · ${lead.property_type}` : ''}
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert">
          {error}
        </Alert>
      )}

      {/* Tabs */}
      <Paper sx={{ px: { xs: 1, sm: 2 } }}>
        <Tabs
          value={tabIndex}
          onChange={(_e, newValue) => setTabIndex(newValue)}
          variant="scrollable"
          scrollButtons="auto"
          aria-label="Lead detail tabs"
        >
          <Tab label="Info" {...a11yTabProps(0)} />
          <Tab label="Score" {...a11yTabProps(1)} />
          <Tab label="Enrichment" {...a11yTabProps(2)} />
          <Tab label="Marketing" {...a11yTabProps(3)} />
          <Tab label="Analysis" {...a11yTabProps(4)} />
        </Tabs>
        <Divider />

        <TabPanel value={tabIndex} index={0}>
          <InfoTab lead={lead} />
        </TabPanel>

        <TabPanel value={tabIndex} index={1}>
          <ScoreTab leadId={lead.id} />
        </TabPanel>

        <TabPanel value={tabIndex} index={2}>
          <EnrichmentTab records={lead.enrichment_records || []} />
        </TabPanel>

        <TabPanel value={tabIndex} index={3}>
          <MarketingTab memberships={lead.marketing_lists || []} />
        </TabPanel>

        <TabPanel value={tabIndex} index={4}>
          <AnalysisTab
            lead={lead}
            onStartAnalysis={handleStartAnalysis}
            analysisLoading={analysisLoading}
          />
        </TabPanel>
      </Paper>
    </Box>
  )
}
