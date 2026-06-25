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
import HomeWorkIcon from '@mui/icons-material/HomeWork'
import ApartmentIcon from '@mui/icons-material/Apartment'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import type {
  PropertyDetail,
  EnrichmentRecord,
  PropertyMarketingListMembership,
  PropertyScoreResponse,
} from '@/types'
import { leadService } from '@/services/leadApi'
import { multifamilyService, leadScoreService, commandCenterService, leadTaskService } from '@/services/api'
import { LeadScoreBadge } from '@/components/LeadScoreBadge'
import { ScoreBreakdownCard } from '@/components/ScoreBreakdownCard'
import { ScoreHistoryTimeline } from '@/components/ScoreHistoryTimeline'
import { RecalculateButton } from '@/components/RecalculateButton'
import { ScoreLegend } from '@/components/ScoreLegend'
import { ContactsSection } from '@/components/ContactsSection'
import { LeadTaskList } from '@/components/LeadTaskList'
import { LeadTimeline } from '@/components/LeadTimeline'
import { LogNoteForm } from '@/components/LogNoteForm'
import { LogCallForm } from '@/components/LogCallForm'
import type { LeadTask, LeadTimelineEntry } from '@/types'
import { formatPhoneNumber, phoneTelHref } from '@/utils/phone'

/** Props accepted by PropertyDetailPage. */
export interface PropertyDetailPageProps {
  /** The property (lead) ID to display. */
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
    id={`property-tabpanel-${index}`}
    aria-labelledby={`property-tab-${index}`}
    sx={{ py: 2 }}
  >
    {value === index && children}
  </Box>
)

function a11yTabProps(index: number) {
  return {
    id: `property-tab-${index}`,
    'aria-controls': `property-tabpanel-${index}`,
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

/** Info tab — all property fields grouped by category. */
const InfoTab: React.FC<{ lead: PropertyDetail }> = ({ lead }) => {
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

  const contacts = lead.contacts ?? []

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

      {/* Contacts — all linked contacts, primary first */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
          Contacts
        </Typography>
        {contacts.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No contacts linked. Use the Contacts tab to add one.
          </Typography>
        ) : (
          <TableContainer>
            <Table size="small" aria-label="Contacts">
              <TableBody>
                {contacts.map((c) => {
                  const name = [c.first_name, c.last_name].filter(Boolean).join(' ') || '(No name)'
                  const role = c.role.split('_').map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
                  const phone = c.phones[0]?.value ?? null
                  const email = c.emails[0]?.value ?? null
                  return (
                    <TableRow key={c.id}>
                      <TableCell sx={{ width: '40%', color: 'text.secondary' }}>
                        {name}
                        {c.is_primary && (
                          <Typography component="span" variant="caption" sx={{ ml: 1, color: 'primary.main' }}>
                            Primary
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        {role}
                        {phone && ` · ${phone}`}
                        {email && ` · ${email}`}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Box>
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

/** Score tab — deterministic property-score UI. */
const ScoreTab: React.FC<{ leadId: number }> = ({ leadId }) => {
  const { data, isLoading, error } = useQuery<PropertyScoreResponse>({
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
          This property has not been scored yet. Use the Recalculate button above
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
const MarketingTab: React.FC<{ memberships: PropertyMarketingListMembership[] }> = ({
  memberships,
}) => {
  if (memberships.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        This property is not a member of any marketing lists.
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
  lead: PropertyDetail
  onStartSingleFamily: () => void
  onStartMultifamily: () => void
  analysisLoading: boolean
  multifamilyLoading: boolean
}> = ({ lead, onStartSingleFamily, onStartMultifamily, analysisLoading, multifamilyLoading }) => {
  const session = lead.analysis_session
  const units = lead.units

  const showMultifamily = units !== null && units >= 5
  const showSingleFamily = units === null || units < 5
  const showBoth = units === null

  if (!session) {
    return (
      <Box sx={{ textAlign: 'center', py: 4 }}>
        <Typography variant="body1" gutterBottom>
          No analysis has been started for this property yet.
        </Typography>

        {showBoth && (
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', mt: 2, flexWrap: 'wrap' }}>
            <Button
              variant="outlined"
              startIcon={analysisLoading ? <CircularProgress size={18} /> : <HomeWorkIcon />}
              onClick={onStartSingleFamily}
              disabled={analysisLoading || multifamilyLoading}
              aria-label="Start single-family analysis from this property"
            >
              Start Single-Family Analysis
            </Button>
            <Button
              variant="contained"
              startIcon={multifamilyLoading ? <CircularProgress size={18} /> : <ApartmentIcon />}
              onClick={onStartMultifamily}
              disabled={analysisLoading || multifamilyLoading}
              aria-label="Start multifamily analysis from this property"
            >
              Start Multifamily Analysis
            </Button>
          </Box>
        )}

        {showSingleFamily && !showBoth && (
          <Button
            variant="contained"
            startIcon={analysisLoading ? <CircularProgress size={18} /> : <HomeWorkIcon />}
            onClick={onStartSingleFamily}
            disabled={analysisLoading}
            aria-label="Start single-family analysis from this property"
            sx={{ mt: 1 }}
          >
            Start Single-Family Analysis
          </Button>
        )}

        {showMultifamily && !showBoth && (
          <Button
            variant="contained"
            startIcon={multifamilyLoading ? <CircularProgress size={18} /> : <ApartmentIcon />}
            onClick={onStartMultifamily}
            disabled={multifamilyLoading}
            aria-label="Start multifamily analysis from this property"
            sx={{ mt: 1 }}
          >
            Start Multifamily Analysis
          </Button>
        )}
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

// ---------------------------------------------------------------------------
// Activity tab — timeline + log note/call, mirrors HubSpot center panel
// ---------------------------------------------------------------------------

const ActivityTab: React.FC<{ leadId: number; ccData: any }> = ({ leadId, ccData }) => {
  const [entries, setEntries] = useState<LeadTimelineEntry[]>([])
  const [total, setTotal] = useState(0)

  // Populate from the shared command-center data when it arrives
  useEffect(() => {
    if (ccData) {
      setEntries(ccData.timeline?.entries || [])
      setTotal(ccData.timeline?.total || 0)
    }
  }, [ccData])

  const handleEntrySaved = (entry: LeadTimelineEntry) => {
    setEntries((prev) => [entry, ...prev])
    setTotal((prev) => prev + 1)
  }

  const handleLoadMore = async (page: number) => {
    const result = await commandCenterService.getTimeline(leadId, page)
    return { entries: result.entries, total: result.total }
  }

  if (!ccData) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={32} aria-label="Loading activity" />
      </Box>
    )
  }

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="subtitle2" fontWeight="bold" gutterBottom>Log Note</Typography>
        <LogNoteForm leadId={leadId} onSaved={handleEntrySaved} />
      </Box>
      <Divider sx={{ mb: 3 }} />
      <Box sx={{ mb: 3 }}>
        <Typography variant="subtitle2" fontWeight="bold" gutterBottom>Log Call</Typography>
        <LogCallForm leadId={leadId} onSaved={handleEntrySaved} />
      </Box>
      <Divider sx={{ mb: 2 }} />
      <LeadTimeline
        leadId={leadId}
        initialEntries={entries}
        initialTotal={total}
        onLoadMore={handleLoadMore}
      />
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Tasks panel — always-visible right sidebar
// ---------------------------------------------------------------------------

const TasksTab: React.FC<{ leadId: number; ccData: any }> = ({ leadId, ccData }) => {
  const queryClient = useQueryClient()
  const [tasks, setTasks] = useState<LeadTask[]>([])
  // Use a ref to always access the latest tasks snapshot in the async handler,
  // preventing stale closure race conditions when multiple tasks complete rapidly.
  const tasksRef = React.useRef<LeadTask[]>([])

  useEffect(() => {
    if (ccData) {
      const initial = ccData.open_tasks || []
      setTasks(initial)
      tasksRef.current = initial
    }
  }, [ccData])

  if (!ccData) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={32} aria-label="Loading tasks" />
      </Box>
    )
  }

  return (
    <LeadTaskList
      leadId={leadId}
      tasks={tasks}
      recommendedAction={null}
      onTaskCreated={(task) => {
        const updated = [...tasksRef.current, task]
        tasksRef.current = updated
        setTasks(updated)
      }}
      onTaskCompleted={async (taskId) => {
        if (typeof taskId !== 'number') return
        const previous = tasksRef.current
        const updated = previous.filter((t) => t.id !== taskId)
        tasksRef.current = updated
        setTasks(updated)
        try {
          await leadTaskService.completeTask(leadId, taskId)
          queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        } catch (err) {
          // Restore the snapshot that was current when this call started
          tasksRef.current = previous
          setTasks(previous)
          console.error('[PropertyDetailPage] completeTask failed:', err)
        }
      }}
    />
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * Full property detail view with tabbed sections: Info, Score, Enrichment,
 * Marketing, Analysis, Contacts, and Tasks.
 */
export const PropertyDetailPage: React.FC<PropertyDetailPageProps> = ({
  leadId,
  onBack,
  onAnalysisStarted,
}) => {
  const navigate = useNavigate()
  const [lead, setLead] = useState<PropertyDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tabIndex, setTabIndex] = useState(0)
  const [analysisLoading, setAnalysisLoading] = useState(false)

  // Shared command-center data — used by both ActivityTab and TasksTab to
  // avoid two separate fetches on the same endpoint when the page mounts.
  const { data: ccData } = useQuery({
    queryKey: ['commandCenter', leadId],
    queryFn: () => commandCenterService.getCommandCenter(leadId),
    staleTime: 0,
    refetchOnMount: 'always',
  })

  const { data: scoreData } = useQuery<PropertyScoreResponse>({
    queryKey: ['leadScore', leadId],
    queryFn: async () => {
      const response = await leadScoreService.getLeadScore(leadId)
      return response.data
    },
  })

  useEffect(() => {
    let cancelled = false
    const fetchLead = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await leadService.getLeadDetail(leadId)
        if (!cancelled) setLead(data)
      } catch (err: any) {
        if (!cancelled) setError(err.message || 'Failed to load property details.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchLead()
    return () => {
      cancelled = true
    }
  }, [leadId])

  const handleStartSingleFamily = async () => {
    setAnalysisLoading(true)
    try {
      const result = await leadService.analyzeLead(leadId)
      const updated = await leadService.getLeadDetail(leadId)
      setLead(updated)
      onAnalysisStarted?.(result.session_id)
    } catch (err: any) {
      setError(err.message || 'Failed to start analysis.')
    } finally {
      setAnalysisLoading(false)
    }
  }

  const multifamilyMutation = useMutation({
    mutationFn: async () => {
      if (!lead) throw new Error('Property not loaded')
      const deal = await multifamilyService.createDeal({
        property_address: lead.property_street,
        unit_count: lead.units ?? 5,
        purchase_price: 0,
        close_date: new Date().toISOString().split('T')[0],
      })
      await multifamilyService.linkDealToLead(deal.id, lead.id)
      return deal
    },
    onSuccess: (deal) => {
      onAnalysisStarted?.(String(deal.id))
      navigate(`/multifamily/deals/${deal.id}`)
    },
    onError: (err: any) => {
      setError(err.message || 'Failed to start multifamily analysis.')
    },
  })

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress aria-label="Loading property details" />
      </Box>
    )
  }

  if (error && !lead) {
    return (
      <Box sx={{ px: { xs: 1, sm: 2 } }}>
        {onBack && (
          <Button startIcon={<ArrowBackIcon />} onClick={onBack} sx={{ mb: 2 }}>
            Back to Properties
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
    <Box component="section" aria-labelledby="property-detail-heading" sx={{ px: { xs: 1, sm: 2 } }}>
      {/* Header */}
      <Box sx={{ mb: 2 }}>
        {onBack && (
          <Button startIcon={<ArrowBackIcon />} onClick={onBack} sx={{ mb: 1 }}>
            Back to Properties
          </Button>
        )}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <Typography variant="h5" id="property-detail-heading" component="h2">
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
          {(() => {
            const primary = lead.contacts?.find((c) => c.is_primary)
            const name = primary
              ? [primary.first_name, primary.last_name].filter(Boolean).join(' ')
              : null
            return name ? `Primary contact: ${name}` : 'No primary contact set'
          })()}
          {lead.property_type ? ` · ${lead.property_type}` : ''}
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert">
          {error}
        </Alert>
      )}

      {/* Two-column layout: tabbed content + sticky right panel */}
      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>

        {/* Main tabbed content */}
        <Paper sx={{ flex: 1, minWidth: 0, px: { xs: 1, sm: 2 } }}>
          <Tabs
            value={tabIndex}
            onChange={(_e, newValue) => setTabIndex(newValue)}
            variant="scrollable"
            scrollButtons="auto"
            aria-label="Property detail tabs"
          >
            <Tab label="Activity" {...a11yTabProps(0)} />
            <Tab label="Info" {...a11yTabProps(1)} />
            <Tab label="Score" {...a11yTabProps(2)} />
            <Tab label="Enrichment" {...a11yTabProps(3)} />
            <Tab label="Marketing" {...a11yTabProps(4)} />
            <Tab label="Analysis" {...a11yTabProps(5)} />
            <Tab label="Contacts" {...a11yTabProps(6)} />
          </Tabs>
          <Divider />

          <TabPanel value={tabIndex} index={0}>
            <ActivityTab leadId={lead.id} ccData={ccData} />
          </TabPanel>

          <TabPanel value={tabIndex} index={1}>
            <InfoTab lead={lead} />
          </TabPanel>

          <TabPanel value={tabIndex} index={2}>
            <ScoreTab leadId={lead.id} />
          </TabPanel>

          <TabPanel value={tabIndex} index={3}>
            <EnrichmentTab records={lead.enrichment_records || []} />
          </TabPanel>

          <TabPanel value={tabIndex} index={4}>
            <MarketingTab memberships={lead.marketing_lists || []} />
          </TabPanel>

          <TabPanel value={tabIndex} index={5}>
            <AnalysisTab
              lead={lead}
              onStartSingleFamily={handleStartSingleFamily}
              onStartMultifamily={() => multifamilyMutation.mutate()}
              analysisLoading={analysisLoading}
              multifamilyLoading={multifamilyMutation.isPending}
            />
          </TabPanel>

          <TabPanel value={tabIndex} index={6}>
            <ContactsSection propertyId={lead.id} />
          </TabPanel>
        </Paper>

        {/* Sticky right panel — tasks + compact property info */}
        <Paper
          variant="outlined"
          sx={{
            width: 300,
            flexShrink: 0,
            p: 2,
            position: 'sticky',
            top: 80,
            maxHeight: 'calc(100vh - 100px)',
            overflowY: 'auto',
            display: { xs: 'none', md: 'block' },
          }}
        >
          {/* Tasks */}
          <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
            Tasks
          </Typography>
          <Divider sx={{ mb: 1 }} />
          <TasksTab leadId={lead.id} ccData={ccData} />

          {/* Property info summary */}
          <Divider sx={{ my: 2 }} />
          <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
            Property
          </Typography>
          {[
            [lead.property_city && lead.property_state ? `${lead.property_city}, ${lead.property_state} ${lead.property_zip ?? ''}`.trim() : null, 'location'],
            [lead.property_type, 'type'],
            [(lead.bedrooms != null || lead.bathrooms != null) ? `${lead.bedrooms ?? '?'} bd · ${lead.bathrooms ?? '?'} ba` : null, 'beds/baths'],
            [lead.square_footage ? `${lead.square_footage.toLocaleString()} sqft` : null, 'sqft'],
            [lead.year_built ? `Built ${lead.year_built}` : null, 'year'],
            [lead.units ? `${lead.units} unit${lead.units !== 1 ? 's' : ''}` : null, 'units'],
            [lead.county_assessor_pin, 'PIN'],
            [lead.zoning, 'zoning'],
          ].filter(([v]) => v).map(([value, key]) => (
            <Typography key={key as string} variant="caption" display="block" color="text.secondary" sx={{ mb: 0.25 }}>
              {value}
            </Typography>
          ))}

          {/* Contacts summary */}
          {lead.contacts && lead.contacts.length > 0 && (
            <>
              <Divider sx={{ my: 2 }} />
              <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                Contacts
              </Typography>
              {lead.contacts.map((c) => {
                const name = [c.first_name, c.last_name].filter(Boolean).join(' ') || '(No name)'
                const phone = c.phones[0]?.value ?? null
                const email = c.emails[0]?.value ?? null
                return (
                  <Box key={c.id} sx={{ mb: 1 }}>
                    <Typography variant="body2" fontWeight={c.is_primary ? 'bold' : 'normal'}>
                      {name}{c.is_primary && <Typography component="span" variant="caption" color="primary.main" sx={{ ml: 0.5 }}>Primary</Typography>}
                    </Typography>
                    {phone && (
                      <Typography variant="caption" display="block" color="text.secondary">
                        <a href={phoneTelHref(phone)} style={{ textDecoration: 'none', color: 'inherit' }}>📞 {formatPhoneNumber(phone)}</a>
                      </Typography>
                    )}
                    {email && (
                      <Typography variant="caption" display="block" color="text.secondary">
                        <a href={`mailto:${email}`} style={{ textDecoration: 'none', color: 'inherit' }}>✉️ {email}</a>
                      </Typography>
                    )}
                  </Box>
                )
              })}
            </>
          )}

          {/* Key tracking */}
          {(lead.source || lead.date_identified || lead.notes) && (
            <>
              <Divider sx={{ my: 2 }} />
              <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                Tracking
              </Typography>
              {lead.source && <Typography variant="caption" display="block" color="text.secondary" sx={{ mb: 0.25 }}>Source: {lead.source}</Typography>}
              {lead.date_identified && <Typography variant="caption" display="block" color="text.secondary" sx={{ mb: 0.25 }}>Identified: {formatDate(lead.date_identified)}</Typography>}
              {lead.notes && <Typography variant="caption" display="block" sx={{ mt: 0.5, fontStyle: 'italic' }}>{lead.notes}</Typography>}
            </>
          )}
        </Paper>

      </Box>
    </Box>
  )
}
