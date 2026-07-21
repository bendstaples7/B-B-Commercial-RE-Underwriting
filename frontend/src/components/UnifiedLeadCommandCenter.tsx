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
import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CircularProgress,
  Alert,
  Button,
  Box,
  IconButton,
  Typography,
  Paper,
  Snackbar,
  Tooltip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Chip,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import { Link as RouterLink, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import BarChartIcon from '@mui/icons-material/BarChart'
import FormatListBulletedIcon from '@mui/icons-material/FormatListBulleted'
import { commandCenterService, leadTaskService, leadScoreService, queueService } from '@/services/api'
import { entityResolutionApi } from '@/services/entityResolutionApi'
import { leadService } from '@/services/leadApi'
import { multifamilyService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { primaryOwnerDisplayName } from '@/utils/propertyContacts'
import { parseLogActivityParam, buildLeadUrl } from '@/utils/queueLogNavigation'
import { isFromQueueState, fromQueueFromKey, queuePath, SKIP_TRACE_AUTO_ADVANCE_QUEUE_KEYS, type FromQueueState } from '@/utils/fromQueue'
import { scopeRowsToLead, scopeRowsToLeadWithTotal } from '@/utils/leadScopedRows'
import {
  LEAD_WORKSPACE_STALE_MS,
  prefetchAdjacentQueueLeads,
  prefetchLeadWorkspace,
  prefetchQueueNavigation,
} from '@/utils/prefetchLeadWorkspace'
import { ALL_LEAD_STATUSES } from '@/constants/leadStatuses'
import { scoringActionLabel } from '@/constants/scoringRecommendedActions'
import type { CommandCenterPayload, PropertyDetail, LeadTask, LeadTimelineEntry, PropertyScoreResponse, PropertyScoreRecord, OutreachContact, QueueNavigation, LeadStatus, CRMRecommendedAction } from '@/types'
import { LeadScoreBadge } from '@/components/LeadScoreBadge'
import type { ScoreTier } from '@/components/LeadScoreBadge'
import { LeadStatusSelector } from '@/components/LeadStatusSelector'
import { LeadTaskList, type LeadTaskListHandle } from '@/components/LeadTaskList'
import { LeadTimeline } from '@/components/LeadTimeline'
import { LeadBriefingPanel } from '@/components/LeadBriefingPanel'
import { LogActivityModal, type ActivityLogType } from '@/components/LogActivityModal'
import { ScoreBreakdownDialog } from '@/components/ScoreBreakdownDialog'
import { RecommendedActionPanel } from '@/components/RecommendedActionPanel'
import { resolveOutreachContactFromCommandCenter } from '@/utils/outreachContact'
import { outreachContactPlacement } from '@/utils/outreachContactPlacement'
import { LeadDetailTabPanel } from '@/components/lead-detail/LeadDetailTabPanel'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import { BuildingOwnershipSection } from '@/components/BuildingOwnershipSection'
import {
  ccCardSx,
  ccSectionTitleSx,
} from '@/components/lead-detail/commandCenterChrome'
import { SuppressLeadDialog } from '@/components/SuppressLeadDialog'
import {
  enqueueResultSeverity,
  formatEnqueueSummary,
} from '@/utils/formatEnqueueSummary'
import { formatDateOnly } from '@/utils/helpers'

export { ALL_LEAD_STATUSES } from '@/constants/leadStatuses'
export { tabParamToIndex } from '@/components/lead-detail/LeadDetailTabPanel'

export interface UnifiedLeadCommandCenterProps {
  leadId: number
}

// ── Score tier derivation (fallback when no LeadScoreRecord exists yet) ────────

const TIER_RANGE_LABELS: Record<ScoreTier, string> = {
  A: '75–100 (strong fit)',
  B: '60–74 (good fit)',
  C: '40–59 (marginal)',
  D: '0–39 (low priority)',
}

function scoreToTier(score: number): ScoreTier {
  if (score >= 75) return 'A'
  if (score >= 60) return 'B'
  if (score >= 40) return 'C'
  return 'D'
}

function cleanAddressPart(value?: string | null): string {
  return (value || '').trim().replace(/^,+|,+$/g, '').trim()
}

// ── StickyHeader ──────────────────────────────────────────────────────────────
// Requirements: 5.1, 10.1, 10.2

interface StickyHeaderProps {
  leadId: number
  commandCenterData: CommandCenterPayload
  scoreRecord?: PropertyScoreRecord | null
  onStatusChanged: (
    nextStatus: LeadStatus,
    result?: {
      timeline_entry?: LeadTimelineEntry
      lead_score?: number | null
      recommended_action?: string | null
    },
  ) => void | Promise<void>
  onViewFullBreakdown?: () => void
  fromQueue?: FromQueueState | null
}

function formatPropertyAddress(data: CommandCenterPayload): string {
  const street = cleanAddressPart(data.property_street)
  const cityStateZip = [data.property_city, data.property_state, data.property_zip]
    .map(cleanAddressPart)
    .filter(Boolean)
    .join(', ')
  if (street && cityStateZip) return `${street}, ${cityStateZip}`
  return street || cityStateZip || `Lead #${data.id}`
}

function StickyHeader({
  leadId,
  commandCenterData,
  scoreRecord,
  onStatusChanged,
  onViewFullBreakdown,
  fromQueue,
}: StickyHeaderProps) {
  const [scoreDialogOpen, setScoreDialogOpen] = useState(false)
  const navigate = useNavigate()

  const propertyAddress = formatPropertyAddress(commandCenterData)
  const primaryOwner = primaryOwnerDisplayName(
    commandCenterData.contacts,
    commandCenterData.owner_first_name,
    commandCenterData.owner_last_name,
    commandCenterData.organizations,
  )

  const scoreTier = scoreRecord?.score_tier ?? scoreToTier(commandCenterData.lead_score)
  const displayScore = scoreRecord?.total_score ?? commandCenterData.lead_score
  const tierTooltip = `Tier ${scoreTier}: ${TIER_RANGE_LABELS[scoreTier]} — letter grade from total score (0–100)`

  const handleBack = () => {
    if (fromQueue) {
      navigate(queuePath(fromQueue.key))
      return
    }
    navigate(-1)
  }

  return (
    <>
      <Box
        component="header"
        data-testid="sticky-header"
        sx={{
          bgcolor: 'background.paper',
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Box
          sx={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'flex-start',
            gap: { xs: 1, sm: 0 },
            px: { xs: 1, sm: 2 },
            py: 1,
            minHeight: { xs: 'auto', sm: 48 },
          }}
        >
          <IconButton
            data-testid="back-button"
            onClick={handleBack}
            edge="start"
            aria-label={fromQueue ? `Back to ${fromQueue.label}` : 'Go back'}
            sx={{ mr: 0.5, mt: { xs: 0.25, sm: 0 } }}
          >
            <ArrowBackIcon />
          </IconButton>

          <Box sx={{ flexGrow: 1, minWidth: 0, flexBasis: { xs: 'calc(100% - 48px)', sm: 'auto' }, overflow: 'hidden' }} data-testid="sticky-header-address">
            <Typography
              variant="subtitle1"
              fontWeight={700}
              sx={{
                lineHeight: 1.3,
                overflowWrap: 'anywhere',
                wordBreak: 'break-word',
                whiteSpace: { xs: 'normal', sm: 'nowrap' },
              }}
              title={propertyAddress}
            >
              {propertyAddress}
            </Typography>
            {primaryOwner ? (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  lineHeight: 1.2,
                  overflowWrap: 'anywhere',
                  wordBreak: 'break-word',
                  whiteSpace: { xs: 'normal', sm: 'nowrap' },
                }}
                title={primaryOwner}
                data-testid="sticky-header-owner"
              >
                {primaryOwner}
              </Typography>
            ) : null}
          </Box>

          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              flexWrap: 'wrap',
              width: { xs: '100%', sm: 'auto' },
              pl: { xs: 5, sm: 0 },
              justifyContent: { xs: 'flex-start', sm: 'flex-end' },
            }}
          >
            <Tooltip title={scoreRecord ? `${tierTooltip} — click for breakdown` : tierTooltip}>
              <span>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => scoreRecord && setScoreDialogOpen(true)}
                  disabled={!scoreRecord}
                  data-testid="header-lead-score"
                  aria-label="View lead score breakdown"
                  startIcon={<BarChartIcon sx={{ fontSize: 18 }} />}
                  sx={{
                    textTransform: 'none',
                    fontWeight: 600,
                    flexShrink: 0,
                  }}
                >
                  {Math.round(displayScore)} / 100
                  <Box component="span" sx={{ ml: 0.75 }}>
                    <LeadScoreBadge tier={scoreTier} size="small" />
                  </Box>
                </Button>
              </span>
            </Tooltip>

            <LeadStatusSelector
              leadId={leadId}
              status={commandCenterData.lead_status}
              allStatuses={ALL_LEAD_STATUSES}
              onStatusChanged={onStatusChanged}
            />
          </Box>
        </Box>
      </Box>

      {scoreRecord && (
        <ScoreBreakdownDialog
          score={scoreRecord}
          open={scoreDialogOpen}
          onClose={() => setScoreDialogOpen(false)}
          onViewFullBreakdown={onViewFullBreakdown}
        />
      )}
    </>
  )
}

// ── QueueWorkHeader ───────────────────────────────────────────────────────────

interface QueueWorkHeaderProps {
  fromQueue: FromQueueState
  navigation: QueueNavigation | undefined
  isLoading: boolean
  onAdvance: (leadId: number) => void
  onPrefetchLead?: (leadId: number) => void
}

function QueueWorkHeader({
  fromQueue,
  navigation,
  isLoading,
  onAdvance,
  onPrefetchLead,
}: QueueWorkHeaderProps) {
  const navigate = useNavigate()
  const theme = useTheme()
  const isXs = useMediaQuery(theme.breakpoints.down('sm'))
  const positionLabel =
    navigation?.position != null
      ? `${navigation.position} of ${navigation.total}`
      : navigation
        ? `${navigation.total} in queue`
        : '…'

  return (
    <Box
      data-testid="queue-work-header"
      sx={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 0.5,
        px: { xs: 1, sm: 2 },
        py: 0.75,
        bgcolor: 'action.hover',
        borderBottom: 1,
        borderColor: 'divider',
      }}
    >
      <Typography
        variant="body2"
        fontWeight={600}
        sx={{
          flexGrow: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {fromQueue.label}
        <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
          · {isLoading ? '…' : positionLabel}
        </Typography>
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25, ml: 'auto', flexShrink: 0 }}>
        {isXs ? (
          <IconButton
            size="small"
            onClick={() => navigate(queuePath(fromQueue.key))}
            aria-label="Back to queue"
            data-testid="queue-back-to-list"
          >
            <FormatListBulletedIcon fontSize="small" />
          </IconButton>
        ) : (
          <Button
            size="small"
            onClick={() => navigate(queuePath(fromQueue.key))}
            data-testid="queue-back-to-list"
          >
            Back to queue
          </Button>
        )}
        <IconButton
          size="small"
          disabled={!navigation?.prev_id}
          aria-label="Previous in queue"
          data-testid="queue-prev-btn"
          onMouseEnter={() => navigation?.prev_id && onPrefetchLead?.(navigation.prev_id)}
          onFocus={() => navigation?.prev_id && onPrefetchLead?.(navigation.prev_id)}
          onClick={() => navigation?.prev_id && onAdvance(navigation.prev_id)}
        >
          <ChevronLeftIcon />
        </IconButton>
        <IconButton
          size="small"
          disabled={!navigation?.next_id}
          aria-label="Next in queue"
          data-testid="queue-next-btn"
          onMouseEnter={() => navigation?.next_id && onPrefetchLead?.(navigation.next_id)}
          onFocus={() => navigation?.next_id && onPrefetchLead?.(navigation.next_id)}
          onClick={() => navigation?.next_id && onAdvance(navigation.next_id)}
        >
          <ChevronRightIcon />
        </IconButton>
      </Box>
    </Box>
  )
}

// ── Work queue membership strip ──────────────────────────────────────────────

interface WorkQueueMembershipStripProps {
  commandCenterData: CommandCenterPayload
}

/** Always-visible work-queue membership (sidebar is lg+ only). */
function WorkQueueMembershipStrip({ commandCenterData }: WorkQueueMembershipStripProps) {
  const memberships = commandCenterData.work_queues ?? []

  return (
    <Box
      sx={{
        px: { xs: 1, sm: 2 },
        pt: 1,
        display: { xs: 'none', sm: 'flex' },
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 1,
      }}
      data-testid="work-queue-membership-strip"
    >
      <Typography variant="body2" fontWeight={600} sx={{ mr: 0.5 }}>
        Work queues
      </Typography>
      {memberships.length > 0 ? (
        memberships.map((q) => (
          <Chip
            key={q.key}
            component={RouterLink}
            to={q.path}
            clickable
            size="small"
            label={q.label}
            data-testid={`work-queue-strip-${q.key}`}
          />
        ))
      ) : (
        <Typography variant="body2" color="text.secondary" data-testid="work-queue-strip-empty">
          Not in an active work queue
        </Typography>
      )}
    </Box>
  )
}

// ── TasksPanel ────────────────────────────────────────────────────────────────
// Requirements: 7.1, 7.2, 7.3, 7.4, 12.4

interface TasksPanelProps {
  leadId: number
  initialTasks: LeadTask[]
  outreachContact?: OutreachContact | null
  showOutreachContactOnPrimaryTask?: boolean
  missingOutreachChannel?: OutreachContact['channel'] | null
  mailQueueStatus?: 'queued' | 'sent_recently' | null
  upNextToMail?: boolean
  /** Drop Paper chrome when nested inside a shared action card. */
  embedded?: boolean
  onTasksChanged: () => void
  /** Called after a task is successfully completed (for queue auto-advance). */
  onAfterTaskCompleted?: () => void | Promise<void>
}

export interface TasksPanelHandle {
  scrollIntoView: () => void
  openCreateForm: () => void
}

const TasksPanel = React.forwardRef<TasksPanelHandle, TasksPanelProps>(function TasksPanel(
  {
    leadId,
    initialTasks,
    outreachContact,
    showOutreachContactOnPrimaryTask = false,
    missingOutreachChannel = null,
    mailQueueStatus = null,
    upNextToMail = false,
    embedded = false,
    onTasksChanged,
    onAfterTaskCompleted,
  },
  ref,
) {
  const queryClient = useQueryClient()
  const panelRef = useRef<HTMLDivElement>(null)
  const taskListRef = useRef<LeadTaskListHandle>(null)
  const [tasks, setTasks] = useState<LeadTask[]>(() =>
    scopeRowsToLead(initialTasks, leadId, 'tasks'),
  )

  useEffect(() => {
    setTasks(scopeRowsToLead(initialTasks, leadId, 'tasks'))
  }, [leadId, initialTasks])

  React.useImperativeHandle(ref, () => ({
    scrollIntoView: () => {
      const el = panelRef.current
      if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    },
    openCreateForm: () => {
      taskListRef.current?.openCreateForm()
    },
  }))

  // LeadTaskList handles creation internally and calls this with the new task.
  // Replace optimistic placeholder (id=0) when present; otherwise append.
  const handleTaskCreated = (task: LeadTask) => {
    setTasks((prev) => {
      const next = (() => {
        if (prev.some((t) => t.id === 0)) {
          return prev.map((t) => (t.id === 0 ? task : t))
        }
        if (prev.some((t) => t.id === task.id)) {
          return prev.map((t) => (t.id === task.id ? { ...t, ...task } : t))
        }
        return [task, ...prev]
      })()
      return scopeRowsToLead(next, leadId, 'tasks')
    })
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    onTasksChanged()
  }

  const handleTaskUpdated = (task: LeadTask) => {
    setTasks((prev) =>
      scopeRowsToLead(
        prev.map((t) => (t.id === task.id ? { ...t, ...task } : t)),
        leadId,
        'tasks',
      ),
    )
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    onTasksChanged()
  }

  // Called immediately on form submit (before API call) to add a placeholder
  // so the UI grows from N to N+1 optimistically (Requirement 7.2, Property 12).
  const handleOptimisticTaskCreate = (optimisticTask: LeadTask) => {
    setTasks((prev) =>
      scopeRowsToLead([{ ...optimisticTask, lead_id: leadId }, ...prev], leadId, 'tasks'),
    )
  }

  // Called when the create API call fails — roll back the optimistic placeholder
  // (id=0) so a failed create doesn't leave a stale task in the list (Req 7.2).
  const handleOptimisticTaskRevert = () => {
    setTasks(prev => prev.filter(t => t.id !== 0))
  }

  const handleTaskCompleted = async (taskId: number | string) => {
    // Only native tasks (numeric IDs) can be completed from the platform
    if (typeof taskId === 'number') {
      try {
        await leadTaskService.completeTask(leadId, taskId)
      } catch (err) {
        console.error('Failed to complete task:', err)
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        throw err
      }
    }
    setTasks(prev => prev.filter(t => String(t.id) !== String(taskId)))
    queryClient.setQueryData<CommandCenterPayload>(
      ['commandCenter', leadId],
      current => current
        ? {
            ...current,
            open_tasks: current.open_tasks.filter(
              task => String(task.id) !== String(taskId),
            ),
          }
        : current,
    )
    await queryClient.invalidateQueries({
      queryKey: ['commandCenter', leadId],
      refetchType: 'none',
    })
    await onAfterTaskCompleted?.()
  }

  const handleHubSpotTaskDone = async (taskId: number) => {
    setTasks(prev => prev.filter(t => String(t.id) !== String(taskId)))
    queryClient.setQueryData<CommandCenterPayload>(
      ['commandCenter', leadId],
      current => current
        ? {
            ...current,
            open_tasks: current.open_tasks.filter(
              task => String(task.id) !== String(taskId),
            ),
          }
        : current,
    )
    await queryClient.invalidateQueries({
      queryKey: ['commandCenter', leadId],
      refetchType: 'none',
    })
    await onAfterTaskCompleted?.()
  }

  // Tasks are scoped on every write path; pass state through without re-scoping on render.
  return (
    <Box ref={panelRef} data-testid="tasks-panel" sx={embedded ? { p: 0 } : undefined}>
      {embedded ? (
        <LeadTaskList
          ref={taskListRef}
          leadId={leadId}
          tasks={tasks}
          outreachContact={outreachContact}
          showOutreachContactOnPrimaryTask={showOutreachContactOnPrimaryTask}
          missingOutreachChannel={missingOutreachChannel}
          mailQueueStatus={mailQueueStatus}
          upNextToMail={upNextToMail}
          onTaskCreated={handleTaskCreated}
          onTaskUpdated={handleTaskUpdated}
          onTaskCompleted={handleTaskCompleted}
          onHubSpotTaskDone={handleHubSpotTaskDone}
          onOptimisticTaskCreate={handleOptimisticTaskCreate}
          onOptimisticTaskRevert={handleOptimisticTaskRevert}
        />
      ) : (
        <Paper sx={{ p: 2, mb: 2 }}>
          <LeadTaskList
            ref={taskListRef}
            leadId={leadId}
            tasks={tasks}
            outreachContact={outreachContact}
            showOutreachContactOnPrimaryTask={showOutreachContactOnPrimaryTask}
            missingOutreachChannel={missingOutreachChannel}
            mailQueueStatus={mailQueueStatus}
            upNextToMail={upNextToMail}
            onTaskCreated={handleTaskCreated}
            onTaskUpdated={handleTaskUpdated}
            onTaskCompleted={handleTaskCompleted}
            onHubSpotTaskDone={handleHubSpotTaskDone}
            onOptimisticTaskCreate={handleOptimisticTaskCreate}
            onOptimisticTaskRevert={handleOptimisticTaskRevert}
          />
        </Paper>
      )}
    </Box>
  )
})

// ── ActivityPanel ─────────────────────────────────────────────────────────
// Requirements: 8.1, 8.2, 8.3

interface ActivityPanelProps {
  leadId: number
  initialEntries: LeadTimelineEntry[]
  initialTotal: number
  highlightEntryId: number | null
}

export interface ActivityPanelHandle {
  scrollIntoView: () => void
  prependEntry: (entry: LeadTimelineEntry) => void
}

const ACTIVITY_SUCCESS_MESSAGES: Record<ActivityLogType, string> = {
  note: 'Note saved.',
  call: 'Call logged.',
  email: 'Email logged.',
}

function normalizeTimelineEntriesForLead(
  entries: readonly LeadTimelineEntry[],
  leadId: number,
): LeadTimelineEntry[] {
  return entries.map((entry) => ({
    ...entry,
    lead_id: entry.lead_id ?? leadId,
  }))
}

const ActivityPanel = React.forwardRef<ActivityPanelHandle, ActivityPanelProps>(
  function ActivityPanel(
    { leadId, initialEntries, initialTotal, highlightEntryId },
    ref,
  ) {
    const panelRef = useRef<HTMLDivElement>(null)
    const initialScopedEntries = normalizeTimelineEntriesForLead(initialEntries, leadId)
    const [timelineEntries, setTimelineEntries] = useState<LeadTimelineEntry[]>(() =>
      scopeRowsToLead(initialScopedEntries, leadId, 'timeline'),
    )
    const [timelineTotal, setTimelineTotal] = useState(initialTotal)
    const leadIdRef = useRef(leadId)
    leadIdRef.current = leadId
    const timelineEntriesRef = useRef(timelineEntries)
    timelineEntriesRef.current = timelineEntries

    // Drop prior-lead rows entirely when navigating. Only keep optimistic
    // prepends that belong to the *current* lead (same lead_id), then
    // fail-closed filter anything foreign before paint. LeadTimeline is a
    // presenter — scoping ownership stays here.
    React.useEffect(() => {
      const serverEntries = normalizeTimelineEntriesForLead(initialEntries, leadId)
      const serverIds = new Set(serverEntries.map((e) => e.id))
      const optimisticOnly = timelineEntriesRef.current.filter(
        (e) => e.lead_id === leadId && !serverIds.has(e.id),
      )
      const scoped = scopeRowsToLeadWithTotal(
        [...optimisticOnly, ...serverEntries],
        leadId,
        'timeline',
        initialTotal,
      )
      setTimelineEntries(scoped.rows)
      setTimelineTotal(scoped.total)
    }, [leadId, initialEntries, initialTotal])

    React.useImperativeHandle(ref, () => ({
      scrollIntoView: () => {
        const el = panelRef.current
        if (el && typeof el.scrollIntoView === 'function') {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      },
      prependEntry: (entry: LeadTimelineEntry) => {
        const activeLeadId = leadIdRef.current
        // Reject only clearly foreign ids; missing lead_id is treated as current.
        if (entry.lead_id != null && entry.lead_id !== activeLeadId) return
        const normalized: LeadTimelineEntry = {
          ...entry,
          lead_id: entry.lead_id ?? activeLeadId,
        }
        setTimelineEntries((prev) =>
          scopeRowsToLead([normalized, ...prev], activeLeadId, 'timeline'),
        )
        setTimelineTotal((prev) => prev + 1)
      },
    }))

    const handleLoadMore = async (page: number): Promise<{ entries: LeadTimelineEntry[]; total: number }> => {
      const requestedLeadId = leadId
      const result = await commandCenterService.getTimeline(requestedLeadId, page)
      if (requestedLeadId !== leadIdRef.current) {
        return { entries: [], total: 0 }
      }
      const scoped = scopeRowsToLeadWithTotal(
        normalizeTimelineEntriesForLead(result.entries, requestedLeadId),
        requestedLeadId,
        'timeline',
        result.total,
      )
      return {
        entries: scoped.rows,
        total: scoped.total,
      }
    }

    return (
      <Box ref={panelRef} sx={{ mb: 2 }} data-testid="activity-panel">
        <Typography sx={ccSectionTitleSx}>
          Activity
        </Typography>
        <LeadTimeline
          leadId={leadId}
          initialEntries={timelineEntries}
          initialTotal={timelineTotal}
          onLoadMore={handleLoadMore}
          highlightEntryId={highlightEntryId}
        />
      </Box>
    )
  }
)

// ── Main component ─────────────────────────────────────────────────────────────

export function UnifiedLeadCommandCenter({ leadId }: UnifiedLeadCommandCenterProps) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const fromQueue = useMemo(() => {
    const state = location.state as { fromQueue?: unknown } | null
    if (isFromQueueState(state?.fromQueue)) return state.fromQueue
    return fromQueueFromKey(searchParams.get('queue'))
  }, [location.state, searchParams])
  const visitedHistory = fromQueue?.visitedHistory ?? []
  const forwardStack = fromQueue?.forwardStack ?? []

  const {
    data: commandCenterData,
    isLoading: commandCenterLoading,
    error: commandCenterError,
  } = useQuery<CommandCenterPayload, Error>({
    queryKey: ['commandCenter', leadId],
    queryFn: () => commandCenterService.getCommandCenter(leadId),
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })
  const openTasks = useMemo(
    () => commandCenterData?.open_tasks ?? [],
    [commandCenterData?.open_tasks],
  )

  const {
    data: queueNavigation,
    isLoading: queueNavLoading,
  } = useQuery<QueueNavigation>({
    queryKey: ['queue-navigation', fromQueue?.key, fromQueue?.outreach ?? null, leadId],
    queryFn: () =>
      queueService.getNavigation(fromQueue!.key, leadId, {
        outreach: fromQueue?.outreach,
      }),
    enabled: !!fromQueue,
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })
  const sessionQueueNavigation = queueNavigation
    ? {
        ...queueNavigation,
        prev_id: visitedHistory.at(-1) ?? queueNavigation.prev_id,
        next_id: forwardStack.at(-1) ?? queueNavigation.next_id,
      }
    : queueNavigation

  const {
    data: scoreData,
    isLoading: scoreLoading,
  } = useQuery<PropertyScoreResponse>({
    queryKey: ['leadScore', leadId],
    queryFn: async () => {
      const response = await leadScoreService.getLeadScore(leadId)
      return response.data
    },
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })

  const {
    data: leadData,
    isLoading: leadLoading,
    isError: leadDetailError,
  } = useQuery<PropertyDetail, Error>({
    queryKey: ['lead', leadId],
    queryFn: () => leadService.getLeadDetail(leadId),
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })

  const prefetchQueueLead = useCallback(
    (targetLeadId: number) => {
      prefetchLeadWorkspace(queryClient, targetLeadId)
      if (fromQueue) {
        prefetchQueueNavigation(queryClient, fromQueue.key, targetLeadId, {
          outreach: fromQueue.outreach,
        })
      }
    },
    [queryClient, fromQueue],
  )

  useEffect(() => {
    if (!fromQueue || !queueNavigation) return
    prefetchAdjacentQueueLeads(
      queryClient,
      fromQueue.key,
      queueNavigation.prev_id,
      queueNavigation.next_id,
      { outreach: fromQueue.outreach },
    )
  }, [fromQueue, queueNavigation, queryClient])

  // Deep-link handling for the `?tab=` query param. The TabPanel selects the
  // tab named by the param (info/score/enrichment/marketing/analysis/contacts).
  // There is no "timeline" tab — the activity timeline lives in the always-
  // visible ActivityPanel above the tabs — so the Needs Review queue's "View
  // Activity" deep-link (?tab=timeline) instead scrolls the ActivityPanel into
  // view once the data has loaded and the panel has rendered.
  const tabParam = searchParams.get('tab')
  const activityRef = useRef<ActivityPanelHandle>(null)
  const tasksPanelRef = useRef<TasksPanelHandle>(null)
  const showLead = !!commandCenterData && !commandCenterError
  const [activityModal, setActivityModal] = useState<ActivityLogType | null>(null)
  const [highlightEntryId, setHighlightEntryId] = useState<number | null>(null)
  const [activitySnackbar, setActivitySnackbar] = useState<{
    open: boolean
    message: string
    severity?: 'success' | 'warning' | 'error'
    linkTo?: string
    linkLabel?: string
  }>({
    open: false,
    message: '',
  })
  /** After staging mail from a work queue — prompt to continue to next lead. */
  const [mailContinuePrompt, setMailContinuePrompt] = useState(false)
  const [suppressDialogOpen, setSuppressDialogOpen] = useState(false)
  const [dncDialogOpen, setDncDialogOpen] = useState(false)
  const [dncPending, setDncPending] = useState(false)
  const [dncError, setDncError] = useState<string | null>(null)

  const advanceInQueue = useCallback(
    (nextLeadId: number) => {
      if (!fromQueue) return
      setMailContinuePrompt(false)
      const isBack = visitedHistory.at(-1) === nextLeadId
      const isForward = forwardStack.at(-1) === nextLeadId
      const nextQueueState: FromQueueState = {
        ...fromQueue,
        visitedHistory: isBack
          ? visitedHistory.slice(0, -1)
          : [...visitedHistory, leadId],
        forwardStack: isBack
          ? [...forwardStack, leadId]
          : isForward
            ? forwardStack.slice(0, -1)
            : [],
      }
      navigate(buildLeadUrl(nextLeadId, fromQueue.key), { state: { fromQueue: nextQueueState } })
    },
    [fromQueue, forwardStack, leadId, navigate, visitedHistory],
  )

  const exitQueueCaughtUp = useCallback(() => {
    if (!fromQueue) return
    setMailContinuePrompt(false)
    navigate(queuePath(fromQueue.key))
    setActivitySnackbar({
      open: true,
      message: 'Queue caught up.',
    })
  }, [fromQueue, navigate])

  const advanceAfterTaskComplete = useCallback(async (snapshottedNextId?: number | null) => {
    if (!fromQueue) return
    const queueListKey = `queue-${fromQueue.key}`
    // Refresh list/counts before leaving so Back lands on fresh data; clear
    // cache so remount shows QueueLoadingState instead of stale rows.
    await queryClient.invalidateQueries({
      queryKey: [queueListKey],
      refetchType: 'all',
    })
    await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    if (fromQueue.key === 'todays-action') {
      await queryClient.invalidateQueries({
        queryKey: ['queue-todays-action-outreach-counts'],
        refetchType: 'all',
      })
    }
    queryClient.removeQueries({ queryKey: [queueListKey] })

    try {
      // The neighbour must be captured before completion removes this lead.
      // A fresh queue query can otherwise return the queue head, skipping work.
      if (snapshottedNextId) {
        advanceInQueue(snapshottedNextId)
      } else {
        const nav = await queueService.getNavigation(fromQueue.key, leadId, {
          outreach: fromQueue.outreach,
        })
        if (nav.next_id) {
          advanceInQueue(nav.next_id)
        } else {
          exitQueueCaughtUp()
        }
      }
    } catch {
      exitQueueCaughtUp()
    }
  }, [fromQueue, leadId, advanceInQueue, exitQueueCaughtUp, queryClient])

  const handleStatusChanged = useCallback(async (
    nextStatus?: LeadStatus,
    result?: {
      timeline_entry?: LeadTimelineEntry
      lead_score?: number | null
      recommended_action?: string | null
    },
  ) => {
    // Do not refetch Command Center here. Its GET used to perform stale HubSpot
    // task reconciliation, which must never be a side effect of changing lead
    // status. Prefer the PATCH payload (status + score + timeline entry).
    queryClient.setQueryData<CommandCenterPayload>(
      ['commandCenter', leadId],
      (current) => {
        if (!current) return current
        const next = { ...current }
        if (nextStatus) next.lead_status = nextStatus
        if (result?.lead_score !== undefined) {
          next.lead_score = result.lead_score ?? 0
        }
        if (result && result.recommended_action !== undefined) {
          const action = result.recommended_action as CRMRecommendedAction | null
          next.recommended_action = {
            ...next.recommended_action,
            value: action,
            label: action ? scoringActionLabel(action) : null,
            explanation: null,
            recommended_contact_method: null,
            outreach_contact: null,
            winning_rule: null,
            winning_rule_label: null,
            signals: {},
          }
        }
        return next
      },
    )
    if (result?.timeline_entry) {
      activityRef.current?.prependEntry(result.timeline_entry)
      setHighlightEntryId(result.timeline_entry.id)
      window.setTimeout(() => setHighlightEntryId(null), 2000)
    }
    // Header prefers leadScore history over CC lead_score — must refresh or score looks stuck.
    await queryClient.invalidateQueries({ queryKey: ['leadScore', leadId] })
    await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    if (!fromQueue) return
    await queryClient.invalidateQueries({ queryKey: ['queue-navigation', fromQueue.key] })
    await queryClient.invalidateQueries({ queryKey: [`queue-${fromQueue.key}`] })
    // Stay on this lead after status change — only task/activity completion advances the queue.
  }, [queryClient, leadId, fromQueue])

  const handleActivitySaved = useCallback((
    entry: LeadTimelineEntry,
    type: ActivityLogType,
    meta?: {
      completedTaskId?: number
      completedHubSpotTaskId?: number
      warning?: string
    },
  ) => {
    activityRef.current?.prependEntry(entry)
    setHighlightEntryId(entry.id)
    setActivitySnackbar({
      open: true,
      message: meta?.warning ?? ACTIVITY_SUCCESS_MESSAGES[type],
      severity: meta?.warning ? 'warning' : 'success',
    })
    setActivityModal(null)
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    window.setTimeout(() => setHighlightEntryId(null), 2000)
    if (
      fromQueue
      && (meta?.completedTaskId != null || meta?.completedHubSpotTaskId != null)
    ) {
      void advanceAfterTaskComplete(queueNavigation?.next_id)
    }
  }, [queryClient, leadId, fromQueue, advanceAfterTaskComplete, queueNavigation?.next_id])

  const handleRaAction = useCallback(async (action: string) => {
    switch (action) {
      case 'log_call':
        setActivityModal('call')
        return
      case 'log_note':
        setActivityModal('note')
        return
      case 'log_email':
        setActivityModal('email')
        return
      case 'create_task':
        tasksPanelRef.current?.scrollIntoView()
        window.setTimeout(() => tasksPanelRef.current?.openCreateForm(), 300)
        return
      case 'add_to_mail_batch': {
        const result = await openLetterService.enqueue([leadId], fromQueue?.key ?? 'command-center')
        setActivitySnackbar({
          open: true,
          message: formatEnqueueSummary(result),
          severity: enqueueResultSeverity(result),
          ...(result.added > 0
            ? { linkTo: '/queues/ready-to-mail', linkLabel: 'View staged batch' }
            : {}),
        })
        if (result.added > 0 && fromQueue) {
          setMailContinuePrompt(true)
          await queryClient.invalidateQueries({
            queryKey: [`queue-${fromQueue.key}`],
            refetchType: 'all',
          })
          if (fromQueue.key === 'todays-action') {
            await queryClient.invalidateQueries({
              queryKey: ['queue-todays-action-outreach-counts'],
              refetchType: 'all',
            })
          }
          await queryClient.invalidateQueries({ queryKey: ['queue-navigation', fromQueue.key] })
        }
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        await queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
        await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
        return
      }
      case 'research_property': {
        const el = document.getElementById('building-ownership-section')
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
        return
      }
      case 'run_analysis': {
        navigate(`${location.pathname}?tab=analysis`, { replace: true })
        if (leadLoading) {
          setActivitySnackbar({
            open: true,
            message: 'Loading lead details before starting analysis…',
          })
          return
        }
        if (leadDetailError || leadData == null) {
          setActivitySnackbar({
            open: true,
            message: 'Could not load lead details — refresh and try again before starting analysis.',
          })
          return
        }
        const units = leadData.units
        if (units != null && units >= 5) {
          const deal = await multifamilyService.createDeal({
            property_address: leadData.property_street ?? '',
            unit_count: units,
            purchase_price: 0,
            close_date: new Date().toISOString().split('T')[0],
          })
          await multifamilyService.linkDealToLead(deal.id, leadId)
          navigate(`/multifamily/deals/${deal.id}`)
        } else {
          const result = await leadService.analyzeLead(leadId)
          navigate(`/analysis/${result.session_id}`)
        }
        return
      }
      case 'skip_trace':
      case 'move_to_skip_trace': {
        // Complete current work, including dated recent-sale verify tasks.
        // Never pass the undated "Awaiting skip trace" handoff as complete_task_id.
        const isUndatedSkipHandoff = (task: LeadTask) => (
          task.task_type === 'skip_trace_owner'
          && !task.due_date
          && (task.title || '').trim().toLowerCase() === 'awaiting skip trace'
        )
        const completable = openTasks.find(
          (t) => (
            (t.status === 'open' || t.status === 'overdue')
            && !isUndatedSkipHandoff(t)
          ),
        )
        const rawId = completable?.id
        const completeTaskId =
          rawId == null || rawId === ''
            ? undefined
            : Number(rawId)
        const result = await commandCenterService.moveToSkipTrace(
          leadId,
          completeTaskId != null && Number.isFinite(completeTaskId)
            ? completeTaskId
            : undefined,
        )
        // Apply the returned status and task transition immediately. Unlike a
        // normal status PATCH, this action also completes current work and
        // creates/reuses the skip-trace handoff task.
        queryClient.setQueryData<CommandCenterPayload>(
          ['commandCenter', leadId],
          (current) => {
            if (!current) return current
            const remainingTasks = current.open_tasks.filter(
              (task) => (
                result.completed_task_id == null
                || Number(task.id) !== result.completed_task_id
              ),
            )
            const hasHandoff = remainingTasks.some(
              (task) => Number(task.id) === result.skip_trace_task_id,
            )
            const handoffTask: LeadTask = {
              id: result.skip_trace_task_id,
              lead_id: leadId,
              task_type: 'skip_trace_owner',
              title: 'Awaiting skip trace',
              status: 'open',
              due_date: null,
              created_at: new Date().toISOString(),
              completed_at: null,
              created_by: 'system',
              source: 'native',
            }
            return {
              ...current,
              lead_status: result.lead_status as LeadStatus,
              needs_skip_trace: true,
              open_tasks: hasHandoff
                ? remainingTasks.map((task) => (
                  Number(task.id) === result.skip_trace_task_id
                    ? {
                        ...task,
                        title: 'Awaiting skip trace',
                        due_date: null,
                      }
                    : task
                ))
                : [...remainingTasks, handoffTask],
            }
          },
        )
        setActivitySnackbar({
          open: true,
          message: result.already_done
            ? (result.reason_code === 'already_awaiting_skip_trace'
              ? 'Already awaiting skip trace'
              : 'Already in Skip Trace pipeline')
            : result.completed_task_id
              ? 'Current task completed and lead moved to Skip Trace'
              : 'Lead moved to Skip Trace',
        })
        if (!result.already_done) {
          await handleStatusChanged(result.lead_status as LeadStatus, {
            lead_score: result.lead_score,
            recommended_action: result.recommended_action,
          })
          // Status change alone stays put; Move to Skip Trace completes current
          // work and drops the lead from due-work queues — advance like task done.
          if (fromQueue && SKIP_TRACE_AUTO_ADVANCE_QUEUE_KEYS.has(fromQueue.key)) {
            await advanceAfterTaskComplete(queueNavigation?.next_id)
          }
        }
        return
      }
      case 'adjust_for_recent_sale': {
        const currentTask = openTasks[0]
        const result = await leadService.adjustForRecentSale(
          leadId,
          currentTask?.id == null ? undefined : Number(currentTask.id),
          currentTask?.hubspot_task_id,
        )
        setActivitySnackbar({
          open: true,
          message: result.task_created
            ? `Task created for ${formatDateOnly(result.due_date)}`
            : `Task moved to ${formatDateOnly(result.due_date)}`,
        })
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
        return
      }
      case 'add_contact_info':
        navigate(`${location.pathname}?tab=contacts`, { replace: true })
        window.setTimeout(() => {
          document.querySelector('[data-testid="tab-panel"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }, 100)
        return
      case 'search_property':
        navigate(`/queues/missing-property-match?leadId=${leadId}`)
        return
      case 'research_pin':
        await leadTaskService.createTask(leadId, {
          title: 'Research missing PIN',
          task_type: 'research_missing_pin',
        })
        tasksPanelRef.current?.scrollIntoView()
        setActivitySnackbar({ open: true, message: 'Research PIN task created' })
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        return
      case 'suppress':
        setSuppressDialogOpen(true)
        return
      case 'do_not_contact':
        setDncDialogOpen(true)
        return
      default:
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    }
  }, [
    queryClient,
    leadId,
    navigate,
    location.pathname,
    leadData,
    leadLoading,
    leadDetailError,
    openTasks,
    fromQueue,
    handleStatusChanged,
    advanceAfterTaskComplete,
    queueNavigation?.next_id,
  ])

  const handleCreateTask = useCallback(() => {
    tasksPanelRef.current?.scrollIntoView()
    window.setTimeout(() => tasksPanelRef.current?.openCreateForm(), 300)
  }, [])

  const handleViewScoreBreakdown = useCallback(() => {
    navigate(`${location.pathname}?tab=score`, { replace: true })
    window.setTimeout(() => {
      document.querySelector('[data-testid="tab-panel"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 100)
  }, [navigate, location.pathname])

  const handleViewSaleHistory = useCallback(() => {
    navigate(`${location.pathname}?tab=info#info-sale-history`, { replace: true })
    window.setTimeout(() => {
      document.getElementById('info-sale-history')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    }, 120)
  }, [navigate, location.pathname])

  useEffect(() => {
    if (!showLead) return
    if (tabParam?.toLowerCase() !== 'timeline') return
    activityRef.current?.scrollIntoView()
  }, [showLead, tabParam])

  useEffect(() => {
    setMailContinuePrompt(false)
    setHighlightEntryId(null)
    setActivityModal(null)
    setSuppressDialogOpen(false)
    setDncDialogOpen(false)
    setDncPending(false)
    setDncError(null)
    setActivitySnackbar({ open: false, message: '' })
  }, [leadId])

  useEffect(() => {
    if (!showLead) return
    const logType = parseLogActivityParam(searchParams.get('log'))
    if (!logType) return
    setActivityModal(logType)
    const next = new URLSearchParams(searchParams)
    next.delete('log')
    const search = next.toString()
    navigate(
      { pathname: location.pathname, search: search ? `?${search}` : '' },
      { replace: true, state: location.state },
    )
  }, [showLead, searchParams, navigate, location.pathname, location.state])

  if (commandCenterLoading && !commandCenterData) {
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
  const outreachContact = resolveOutreachContactFromCommandCenter(commandCenterData!)
  const recommendedActionValue = commandCenterData!.recommended_action?.value ?? null
  const contactMethod = commandCenterData!.recommended_action?.recommended_contact_method ?? null
  const placement = outreachContactPlacement(openTasks, outreachContact, recommendedActionValue)
  const missingOutreachChannel =
    placement !== 'none' && contactMethod && !outreachContact
      ? (contactMethod as OutreachContact['channel'])
      : null
  const recommendedActionWithContact = {
    ...commandCenterData!.recommended_action,
    outreach_contact: outreachContact,
  }

  return (
    <Box
      data-testid="unified-lead-command-center"
      sx={{
        maxWidth: '100%',
        minWidth: 0,
        boxSizing: 'border-box',
      }}
    >
      {/* Queue work bar + sticky lead header — no overflow clipping on sticky ancestors */}
      <Box sx={{ position: 'sticky', top: 0, zIndex: 100, bgcolor: 'background.default', maxWidth: '100%' }}>
        {fromQueue && (
          <QueueWorkHeader
            fromQueue={fromQueue}
            navigation={sessionQueueNavigation}
            isLoading={queueNavLoading}
            onAdvance={advanceInQueue}
            onPrefetchLead={prefetchQueueLead}
          />
        )}
        {mailContinuePrompt && fromQueue && (
          <Alert
            severity="success"
            data-testid="mail-continue-banner"
            onClose={() => setMailContinuePrompt(false)}
            sx={{
              borderRadius: 0,
              borderBottom: 1,
              borderColor: 'divider',
            }}
            action={
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0 }}>
                <Button
                  color="inherit"
                  size="small"
                  variant="outlined"
                  component={RouterLink}
                  to="/queues/ready-to-mail"
                  data-testid="mail-continue-view-staged-batch"
                  sx={{ bgcolor: 'background.paper' }}
                >
                  View staged batch
                </Button>
                {queueNavLoading ? (
                  <CircularProgress size={18} color="inherit" sx={{ mx: 1 }} />
                ) : queueNavigation?.next_id ? (
                  <Button
                    color="inherit"
                    size="small"
                    variant="outlined"
                    data-testid="mail-continue-next-lead"
                    onClick={() => { void advanceAfterTaskComplete(queueNavigation?.next_id) }}
                  >
                    Next lead
                  </Button>
                ) : (
                  <Button
                    color="inherit"
                    size="small"
                    variant="outlined"
                    data-testid="mail-continue-back-to-queue"
                    onClick={() => {
                      setMailContinuePrompt(false)
                      navigate(queuePath(fromQueue.key))
                    }}
                  >
                    Back to queue
                  </Button>
                )}
              </Box>
            }
          >
            {queueNavLoading || queueNavigation?.next_id
              ? 'Staged for the next mail batch.'
              : 'Staged. You’re caught up.'}
          </Alert>
        )}
        <StickyHeader
          leadId={leadId}
          commandCenterData={commandCenterData!}
          scoreRecord={scoreData?.latest}
          onStatusChanged={handleStatusChanged}
          onViewFullBreakdown={handleViewScoreBreakdown}
          fromQueue={fromQueue}
        />
      </Box>

      <WorkQueueMembershipStrip commandCenterData={commandCenterData!} />

      {/* Two-column flex layout: activity column (left) + property sidebar (right, hidden below lg) */}
      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', p: { xs: 0, sm: 2 }, maxWidth: '100%', minWidth: 0 }}>
        {/* Activity column — order: RecommendedActionPanel → TasksPanel → ActivityPanel → TabPanel */}
        <Box sx={{ flex: 1, minWidth: 0, maxWidth: '100%', px: { xs: 0.5, sm: 0 }, overflow: 'hidden' }}>
          {/* One card: recommended action + quick actions + open tasks */}
          <Paper sx={ccCardSx} data-testid="lead-action-section">
            <Typography sx={{ ...ccSectionTitleSx, mb: 1.5 }}>
              Next steps
            </Typography>
            <RecommendedActionPanel
              recommendedAction={recommendedActionWithContact}
              leadStatus={commandCenterData!.lead_status}
              openTasks={openTasks}
              mailQueueStatus={commandCenterData!.mail_queue_status ?? null}
              isMailable={commandCenterData!.is_mailable ?? false}
              mailEligible={commandCenterData!.mail_eligible}
              mailIneligibleReason={commandCenterData!.mail_ineligible_reason}
              mailEligibleDate={commandCenterData!.mail_eligible_date}
              showOutreachContact={placement === 'recommended_action'}
              embedded
              entityResearch={commandCenterData!.entity_research ?? null}
              onRefreshEntityResearch={async () => {
                await entityResolutionApi.resolve(leadId, { action: 'resolve', async: false })
                await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
              }}
              onAction={handleRaAction}
              onCreateTask={handleCreateTask}
            />
            <Box
              sx={{
                borderTop: 1,
                borderColor: 'divider',
                mt: 2,
                pt: 2,
              }}
            >
              <TasksPanel
                ref={tasksPanelRef}
                leadId={leadId}
                initialTasks={openTasks}
                outreachContact={outreachContact}
                showOutreachContactOnPrimaryTask={placement === 'primary_task'}
                missingOutreachChannel={missingOutreachChannel}
                mailQueueStatus={commandCenterData!.mail_queue_status ?? null}
                upNextToMail={Boolean(commandCenterData!.up_next_to_mail)}
                embedded
                onTasksChanged={() => queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })}
                onAfterTaskCompleted={fromQueue ? () => { void advanceAfterTaskComplete(queueNavigation?.next_id) } : undefined}
              />
            </Box>
          </Paper>

          <PropertySidebar
            variant="inline"
            commandCenterData={commandCenterData!}
            onViewSaleHistory={handleViewSaleHistory}
          />

          <BuildingOwnershipSection
            leadId={leadId}
            commandCenterData={commandCenterData!}
          />

          <LeadBriefingPanel
            leadId={leadId}
            initialBriefing={commandCenterData!.quick_briefing ?? null}
          />

          {/* ActivityPanel — third in ActivityColumn (Req 8.1–8.3) */}
          <ActivityPanel
            ref={activityRef}
            leadId={leadId}
            initialEntries={commandCenterData!.timeline.entries}
            initialTotal={commandCenterData!.timeline.total}
            highlightEntryId={highlightEntryId}
          />

          {/* TabPanel — fourth in ActivityColumn (Req 9.1–9.6) */}
          {leadData ? (
            <LeadDetailTabPanel
              leadId={leadId}
              leadData={leadData}
              commandCenterData={commandCenterData!}
              scoreData={scoreData}
              scoreLoading={scoreLoading}
            />
          ) : leadLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress size={28} aria-label="Loading property details" />
            </Box>
          ) : null}
        </Box>

        {/* Property sidebar — sticky, hidden below lg breakpoint (Req 11.1–11.5) */}
        <PropertySidebar
          commandCenterData={commandCenterData!}
          onViewSaleHistory={handleViewSaleHistory}
        />
      </Box>

      <LogActivityModal
        open={activityModal != null}
        activityType={activityModal}
        leadId={leadId}
        openTasks={openTasks}
        onClose={() => setActivityModal(null)}
        onSaved={handleActivitySaved}
      />

      <SuppressLeadDialog
        open={suppressDialogOpen}
        onClose={() => setSuppressDialogOpen(false)}
        onConfirm={async () => {
          await commandCenterService.suppress(leadId)
          setSuppressDialogOpen(false)
          setActivitySnackbar({ open: true, message: 'Lead suppressed' })
          await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
          await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
        }}
      />

      <Dialog
        open={dncDialogOpen}
        onClose={dncPending ? undefined : () => {
          setDncDialogOpen(false)
          setDncError(null)
        }}
      >
        <DialogTitle>Mark as Do Not Contact?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This lead will be removed from active outreach queues and marked do not contact.
          </DialogContentText>
          {dncError && (
            <DialogContentText color="error" sx={{ mt: 1 }} data-testid="dnc-error">
              {dncError}
            </DialogContentText>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDncDialogOpen(false)} disabled={dncPending}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            disabled={dncPending}
            onClick={async () => {
              setDncPending(true)
              setDncError(null)
              try {
                await commandCenterService.doNotContact(leadId)
                setDncDialogOpen(false)
                setActivitySnackbar({ open: true, message: 'Lead marked do not contact' })
                await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
                await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
              } catch (err) {
                console.error('[UnifiedLeadCommandCenter] DNC failed:', err)
                setDncError(err instanceof Error ? err.message : 'Failed to mark do not contact. Please try again.')
              } finally {
                setDncPending(false)
              }
            }}
          >
            {dncPending ? 'Updating…' : 'Mark DNC'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={activitySnackbar.open}
        autoHideDuration={4000}
        onClose={() => setActivitySnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        data-testid="activity-success-snackbar"
      >
        <Alert
          severity={activitySnackbar.severity ?? 'success'}
          onClose={() => setActivitySnackbar((s) => ({ ...s, open: false }))}
          data-testid="activity-success-alert"
          action={
            activitySnackbar.linkTo ? (
              <Button
                color="inherit"
                size="small"
                variant="outlined"
                component={RouterLink}
                to={activitySnackbar.linkTo}
                data-testid="activity-success-link"
                sx={{ bgcolor: 'background.paper' }}
              >
                {activitySnackbar.linkLabel ?? 'View'}
              </Button>
            ) : undefined
          }
        >
          {activitySnackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  )
}
