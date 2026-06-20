/**
 * UnifiedLeadCommandCenter — canonical lead detail view served at /leads/:id.
 *
 * Replaces the split between PropertyDetailPage (/properties/:leadId) and
 * LeadCommandCenter (/leads/:id/command-center) with a single component.
 *
 * Two React Query fetches on mount:
 *   1. commandCenter — GET /api/leads/:id/command-center → CommandCenterPayload
 *   2. lead          — GET /api/leads/:id (via /properties/:id) → PropertyDetail
 *
 * Requirements: 5.8, 5.9, 12.1, 12.2
 */
import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CircularProgress,
  Alert,
  Button,
  Box,
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Paper,
  Tabs,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Divider,
  Link,
  Tooltip,
} from '@mui/material'
import type { SelectChangeEvent } from '@mui/material'
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import HomeWorkIcon from '@mui/icons-material/HomeWork'
import ApartmentIcon from '@mui/icons-material/Apartment'
import PhoneIcon from '@mui/icons-material/Phone'
import EmailIcon from '@mui/icons-material/Email'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { commandCenterService, leadTaskService, multifamilyService, leadScoreService } from '@/services/api'
import { leadService } from '@/services/leadApi'
import { deriveQueueContext } from '@/utils/deriveQueueContext'
import type { CommandCenterPayload, PropertyDetail, LeadStatus, LeadTask, LeadTimelineEntry, PropertyScoreResponse } from '@/types'
import { LeadScoreBadge } from '@/components/LeadScoreBadge'
import type { ScoreTier } from '@/components/LeadScoreBadge'
import { LeadStatusChip } from '@/components/LeadStatusChip'
import { LeadTaskList } from '@/components/LeadTaskList'
import { LogNoteForm } from '@/components/LogNoteForm'
import { LogCallForm } from '@/components/LogCallForm'
import { LeadTimeline } from '@/components/LeadTimeline'
import { ScoreBreakdownCard } from '@/components/ScoreBreakdownCard'
import { ScoreHistoryTimeline } from '@/components/ScoreHistoryTimeline'
import { RecalculateButton } from '@/components/RecalculateButton'
import { ScoreLegend } from '@/components/ScoreLegend'
import { ContactsSection } from '@/components/ContactsSection'
import { RecommendedActionPanel } from '@/components/RecommendedActionPanel'

// All valid lead status values — derived from the LeadStatus union type
export const ALL_LEAD_STATUSES: LeadStatus[] = [
  'skip_trace',
  'awaiting_skip_trace',
  'mailing_no_contact_made',
  'mailing_contacted_no_interest',
  'mailing_contacted_interested',
  'negotiating_remote',
  'in_person_appointment',
  'offer_delivered',
  'deprioritize',
  'deal_won',
  'deal_lost',
  'suppressed',
  'do_not_contact',
]

export interface UnifiedLeadCommandCenterProps {
  leadId: number
}

// ── Score tier derivation ──────────────────────────────────────────────────────
// Matches the tier thresholds defined in ScoreLegend:
//   A = 75–100, B = 60–74, C = 40–59, D = 0–39

function scoreToTier(score: number): ScoreTier {
  if (score >= 75) return 'A'
  if (score >= 60) return 'B'
  if (score >= 40) return 'C'
  return 'D'
}

// ── StickyHeader ──────────────────────────────────────────────────────────────
// Requirements: 5.1, 10.1, 10.2

interface StickyHeaderProps {
  commandCenterData: CommandCenterPayload
}

function StickyHeader({ commandCenterData }: StickyHeaderProps) {
  const navigate = useNavigate()

  const ownerName =
    [commandCenterData.owner_first_name, commandCenterData.owner_last_name]
      .filter(Boolean)
      .join(' ') || 'Unknown Owner'

  const address = [
    commandCenterData.property_street,
    commandCenterData.property_city,
    commandCenterData.property_state,
  ]
    .filter(Boolean)
    .join(', ')

  const scoreTier = scoreToTier(commandCenterData.lead_score)

  return (
    <AppBar position="sticky" color="default" elevation={1} sx={{ top: 0, zIndex: 100 }}>
      <Toolbar>
        <IconButton
          data-testid="back-button"
          onClick={() => navigate(-1)}
          edge="start"
          aria-label="Go back"
          sx={{ mr: 1 }}
        >
          <ArrowBackIcon />
        </IconButton>

        <Box sx={{ flexGrow: 1 }}>
          <Typography variant="subtitle1" fontWeight="bold">
            {ownerName}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {address}
          </Typography>
        </Box>

        {/* Lead score badge */}
        <Box sx={{ mr: 2, display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
            {commandCenterData.lead_score}
          </Typography>
          <LeadScoreBadge tier={scoreTier} size="small" />
        </Box>

        {/* Lead status chip */}
        <LeadStatusChip status={commandCenterData.lead_status} />
      </Toolbar>
    </AppBar>
  )
}

// ── StatusManagementPanel ─────────────────────────────────────────────────────
// Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

interface StatusManagementPanelProps {
  leadId: number
  currentStatus: LeadStatus
  onStatusChanged: () => void
}

function StatusManagementPanel({ leadId, currentStatus, onStatusChanged }: StatusManagementPanelProps) {
  const queryClient = useQueryClient()
  const [pendingStatus, setPendingStatus] = useState<LeadStatus | null>(null)
  const [statusReason, setStatusReason] = useState('')
  const [statusChanging, setStatusChanging] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)

  const otherStatuses = ALL_LEAD_STATUSES.filter(s => s !== currentStatus)

  const handleSelectStatus = (e: SelectChangeEvent<string>) => {
    setPendingStatus(e.target.value as LeadStatus)
    setStatusError(null)
  }

  const handleSubmit = async () => {
    if (!pendingStatus) return
    setStatusChanging(true)
    setStatusError(null)
    try {
      await commandCenterService.updateStatus(leadId, pendingStatus, statusReason || undefined)
      setPendingStatus(null)
      setStatusReason('')
      queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      onStatusChanged()
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : 'Failed to update status')
    } finally {
      setStatusChanging(false)
    }
  }

  const handleCancel = () => {
    setPendingStatus(null)
    setStatusReason('')
    setStatusError(null)
  }

  return (
    <Box sx={{ p: 2 }}>
      <FormControl size="small" sx={{ minWidth: 200 }}>
        <InputLabel>Status</InputLabel>
        <Select
          value={currentStatus}
          label="Status"
          onChange={handleSelectStatus}
        >
          {otherStatuses.map(status => (
            <MenuItem key={status} value={status}>{status}</MenuItem>
          ))}
        </Select>
      </FormControl>

      {pendingStatus && (
        <Box sx={{ mt: 2 }}>
          <TextField
            label="Reason (optional)"
            multiline
            rows={3}
            fullWidth
            inputProps={{ maxLength: 500 }}
            value={statusReason}
            onChange={e => setStatusReason(e.target.value)}
            sx={{ mb: 1 }}
          />
          {statusError && (
            <Alert severity="error" sx={{ mb: 1 }}>{statusError}</Alert>
          )}
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="contained"
              disabled={statusChanging}
              onClick={handleSubmit}
              data-testid="status-submit-btn"
            >
              {statusChanging ? 'Saving...' : 'Confirm Status Change'}
            </Button>
            <Button variant="outlined" onClick={handleCancel}>
              Cancel
            </Button>
          </Box>
        </Box>
      )}
    </Box>
  )
}

// ── QueueContextBanners ───────────────────────────────────────────────────────

interface QueueContextBannersProps {
  commandCenterData: CommandCenterPayload
}

function QueueContextBanners({ commandCenterData }: QueueContextBannersProps) {
  const queues = deriveQueueContext(commandCenterData)

  if (queues.length === 0) return null

  return (
    <Box sx={{ mb: 1 }}>
      {queues.map((queue, index) => (
        <Alert
          key={index}
          severity={queue.color === 'default' ? 'info' : queue.color}
          data-testid="queue-context-banner"
          sx={{ mb: 0.5 }}
          action={
            <Button component={RouterLink} to={queue.path} size="small" color="inherit">
              View Queue
            </Button>
          }
        >
          <strong>{queue.label}</strong> — {queue.reason}
        </Alert>
      ))}
    </Box>
  )
}

// ── TasksPanel ────────────────────────────────────────────────────────────────
// Requirements: 7.1, 7.2, 7.3, 7.4, 12.4

interface TasksPanelProps {
  leadId: number
  initialTasks: LeadTask[]
  onTasksChanged: () => void
}

function TasksPanel({ leadId, initialTasks, onTasksChanged }: TasksPanelProps) {
  const queryClient = useQueryClient()
  const [tasks, setTasks] = useState<LeadTask[]>(initialTasks)
  const tasksRef = useRef<LeadTask[]>(initialTasks)

  // Keep ref in sync with state for rollback on failure
  useEffect(() => {
    tasksRef.current = tasks
  }, [tasks])

  // LeadTaskList handles creation internally and calls this with the new task.
  // No optimistic update needed here — the API call already succeeded.
  const handleTaskCreated = (task: LeadTask) => {
    // Replace the optimistic placeholder (id=0) with the real task from the API
    setTasks(prev => prev.map(t => (t.id === 0 ? task : t)))
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    onTasksChanged()
  }

  // Called immediately on form submit (before API call) to add a placeholder
  // so the UI grows from N to N+1 optimistically (Requirement 7.2, Property 12).
  const handleOptimisticTaskCreate = (optimisticTask: LeadTask) => {
    setTasks(prev => [optimisticTask, ...prev])
  }

  // Called when the create API call fails — roll back the optimistic placeholder
  // (id=0) so a failed create doesn't leave a stale task in the list (Req 7.2).
  const handleOptimisticTaskRevert = () => {
    setTasks(prev => prev.filter(t => t.id !== 0))
  }

  const handleTaskCompleted = async (taskId: number | string) => {
    const snapshot = tasksRef.current
    // Optimistic remove
    setTasks(prev => prev.filter(t => t.id !== taskId))

    // Only native tasks (numeric IDs) can be completed from the platform
    if (typeof taskId === 'number') {
      try {
        await leadTaskService.completeTask(leadId, taskId)
        queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        onTasksChanged()
      } catch (err) {
        // Rollback from snapshot
        setTasks(snapshot)
        console.error('Failed to complete task:', err)
      }
    }
  }

  return (
    <Paper sx={{ p: 2, mb: 2 }} data-testid="tasks-panel">
      <LeadTaskList
        leadId={leadId}
        tasks={tasks}
        onTaskCreated={handleTaskCreated}
        onTaskCompleted={handleTaskCompleted}
        onOptimisticTaskCreate={handleOptimisticTaskCreate}
        onOptimisticTaskRevert={handleOptimisticTaskRevert}
      />
    </Paper>
  )
}

// ── ActivityPanel ─────────────────────────────────────────────────────────
// Requirements: 8.1, 8.2, 8.3

interface ActivityPanelProps {
  leadId: number
  initialEntries: LeadTimelineEntry[]
  initialTotal: number
}

// forwardRef so the main component can scroll the panel into view when the
// `?tab=timeline` deep-link is used (the timeline has no tab — it lives here).
const ActivityPanel = React.forwardRef<HTMLDivElement, ActivityPanelProps>(
  function ActivityPanel({ leadId, initialEntries, initialTotal }, ref) {
    const [timelineEntries, setTimelineEntries] = useState<LeadTimelineEntry[]>(initialEntries)
    const [timelineTotal, setTimelineTotal] = useState(initialTotal)

    const handleNotesSaved = (entry: LeadTimelineEntry) => {
      // Optimistic prepend — entry already created by LogNoteForm before calling onSaved
      setTimelineEntries(prev => [entry, ...prev])
      setTimelineTotal(prev => prev + 1)
    }

    const handleCallSaved = (entry: LeadTimelineEntry) => {
      // Optimistic prepend — entry already created by LogCallForm before calling onSaved
      setTimelineEntries(prev => [entry, ...prev])
      setTimelineTotal(prev => prev + 1)
    }

    const handleLoadMore = async (page: number): Promise<{ entries: LeadTimelineEntry[]; total: number }> => {
      const result = await commandCenterService.getTimeline(leadId, page)
      return { entries: result.entries, total: result.total }
    }

    return (
      <Box ref={ref} sx={{ mb: 2, overflow: 'auto' }} data-testid="activity-panel">
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 1 }}>Log Note</Typography>
          <LogNoteForm leadId={leadId} onSaved={handleNotesSaved} />
        </Box>
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 1 }}>Log Call</Typography>
          <LogCallForm leadId={leadId} onSaved={handleCallSaved} />
        </Box>
        <LeadTimeline
          leadId={leadId}
          initialEntries={timelineEntries}
          initialTotal={timelineTotal}
          onLoadMore={handleLoadMore}
        />
      </Box>
    )
  }
)

// ── Helper functions ──────────────────────────────────────────────────────────

const formatDate = (dateStr: string | null | undefined): string => {
  if (!dateStr) return '—'
  try { return new Date(dateStr).toLocaleDateString() } catch { return '—' }
}

const formatDateTime = (dateStr: string | null | undefined): string => {
  if (!dateStr) return '—'
  try { return new Date(dateStr).toLocaleString() } catch { return '—' }
}

const getEnrichmentStatusColor = (
  status: string,
): 'success' | 'error' | 'warning' | 'default' => {
  switch (status) {
    case 'success': return 'success'
    case 'failed': return 'error'
    case 'pending': return 'warning'
    default: return 'default'
  }
}

const getOutreachStatusColor = (
  status: string,
): 'success' | 'info' | 'warning' | 'error' | 'default' => {
  switch (status) {
    case 'converted': return 'success'
    case 'responded': return 'info'
    case 'contacted': return 'warning'
    case 'opted_out': return 'error'
    default: return 'default'
  }
}

const outreachStatusLabel = (status: string): string =>
  status.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')

// ── TabPanel ──────────────────────────────────────────────────────────────────
// Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6

// Maps the `?tab=` deep-link query param (set by navigations such as the Needs
// Review queue's "View Analysis" / "View Activity" actions) to a Tab_Panel
// index. Tab order (Req 5.5): 0 Info · 1 Score · 2 Enrichment · 3 Marketing ·
// 4 Analysis · 5 Contacts. The activity timeline is NOT a tab — it lives in the
// always-visible ActivityPanel above the Tab_Panel — so `timeline` and any
// unknown/absent value fall back to the default Info tab here. The `timeline`
// value is instead handled by UnifiedLeadCommandCenter, which scrolls the
// ActivityPanel into view (see the scroll effect in the main component).
const DEFAULT_TAB_INDEX = 0

const TAB_PARAM_TO_INDEX: Record<string, number> = {
  info: 0,
  score: 1,
  enrichment: 2,
  marketing: 3,
  analysis: 4,
  contacts: 5,
}

export function tabParamToIndex(param: string | null | undefined): number {
  if (!param) return DEFAULT_TAB_INDEX
  const index = TAB_PARAM_TO_INDEX[param.toLowerCase()]
  return index ?? DEFAULT_TAB_INDEX
}

interface TabPanelComponentProps {
  leadId: number
  leadData: PropertyDetail
}

function TabPanel({ leadId, leadData }: TabPanelComponentProps) {
  const [searchParams] = useSearchParams()
  // Initialize the active tab from the ?tab= deep-link param on mount, then keep
  // it in sync if the param changes (e.g. navigating between leads via queue
  // actions). Manual tab clicks are preserved because they don't change the param.
  const tabParam = searchParams.get('tab')
  const [activeTab, setActiveTab] = useState(() => tabParamToIndex(tabParam))

  useEffect(() => {
    setActiveTab(tabParamToIndex(tabParam))
  }, [tabParam])

  // Score tab data — only fetched when Score tab is active or pre-loaded
  const { data: scoreData } = useQuery<PropertyScoreResponse>({
    queryKey: ['leadScore', leadId],
    queryFn: async () => {
      const response = await leadScoreService.getLeadScore(leadId)
      return response.data
    },
  })

  // Analysis tab handlers
  const navigate = useNavigate()
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  const handleStartSingleFamily = async () => {
    setAnalysisLoading(true)
    setAnalysisError(null)
    try {
      const result = await leadService.analyzeLead(leadId)
      navigate(`/analysis/${result.session_id}`)
    } catch (err: any) {
      setAnalysisError(err.message || 'Failed to start analysis.')
    } finally {
      setAnalysisLoading(false)
    }
  }

  const handleStartMultifamily = async () => {
    setAnalysisError(null)
    try {
      const deal = await multifamilyService.createDeal({
        property_address: leadData.property_street,
        unit_count: leadData.units ?? 5,
        purchase_price: 0,
        close_date: new Date().toISOString().split('T')[0],
      })
      await multifamilyService.linkDealToLead(deal.id, leadData.id)
      navigate(`/multifamily/deals/${deal.id}`)
    } catch (err: any) {
      setAnalysisError(err.message || 'Failed to start multifamily analysis.')
    }
  }

  const fieldGroup = (title: string, fields: [string, string | number | null | undefined][]) => (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle1" fontWeight="bold" gutterBottom>{title}</Typography>
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

  const session = leadData.analysis_session
  const units = leadData.units
  const showMultifamily = units !== null && units >= 5
  const showSingleFamily = units === null || units < 5
  const showBoth = units === null

  return (
    <Box data-testid="tab-panel">
      <Tabs
        value={activeTab}
        onChange={(_, newValue) => setActiveTab(newValue)}
        aria-label="Lead detail tabs"
        variant="scrollable"
        scrollButtons="auto"
      >
        <Tab label="Info" />
        <Tab label="Score" />
        <Tab label="Enrichment" />
        <Tab label="Marketing" />
        <Tab label="Analysis" />
        <Tab label="Contacts" />
      </Tabs>
      <Divider />

      {/* Info tab — Req 9.1 */}
      {activeTab === 0 && (
        <Box sx={{ p: 2 }}>
          {fieldGroup('Owner', [
            ['First Name', leadData.owner_first_name],
            ['Last Name', leadData.owner_last_name],
            ['Owner 2', [leadData.owner_2_first_name, leadData.owner_2_last_name].filter(Boolean).join(' ') || null],
            ['Ownership Type', leadData.ownership_type],
            ['Acquisition Date', formatDate(leadData.acquisition_date)],
          ])}
          {fieldGroup('Property Details', [
            ['Street', leadData.property_street],
            ['City', leadData.property_city],
            ['State', leadData.property_state],
            ['Zip Code', leadData.property_zip],
            ['Property Type', leadData.property_type],
            ['Bedrooms', leadData.bedrooms],
            ['Bathrooms', leadData.bathrooms],
            ['Square Footage', leadData.square_footage?.toLocaleString()],
            ['Lot Size', leadData.lot_size?.toLocaleString()],
            ['Year Built', leadData.year_built],
            ['Units', leadData.units],
            ['Units Allowed', leadData.units_allowed],
            ['Zoning', leadData.zoning],
            ['County Assessor PIN', leadData.county_assessor_pin],
            ['Tax Bill 2021', leadData.tax_bill_2021 != null ? `$${leadData.tax_bill_2021.toLocaleString()}` : null],
            ['Most Recent Sale', leadData.most_recent_sale],
          ])}
          {fieldGroup('Contact Information', [
            ['Phone 1', leadData.phone_1],
            ['Phone 2', leadData.phone_2],
            ['Phone 3', leadData.phone_3],
            ['Email 1', leadData.email_1],
            ['Email 2', leadData.email_2],
          ])}
          {fieldGroup('Mailing Information', [
            ['Mailing Address', leadData.mailing_address],
            ['City', leadData.mailing_city],
            ['State', leadData.mailing_state],
            ['Zip Code', leadData.mailing_zip],
          ])}
          {fieldGroup('Research & Tracking', [
            ['Source', leadData.source],
            ['Date Identified', formatDate(leadData.date_identified)],
            ['Notes', leadData.notes],
            ['Needs Skip Trace', leadData.needs_skip_trace != null ? (leadData.needs_skip_trace ? 'Yes' : 'No') : null],
            ['Skip Tracer', leadData.skip_tracer],
            ['Date Skip Traced', formatDate(leadData.date_skip_traced)],
          ])}
          {fieldGroup('Metadata', [
            ['Data Source', leadData.data_source],
            ['Created', formatDateTime(leadData.created_at)],
            ['Updated', formatDateTime(leadData.updated_at)],
          ])}
        </Box>
      )}

      {/* Score tab — Req 9.2 */}
      {activeTab === 1 && (
        <Box sx={{ p: 2 }}>
          <Box sx={{ mb: 2, display: 'flex', justifyContent: 'flex-end' }}>
            <RecalculateButton mode="single" leadId={leadId} />
          </Box>
          <Box sx={{ mb: 2 }}>
            <ScoreLegend />
          </Box>
          {!scoreData && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress size={32} aria-label="Loading score" />
            </Box>
          )}
          {scoreData && !scoreData.latest && (
            <Alert severity="info" sx={{ mb: 2 }}>
              No score yet. Use the Recalculate button above to generate the first score.
            </Alert>
          )}
          {scoreData?.latest && (
            <>
              <Box sx={{ mb: 2 }}>
                <ScoreBreakdownCard score={scoreData.latest} />
              </Box>
              <ScoreHistoryTimeline history={scoreData.history} />
            </>
          )}
        </Box>
      )}

      {/* Enrichment tab — Req 9.3 */}
      {activeTab === 2 && (
        <Box sx={{ p: 2 }}>
          {(leadData.enrichment_records ?? []).length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No enrichment records yet. Use the Enrich action to pull data from external sources.
            </Typography>
          ) : (
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
                  {(leadData.enrichment_records ?? []).map((rec) => (
                    <TableRow key={rec.id}>
                      <TableCell>{rec.data_source_name || `Source #${rec.data_source_id}`}</TableCell>
                      <TableCell>
                        <Chip label={rec.status} size="small" color={getEnrichmentStatusColor(rec.status)} />
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
          )}
        </Box>
      )}

      {/* Marketing tab — Req 9.4 */}
      {activeTab === 3 && (
        <Box sx={{ p: 2 }}>
          {(leadData.marketing_lists ?? []).length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              This property is not a member of any marketing lists.
            </Typography>
          ) : (
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
                  {(leadData.marketing_lists ?? []).map((m) => (
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
          )}
        </Box>
      )}

      {/* Analysis tab — Req 9.5 */}
      {activeTab === 4 && (
        <Box sx={{ p: 2 }}>
          {analysisError && (
            <Alert severity="error" sx={{ mb: 2 }}>{analysisError}</Alert>
          )}
          {!session ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body1" gutterBottom>
                No analysis has been started for this property yet.
              </Typography>
              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', mt: 2, flexWrap: 'wrap' }}>
                {(showSingleFamily || showBoth) && (
                  <Button
                    variant="outlined"
                    startIcon={analysisLoading ? <CircularProgress size={18} /> : <HomeWorkIcon />}
                    onClick={handleStartSingleFamily}
                    disabled={analysisLoading}
                    aria-label="Start single-family analysis"
                  >
                    Start Single-Family Analysis
                  </Button>
                )}
                {(showMultifamily || showBoth) && (
                  <Button
                    variant="contained"
                    startIcon={<ApartmentIcon />}
                    onClick={handleStartMultifamily}
                    disabled={analysisLoading}
                    aria-label="Start multifamily analysis"
                  >
                    Start Multifamily Analysis
                  </Button>
                )}
              </Box>
            </Box>
          ) : (
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
          )}
        </Box>
      )}

      {/* Contacts tab — Req 9.6 */}
      {activeTab === 5 && (
        <Box sx={{ p: 2 }}>
          <ContactsSection propertyId={leadId} />
        </Box>
      )}
    </Box>
  )
}

// ── PropertySidebar helpers ───────────────────────────────────────────────────

function SidebarSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography
        variant="overline"
        sx={{ fontSize: '0.65rem', letterSpacing: 1, color: 'text.disabled', display: 'block', mb: 0.5 }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  )
}

function SidebarRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (value == null) return null
  return (
    <Box sx={{ display: 'flex', gap: 1, mb: 0.5 }}>
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 90, flexShrink: 0 }}>
        {label}
      </Typography>
      <Typography variant="caption" sx={{ wordBreak: 'break-word' }}>
        {value}
      </Typography>
    </Box>
  )
}

function CopyablePhone({ phone }: { phone: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(phone)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
      <PhoneIcon sx={{ fontSize: 13, color: 'text.secondary' }} />
      <Link href={`tel:${phone}`} variant="caption" underline="hover">
        {phone}
      </Link>
      <Tooltip title={copied ? 'Copied!' : 'Copy'}>
        <IconButton size="small" onClick={handleCopy} sx={{ p: 0.25 }}>
          <ContentCopyIcon sx={{ fontSize: 11 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

function CopyableEmail({ email }: { email: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(email)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
      <EmailIcon sx={{ fontSize: 13, color: 'text.secondary' }} />
      <Link href={`mailto:${email}`} variant="caption" underline="hover" noWrap>
        {email}
      </Link>
      <Tooltip title={copied ? 'Copied!' : 'Copy'}>
        <IconButton size="small" onClick={handleCopy} sx={{ p: 0.25 }}>
          <ContentCopyIcon sx={{ fontSize: 11 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

// ── PropertySidebar ───────────────────────────────────────────────────────────
// Requirements: 11.1, 11.2, 11.3, 11.4, 11.5

interface PropertySidebarProps {
  commandCenterData: CommandCenterPayload
  leadScore: number
}

function PropertySidebar({ commandCenterData, leadScore }: PropertySidebarProps) {
  const data = commandCenterData as any

  const ownerName =
    [commandCenterData.owner_first_name, commandCenterData.owner_last_name]
      .filter(Boolean)
      .join(' ') || ''
  const owner2Name =
    [commandCenterData.owner_2_first_name, commandCenterData.owner_2_last_name]
      .filter(Boolean)
      .join(' ') || ''

  // Collect non-empty phones and emails — prefer merged lists from backend, fall back to flat columns
  const phones: string[] = data.phones?.length
    ? data.phones
    : [
        commandCenterData.phone_1,
        commandCenterData.phone_2,
        commandCenterData.phone_3,
        commandCenterData.phone_4,
        commandCenterData.phone_5,
        commandCenterData.phone_6,
        commandCenterData.phone_7,
      ].filter(Boolean) as string[]

  const emails: string[] = data.emails?.length
    ? data.emails
    : [
        commandCenterData.email_1,
        commandCenterData.email_2,
        commandCenterData.email_3,
        commandCenterData.email_4,
        commandCenterData.email_5,
      ].filter(Boolean) as string[]

  return (
    <Paper
      variant="outlined"
      data-testid="property-sidebar"
      sx={{
        position: 'sticky',
        top: 80, // below the AppBar
        maxHeight: 'calc(100vh - 100px)',
        overflowY: 'auto',
        display: { xs: 'none', sm: 'none', md: 'none', lg: 'block' },
        minWidth: 280,
        maxWidth: 320,
        flexShrink: 0,
        p: 2,
      }}
    >
      {/* Contact Info — Req 11.1 */}
      <SidebarSection title="Contact Info">
        {ownerName && (
          <Typography variant="caption" fontWeight={600} display="block" sx={{ mb: 0.75 }}>
            {ownerName}
          </Typography>
        )}
        {owner2Name && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
            {owner2Name}
          </Typography>
        )}
        {phones.map((p, i) => (
          <CopyablePhone key={i} phone={p} />
        ))}
        {emails.map((e, i) => (
          <CopyableEmail key={i} email={e} />
        ))}
        {data.socials && <SidebarRow label="Socials" value={data.socials} />}
      </SidebarSection>

      {/* Owner */}
      {(owner2Name || commandCenterData.ownership_type || commandCenterData.acquisition_date) && (
        <SidebarSection title="Owner">
          {owner2Name && <SidebarRow label="Owner 2" value={owner2Name} />}
          <SidebarRow label="Type" value={commandCenterData.ownership_type} />
          <SidebarRow label="Acquired" value={commandCenterData.acquisition_date} />
        </SidebarSection>
      )}

      {/* Property — Req 11.2 */}
      <SidebarSection title="Property">
        {(commandCenterData.property_street || commandCenterData.property_city) && (
          <Box sx={{ mb: 0.75 }}>
            {commandCenterData.property_street && (
              <Typography variant="caption" fontWeight={600} display="block">
                {commandCenterData.property_street}
              </Typography>
            )}
            {(commandCenterData.property_city || commandCenterData.property_state || commandCenterData.property_zip) && (
              <Typography variant="caption" color="text.secondary" display="block">
                {[commandCenterData.property_city, commandCenterData.property_state, commandCenterData.property_zip]
                  .filter(Boolean)
                  .join(', ')}
              </Typography>
            )}
          </Box>
        )}
        <SidebarRow label="Type" value={commandCenterData.property_type} />
        <SidebarRow
          label="Beds / Baths"
          value={
            commandCenterData.bedrooms != null || commandCenterData.bathrooms != null
              ? `${commandCenterData.bedrooms ?? '?'} bd / ${commandCenterData.bathrooms ?? '?'} ba`
              : null
          }
        />
        <SidebarRow
          label="Sq Ft"
          value={commandCenterData.square_footage ? commandCenterData.square_footage.toLocaleString() : null}
        />
        <SidebarRow label="Year Built" value={commandCenterData.year_built} />
        <SidebarRow
          label="Lot Size"
          value={data.lot_size ? `${Number(data.lot_size).toLocaleString()} sqft` : null}
        />
        <SidebarRow label="Units" value={data.units} />
        <SidebarRow label="Units Allowed" value={data.units_allowed} />
        <SidebarRow label="Zoning" value={data.zoning} />
        <SidebarRow label="PIN" value={commandCenterData.county_assessor_pin} />
        <SidebarRow
          label="Tax Bill"
          value={data.tax_bill_2021 ? `$${Number(data.tax_bill_2021).toLocaleString()}` : null}
        />
        <SidebarRow label="Last Sale" value={data.most_recent_sale} />
        {data.address_2 && <SidebarRow label="Address 2" value={data.address_2} />}
        {data.returned_addresses && (
          <SidebarRow label="Other Addresses" value={data.returned_addresses} />
        )}
      </SidebarSection>

      {/* Owner Mailing Address */}
      {(commandCenterData.mailing_address || commandCenterData.mailing_city) && (
        <SidebarSection title="Owner Mailing Address">
          {commandCenterData.mailing_address && (
            <Typography variant="caption" display="block">{commandCenterData.mailing_address}</Typography>
          )}
          {(commandCenterData.mailing_city || commandCenterData.mailing_state || commandCenterData.mailing_zip) && (
            <Typography variant="caption" display="block">
              {[commandCenterData.mailing_city, commandCenterData.mailing_state, commandCenterData.mailing_zip]
                .filter(Boolean)
                .join(', ')}
            </Typography>
          )}
        </SidebarSection>
      )}

      {/* Skip Trace (conditional) */}
      {(data.needs_skip_trace || data.skip_tracer || data.date_skip_traced) && (
        <SidebarSection title="Skip Trace">
          <SidebarRow label="Needed" value={data.needs_skip_trace ? 'Yes' : 'No'} />
          <SidebarRow label="Tracer" value={data.skip_tracer} />
          <SidebarRow label="Date" value={data.date_skip_traced} />
        </SidebarSection>
      )}

      {/* Mailer History (conditional) */}
      {(data.mailer_history || data.up_next_to_mail) && (
        <SidebarSection title="Mailer History">
          {data.up_next_to_mail && (
            <Chip label="Up Next to Mail" size="small" color="primary" sx={{ mb: 0.5 }} />
          )}
          {data.mailer_history && (
            <Typography
              variant="caption"
              sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', display: 'block' }}
            >
              {typeof data.mailer_history === 'string'
                ? data.mailer_history
                : JSON.stringify(data.mailer_history, null, 2)}
            </Typography>
          )}
        </SidebarSection>
      )}

      {/* Marketing Lists (conditional) */}
      {data.marketing_memberships?.length > 0 && (
        <SidebarSection title="Marketing Lists">
          {data.marketing_memberships.map((m: any, i: number) => (
            <Box key={i} sx={{ mb: 0.75 }}>
              <Typography variant="caption" fontWeight={500} display="block">{m.list_name}</Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                Status: {m.outreach_status}
                {m.status_updated_at && ` · Updated ${new Date(m.status_updated_at).toLocaleDateString()}`}
                {m.added_at && ` · Added ${new Date(m.added_at).toLocaleDateString()}`}
              </Typography>
            </Box>
          ))}
        </SidebarSection>
      )}

      {/* Source & Metadata — Req 11.3 */}
      <SidebarSection title="Source">
        <SidebarRow
          label="Source"
          value={
            data.source === 'hubspot_import'
              ? `HubSpot${data.hubspot_deal_name ? ` — ${data.hubspot_deal_name}` : ''}`
              : data.source
          }
        />
        <SidebarRow label="Category" value={commandCenterData.lead_category} />
        <SidebarRow label="Data Source" value={data.data_source} />
        <SidebarRow label="Identified" value={data.date_identified} />
        <SidebarRow
          label="Added"
          value={data.created_at ? new Date(data.created_at).toLocaleDateString() : null}
        />
        <SidebarRow
          label="Last Sync"
          value={
            commandCenterData.last_hubspot_sync_at
              ? new Date(commandCenterData.last_hubspot_sync_at).toLocaleDateString()
              : null
          }
        />
        <SidebarRow
          label="Last Contact"
          value={
            commandCenterData.last_contact_date
              ? new Date(commandCenterData.last_contact_date).toLocaleDateString()
              : null
          }
        />
        <SidebarRow label="Follow-up Date" value={data.follow_up_date} />
        <SidebarRow label="Added to HS" value={commandCenterData.date_added_to_hubspot} />
      </SidebarSection>

      {/* Scores — Req 11.4 */}
      <SidebarSection title="Scores">
        <SidebarRow label="Lead Score" value={leadScore} />
        <SidebarRow
          label="Completeness"
          value={
            commandCenterData.data_completeness_score != null
              ? `${Math.round(commandCenterData.data_completeness_score)}%`
              : null
          }
        />
      </SidebarSection>
    </Paper>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function UnifiedLeadCommandCenter({ leadId }: UnifiedLeadCommandCenterProps) {
  const queryClient = useQueryClient()
  const {
    data: commandCenterData,
    isLoading: commandCenterLoading,
    error: commandCenterError,
  } = useQuery<CommandCenterPayload, Error>({
    queryKey: ['commandCenter', leadId],
    queryFn: () => commandCenterService.getCommandCenter(leadId),
    staleTime: 0,
    refetchOnMount: 'always',
  })

  const {
    data: leadData,
    isLoading: leadLoading,
  } = useQuery<PropertyDetail, Error>({
    queryKey: ['lead', leadId],
    queryFn: () => leadService.getLeadDetail(leadId),
    staleTime: 0,
    refetchOnMount: 'always',
  })

  // Deep-link handling for the `?tab=` query param. The TabPanel selects the
  // tab named by the param (info/score/enrichment/marketing/analysis/contacts).
  // There is no "timeline" tab — the activity timeline lives in the always-
  // visible ActivityPanel above the tabs — so the Needs Review queue's "View
  // Activity" deep-link (?tab=timeline) instead scrolls the ActivityPanel into
  // view once the data has loaded and the panel has rendered.
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const activityRef = useRef<HTMLDivElement>(null)
  const showLead = !commandCenterLoading && !leadLoading && !commandCenterError

  useEffect(() => {
    if (!showLead) return
    if (tabParam?.toLowerCase() !== 'timeline') return
    const el = activityRef.current
    // jsdom (and some non-DOM environments) don't implement scrollIntoView.
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [showLead, tabParam])

  if (commandCenterLoading || leadLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress aria-label="Loading lead" />
      </Box>
    )
  }

  if (commandCenterError) {
    const message =
      commandCenterError instanceof Error
        ? commandCenterError.message
        : 'Failed to load lead data'
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error" sx={{ mb: 2 }}>
          {message}
        </Alert>
        <Button component={RouterLink} to="/properties" variant="outlined">
          Back to Properties
        </Button>
      </Box>
    )
  }

  // Main layout
  return (
    <Box>
      {/* Sticky header — owner name, address, score, status, back button (Req 5.1, 10.1, 10.2) */}
      <StickyHeader commandCenterData={commandCenterData!} />

      {/* Queue context banners — one per queue membership (Req 5.2) */}
      <QueueContextBanners commandCenterData={commandCenterData!} />

      {/* Two-column flex layout: activity column (left) + property sidebar (right, hidden below lg) */}
      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', p: { xs: 1, sm: 2 } }}>
        {/* Activity column — order: RecommendedActionPanel → TasksPanel → ActivityPanel → TabPanel */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {/* Status management (outside the prescribed column order — sits above RA panel) */}
          <StatusManagementPanel
            leadId={leadId}
            currentStatus={commandCenterData!.lead_status}
            onStatusChanged={() => queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })}
          />

          {/* RecommendedActionPanel — first in ActivityColumn (Req 5.3) */}
          <Box sx={{ mb: 2 }}>
            <RecommendedActionPanel
              recommendedAction={commandCenterData!.recommended_action}
              leadStatus={commandCenterData!.lead_status}
              openTasks={commandCenterData!.open_tasks ?? []}
              onAction={async (_action: string) => {
                // Re-fetch command center after any RA action so the next RA is shown
                await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
              }}
            />
          </Box>

          {/* TasksPanel — second in ActivityColumn (Req 7.1–7.4) */}
          <TasksPanel
            leadId={leadId}
            initialTasks={commandCenterData!.open_tasks ?? []}
            onTasksChanged={() => queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })}
          />

          {/* ActivityPanel — third in ActivityColumn (Req 8.1–8.3) */}
          <ActivityPanel
            ref={activityRef}
            leadId={leadId}
            initialEntries={commandCenterData!.timeline.entries}
            initialTotal={commandCenterData!.timeline.total}
          />

          {/* TabPanel — fourth in ActivityColumn (Req 9.1–9.6) */}
          <TabPanel leadId={leadId} leadData={leadData!} />
        </Box>

        {/* Property sidebar — sticky, hidden below lg breakpoint (Req 11.1–11.5) */}
        <PropertySidebar
          commandCenterData={commandCenterData!}
          leadScore={commandCenterData!.lead_score}
        />
      </Box>
    </Box>
  )
}
