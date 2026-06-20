/**
 * LeadCommandCenter — main detail view for a single lead.
 *
 * Two-column layout:
 *   Left (main): Back button, Queue context, Recommended Action, Tasks, Log Note/Call, Timeline
 *   Right (sidebar): Contact info, Property details, Source/metadata
 *
 * Requirements: 7.1–7.12
 */
import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Divider,
  FormControl,
  InputLabel,
  Link,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
  Paper,
  IconButton,
  Tooltip,
  Button,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import BlockIcon from '@mui/icons-material/Block'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import PhoneIcon from '@mui/icons-material/Phone'
import EmailIcon from '@mui/icons-material/Email'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import type { LeadStatus, LeadTask, LeadTimelineEntry } from '@/types'
import { deriveQueueContext } from '@/utils/deriveQueueContext'
import { commandCenterService, leadTaskService } from '@/services/api'
import { RecommendedActionPanel } from './RecommendedActionPanel'
import { LeadTaskList } from './LeadTaskList'
import { LeadTimeline } from './LeadTimeline'
import { LogNoteForm } from './LogNoteForm'
import { LogCallForm } from './LogCallForm'
import { LEAD_STATUS_LABELS } from './LeadStatusChip'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Derive status options from LEAD_STATUS_LABELS so there's a single source of truth.
// Casting through unknown is needed because Object.keys always returns string[].
const ALL_LEAD_STATUSES = Object.keys(LEAD_STATUS_LABELS) as LeadStatus[]

// ---------------------------------------------------------------------------
// Sidebar helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Queue membership derivation
// Determines which queue(s) this lead belongs to and why, purely from
// the lead's data fields — no extra API call needed.
// ---------------------------------------------------------------------------

export interface LeadCommandCenterProps {
  leadId: number
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LeadCommandCenter({ leadId }: LeadCommandCenterProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [statusChanging, setStatusChanging] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [pendingStatus, setPendingStatus] = useState<LeadStatus | null>(null)
  const [statusReason, setStatusReason] = useState('')
  const [timelineEntries, setTimelineEntries] = useState<LeadTimelineEntry[]>([])
  const [timelineTotal, setTimelineTotal] = useState(0)
  const [tasks, setTasks] = useState<LeadTask[]>([])

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['commandCenter', leadId],
    queryFn: () => commandCenterService.getCommandCenter(leadId),
    staleTime: 0,            // treat cached data as immediately stale
    refetchOnMount: 'always', // always refetch when component mounts, even if data exists in cache
  })

  useEffect(() => {
    if (data) {
      setTimelineEntries(data.timeline.entries)
      setTimelineTotal(data.timeline.total)
      setTasks(data.open_tasks)
    }
  }, [data])

  const handleStatusChange = (newStatus: LeadStatus) => {
    if (!data || newStatus === data.lead_status) return
    setStatusError(null)  // clear any prior error when user picks a new status
    setPendingStatus(newStatus)
    setStatusReason('')
  }

  const handleStatusConfirm = async () => {
    if (!pendingStatus) return
    try {
      setStatusChanging(true)
      await commandCenterService.updateStatus(leadId, pendingStatus, statusReason.trim() || undefined)
      setStatusError(null)  // clear error on success before resetting pending state
      queryClient.invalidateQueries({ queryKey: ['lead', leadId] })
      queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      setPendingStatus(null)
      setStatusReason('')
    } catch (err) {
      // Keep pendingStatus and statusReason so user can retry or cancel
      setStatusError('Failed to update status')
    } finally {
      setStatusChanging(false)
    }
  }

  const handleStatusCancel = () => {
    setPendingStatus(null)
    setStatusReason('')
  }

  const handleLoadMore = async (page: number) => {
    const result = await commandCenterService.getTimeline(leadId, page)
    return { entries: result.entries, total: result.total }
  }

  const handleTaskCreated = (task: LeadTask) => setTasks((prev) => [...prev, task])

  const handleTaskCompleted = async (taskId: number | string) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId))
    // Only native tasks (numeric IDs) can be completed from the platform
    if (typeof taskId === 'number') {
      try {
        await leadTaskService.completeTask(leadId, taskId)
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      } catch {
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      }
    }
  }

  const handleEntrySaved = (entry: LeadTimelineEntry) => {
    setTimelineEntries((prev) => [entry, ...prev])
    setTimelineTotal((prev) => prev + 1)
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
  }

  const handleRaAction = async (_action: string): Promise<void> => {}

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight={200} data-testid="command-center-loading">
        <CircularProgress />
      </Box>
    )
  }

  if (isError || !data) {
    return <Alert severity="error" data-testid="command-center-error">{error instanceof Error ? error.message : 'Failed to load lead data.'}</Alert>
  }

  const ownerName = [data.owner_first_name, data.owner_last_name].filter(Boolean).join(' ') || 'Unknown Owner'
  const owner2Name = [data.owner_2_first_name, data.owner_2_last_name].filter(Boolean).join(' ')
  const address = [data.property_street, data.property_city, data.property_state].filter(Boolean).join(', ') || 'No address on file'
  const isDNC = data.lead_status === 'do_not_contact'

  // Collect non-empty phones and emails — prefer merged lists from backend, fall back to flat columns
  const phones: string[] = (data as any).phones?.length
    ? (data as any).phones
    : [data.phone_1, data.phone_2, data.phone_3, data.phone_4, data.phone_5, data.phone_6, data.phone_7].filter(Boolean) as string[]
  const emails: string[] = (data as any).emails?.length
    ? (data as any).emails
    : [data.email_1, data.email_2, data.email_3, data.email_4, data.email_5].filter(Boolean) as string[]

  const queueContexts = deriveQueueContext(data)

  return (
    <Box data-testid="lead-command-center" sx={{ display: 'flex', gap: 3, alignItems: 'flex-start', p: { xs: 1, sm: 2 } }}>

      {/* ── Main column ─────────────────────────────────────────────────── */}
      <Box sx={{ flex: 1, minWidth: 0 }}>

        {/* Back button */}
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate(-1)}
          size="small"
          sx={{ mb: 2 }}
          data-testid="back-button"
        >
          Back to Queue
        </Button>

        {/* Queue context banner — shows which queue(s) this lead is in and why */}
        {queueContexts.length > 0 && (
          <Box sx={{ mb: 2 }}>
            {queueContexts.map((ctx) => (
              <Alert
                key={ctx.path}
                severity={ctx.color === 'default' ? 'info' : ctx.color}
                icon={<InfoOutlinedIcon fontSize="small" />}
                sx={{ mb: 0.75, py: 0.5 }}
                action={
                  <Button
                    component={RouterLink}
                    to={ctx.path}
                    size="small"
                    color="inherit"
                    sx={{ whiteSpace: 'nowrap' }}
                  >
                    View Queue
                  </Button>
                }
              >
                <strong>{ctx.label}</strong> — {ctx.reason}
              </Alert>
            ))}
          </Box>
        )}

        {/* Lead Header */}
        <Box sx={{ mb: 3, p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }} data-testid="lead-header">
          <Stack direction="row" alignItems="flex-start" justifyContent="space-between" flexWrap="wrap" gap={1}>
            <Box>
              <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
                <Typography variant="h5" fontWeight="bold" data-testid="lead-owner-name">
                  {ownerName}
                </Typography>
                {isDNC && (
                  <Chip icon={<BlockIcon />} label="DO NOT CONTACT" color="error" size="small" data-testid="dnc-badge" />
                )}
              </Stack>
              <Typography variant="body2" color="text.secondary" data-testid="lead-address">
                {address}
              </Typography>
            </Box>

            <Stack direction="row" alignItems="center" spacing={2}>
              <Box textAlign="center">
                <Typography variant="caption" color="text.secondary">Lead Score</Typography>
                <Typography variant="h6" fontWeight="bold" data-testid="lead-score">{data.lead_score}</Typography>
              </Box>
              <FormControl size="small" sx={{ minWidth: 160 }} data-testid="status-badge-container">
                <InputLabel id="lead-status-label">Status</InputLabel>
                <Select
                  labelId="lead-status-label"
                  label="Status"
                  value={data.lead_status}
                  onChange={(e) => handleStatusChange(e.target.value as LeadStatus)}
                  disabled={pendingStatus !== null || statusChanging}
                  inputProps={{ 'data-testid': 'status-badge-select' }}
                >
                  {ALL_LEAD_STATUSES.map((s) => (
                    <MenuItem key={s} value={s} data-testid={`status-option-${s}`}>{LEAD_STATUS_LABELS[s]}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Stack>
          </Stack>

          {statusError && (
            <Alert severity="error" sx={{ mt: 1 }} onClose={() => setStatusError(null)} data-testid="status-change-error">
              {statusError}
            </Alert>
          )}

          <Box sx={{ mt: 1.5 }} data-testid="property-match-status">
            {data.has_property_match ? (
              <Stack direction="row" alignItems="center" spacing={0.5}>
                <CheckCircleIcon fontSize="small" color="success" />
                <Typography variant="body2" color="success.main">
                  Matched —{' '}
                  {data.analysis_session_id ? (
                    <Link component={RouterLink} to={`/analysis/${data.analysis_session_id}`} data-testid="property-match-link">View Analysis</Link>
                  ) : (
                    <span>Property Matched</span>
                  )}
                </Typography>
              </Stack>
            ) : (
              <Stack direction="row" alignItems="center" spacing={0.5}>
                <HelpOutlineIcon fontSize="small" color="warning" />
                <Typography variant="body2" color="warning.main">
                  Unmatched —{' '}
                  <Link component={RouterLink} to="/queues/missing-property-match" data-testid="missing-match-link">Find Property Match</Link>
                </Typography>
              </Stack>
            )}
          </Box>

          {pendingStatus && (
            <Box sx={{ mt: 1.5, p: 1.5, border: 1, borderColor: 'primary.200', borderRadius: 1, bgcolor: 'primary.50' }}>
              <Typography variant="body2" sx={{ mb: 1 }}>
                Changing status to <strong>{LEAD_STATUS_LABELS[pendingStatus]}</strong>
              </Typography>
              <TextField
                size="small"
                fullWidth
                multiline
                maxRows={3}
                label="What happened? (optional)"
                value={statusReason}
                onChange={(e) => setStatusReason(e.target.value)}
                inputProps={{ maxLength: 500 }}
                sx={{ mb: 1 }}
              />
              <Stack direction="row" spacing={1}>
                <Button
                  size="small"
                  variant="contained"
                  onClick={handleStatusConfirm}
                  disabled={statusChanging}
                >
                  {statusChanging ? <CircularProgress size={16} /> : 'Confirm'}
                </Button>
                <Button size="small" variant="outlined" onClick={handleStatusCancel} disabled={statusChanging}>
                  Cancel
                </Button>
              </Stack>
            </Box>
          )}

        </Box>

        {/* Recommended Action */}
        <Box sx={{ mb: 3 }} data-testid="recommended-action-section">
          <RecommendedActionPanel
            recommendedAction={data.recommended_action}
            leadStatus={data.lead_status}
            openTasks={tasks.filter((t) => t.status === 'open')}
            onAction={handleRaAction}
          />
        </Box>

        {/* Open Tasks */}
        <Box sx={{ mb: 3 }} data-testid="tasks-section">
          <LeadTaskList
            leadId={leadId}
            tasks={tasks}
            recommendedAction={data.recommended_action?.value ?? null}
            onTaskCreated={handleTaskCreated}
            onTaskCompleted={handleTaskCompleted}
            onHubSpotTaskDone={() => queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })}
          />
        </Box>

        {data.notes && data.notes.trim() !== '' && (
          <Box sx={{ mt: 2, p: 1.5, border: 1, borderColor: 'divider', borderRadius: 1 }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, display: 'block', mb: 0.5 }}>
              Lead Notes
            </Typography>
            {(data as any).notes_status_conflict && (
              <Alert severity="warning" sx={{ mb: 1, py: 0.5 }} icon={false}>
                <Typography variant="caption">
                  These notes suggest contact was made — but status is still{' '}
                  <strong>Mailing, No Contact Made</strong>. Update the status above.
                </Typography>
              </Alert>
            )}
            <Typography variant="body2">{data.notes}</Typography>
          </Box>
        )}

        <Divider sx={{ mb: 3 }} />

        {/* Log Note */}
        <Box sx={{ mb: 3 }} data-testid="log-note-section">
          <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 1 }}>Log Note</Typography>
          <LogNoteForm leadId={leadId} onSaved={handleEntrySaved} />
        </Box>

        <Divider sx={{ mb: 3 }} />

        {/* Log Call */}
        <Box sx={{ mb: 3 }} data-testid="log-call-section">
          <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 1 }}>Log Call</Typography>
          <LogCallForm leadId={leadId} onSaved={handleEntrySaved} />
        </Box>

        <Divider sx={{ mb: 3 }} />

        {/* Timeline */}
        <Box data-testid="timeline-section">
        <LeadTimeline
          leadId={leadId}
          initialEntries={timelineEntries}
          initialTotal={timelineTotal}
          onLoadMore={handleLoadMore}
        />
        </Box>
      </Box>

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <Paper
        variant="outlined"
        sx={{
          width: 260,
          flexShrink: 0,
          p: 2,
          position: 'sticky',
          top: 80, // below AppBar
          maxHeight: 'calc(100vh - 100px)',
          overflowY: 'auto',
          display: { xs: 'none', lg: 'block' }, // hide on small screens
        }}
      >
        {/* Contact Info */}
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
          {phones.map((p, i) => <CopyablePhone key={i} phone={p} />)}
          {emails.map((e, i) => <CopyableEmail key={i} email={e} />)}
          {(data as any).socials && (
            <SidebarRow label="Socials" value={(data as any).socials} />
          )}
          {(data as any).unanswered_call_count > 0 && (
            <SidebarRow label="Unanswered" value={`${(data as any).unanswered_call_count} unanswered call(s)`} />
          )}
        </SidebarSection>

        {/* Owner */}
        <SidebarSection title="Owner">
          {owner2Name && <SidebarRow label="Owner 2" value={owner2Name} />}
          <SidebarRow label="Type" value={data.ownership_type} />
          <SidebarRow label="Acquired" value={data.acquisition_date} />
        </SidebarSection>

        {/* Property */}
        <SidebarSection title="Property">
          {(data.property_street || data.property_city) && (
            <Box sx={{ mb: 0.75 }}>
              {data.property_street && (
                <Typography variant="caption" fontWeight={600} display="block">{data.property_street}</Typography>
              )}
              {(data.property_city || data.property_state || data.property_zip) && (
                <Typography variant="caption" color="text.secondary" display="block">
                  {[data.property_city, data.property_state, data.property_zip].filter(Boolean).join(', ')}
                </Typography>
              )}
            </Box>
          )}
          <SidebarRow label="Type" value={data.property_type} />
          <SidebarRow label="Beds / Baths" value={
            (data.bedrooms != null || data.bathrooms != null)
              ? `${data.bedrooms ?? '?'} bd / ${data.bathrooms ?? '?'} ba`
              : null
          } />
          <SidebarRow label="Sq Ft" value={data.square_footage ? data.square_footage.toLocaleString() : null} />
          <SidebarRow label="Year Built" value={data.year_built} />
          <SidebarRow label="Lot Size" value={(data as any).lot_size ? `${(data as any).lot_size.toLocaleString()} sqft` : null} />
          <SidebarRow label="Units" value={(data as any).units} />
          <SidebarRow label="Units Allowed" value={(data as any).units_allowed} />
          <SidebarRow label="Zoning" value={(data as any).zoning} />
          <SidebarRow label="PIN" value={data.county_assessor_pin} />
          <SidebarRow label="Tax Bill" value={(data as any).tax_bill_2021 ? `$${Number((data as any).tax_bill_2021).toLocaleString()}` : null} />
          <SidebarRow label="Last Sale" value={(data as any).most_recent_sale} />
          {(data as any).address_2 && <SidebarRow label="Address 2" value={(data as any).address_2} />}
          {(data as any).returned_addresses && (
            <SidebarRow label="Other Addresses" value={(data as any).returned_addresses} />
          )}
        </SidebarSection>

        {/* Owner Mailing Address */}
        {(data.mailing_address || data.mailing_city) && (
          <SidebarSection title="Owner Mailing Address">
            {data.mailing_address && (
              <Typography variant="caption" display="block">{data.mailing_address}</Typography>
            )}
            {(data.mailing_city || data.mailing_state || data.mailing_zip) && (
              <Typography variant="caption" display="block">
                {[data.mailing_city, data.mailing_state, data.mailing_zip].filter(Boolean).join(', ')}
              </Typography>
            )}
          </SidebarSection>
        )}

        {/* Skip Trace */}
        {((data as any).needs_skip_trace || (data as any).skip_tracer || (data as any).date_skip_traced) && (
          <SidebarSection title="Skip Trace">
            <SidebarRow label="Needed" value={(data as any).needs_skip_trace ? 'Yes' : 'No'} />
            <SidebarRow label="Tracer" value={(data as any).skip_tracer} />
            <SidebarRow label="Date" value={(data as any).date_skip_traced} />
          </SidebarSection>
        )}

        {/* Mailer History */}
        {((data as any).mailer_history || (data as any).up_next_to_mail) && (
          <SidebarSection title="Mailer History">
            {(data as any).up_next_to_mail && (
              <Chip label="Up Next to Mail" size="small" color="primary" sx={{ mb: 0.5 }} />
            )}
            {(data as any).mailer_history && (
              <Typography variant="caption" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', display: 'block' }}>
                {typeof (data as any).mailer_history === 'string'
                  ? (data as any).mailer_history
                  : JSON.stringify((data as any).mailer_history, null, 2)}
              </Typography>
            )}
          </SidebarSection>
        )}

        {/* Marketing Lists */}
        {(data as any).marketing_memberships?.length > 0 && (
          <SidebarSection title="Marketing Lists">
            {(data as any).marketing_memberships.map((m: any, i: number) => (
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

        {/* Source / Metadata */}
        <SidebarSection title="Source">
          <SidebarRow label="Source" value={
            (data as any).source === 'hubspot_import'
              ? `HubSpot${(data as any).hubspot_deal_name ? ` — ${(data as any).hubspot_deal_name}` : ''}`
              : (data as any).source
          } />
          <SidebarRow label="Category" value={data.lead_category} />
          <SidebarRow label="Data Source" value={(data as any).data_source} />
          <SidebarRow label="Identified" value={(data as any).date_identified} />
          <SidebarRow label="Added" value={(data as any).created_at ? new Date((data as any).created_at).toLocaleDateString() : null} />
          <SidebarRow label="Last Sync" value={
            data.last_hubspot_sync_at
              ? new Date(data.last_hubspot_sync_at).toLocaleDateString()
              : null
          } />
          <SidebarRow label="Last Contact" value={
            data.last_contact_date
              ? new Date(data.last_contact_date).toLocaleDateString()
              : null
          } />
          <SidebarRow label="Follow-up Date" value={(data as any).follow_up_date} />
          <SidebarRow label="Added to HS" value={data.date_added_to_hubspot} />
        </SidebarSection>

        {/* Scores */}
        <SidebarSection title="Scores">
          <SidebarRow label="Lead Score" value={data.lead_score} />
          <SidebarRow label="Completeness" value={
            data.data_completeness_score != null
              ? `${Math.round(data.data_completeness_score)}%`
              : null
          } />
        </SidebarSection>

      </Paper>
    </Box>
  )
}

export default LeadCommandCenter
