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
  AppBar,
  Toolbar,
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
} from '@mui/material'
import { Link as RouterLink, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import BarChartIcon from '@mui/icons-material/BarChart'
import { commandCenterService, leadTaskService, leadScoreService, queueService } from '@/services/api'
import { leadService } from '@/services/leadApi'
import { multifamilyService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { deriveQueueContext } from '@/utils/deriveQueueContext'
import { parseLogActivityParam, buildLeadUrl } from '@/utils/queueLogNavigation'
import { isFromQueueState, fromQueueFromKey, queuePath, type FromQueueState } from '@/utils/fromQueue'
import {
  LEAD_WORKSPACE_STALE_MS,
  prefetchAdjacentQueueLeads,
  prefetchLeadWorkspace,
  prefetchQueueNavigation,
} from '@/utils/prefetchLeadWorkspace'
import { ALL_LEAD_STATUSES } from '@/constants/leadStatuses'
import type { CommandCenterPayload, PropertyDetail, LeadTask, LeadTimelineEntry, PropertyScoreResponse, PropertyScoreRecord, OutreachContact, QueueNavigation } from '@/types'
import { LeadScoreBadge } from '@/components/LeadScoreBadge'
import type { ScoreTier } from '@/components/LeadScoreBadge'
import { LeadStatusSelector } from '@/components/LeadStatusSelector'
import { LeadTaskList, type LeadTaskListHandle } from '@/components/LeadTaskList'
import { LeadTimeline } from '@/components/LeadTimeline'
import { LogActivityModal, type ActivityLogType } from '@/components/LogActivityModal'
import { ScoreBreakdownDialog } from '@/components/ScoreBreakdownDialog'
import { RecommendedActionPanel } from '@/components/RecommendedActionPanel'
import { resolveOutreachContactFromCommandCenter } from '@/utils/outreachContact'
import { outreachContactPlacement } from '@/utils/outreachContactPlacement'
import { LeadDetailTabPanel } from '@/components/lead-detail/LeadDetailTabPanel'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import { BuildingOwnershipReviewDrawer } from '@/components/BuildingOwnershipReviewDrawer'
import { SuppressLeadDialog } from '@/components/SuppressLeadDialog'

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

// ── StickyHeader ──────────────────────────────────────────────────────────────
// Requirements: 5.1, 10.1, 10.2

interface StickyHeaderProps {
  leadId: number
  commandCenterData: CommandCenterPayload
  scoreRecord?: PropertyScoreRecord | null
  onStatusChanged: () => void
  onViewFullBreakdown?: () => void
  fromQueue?: FromQueueState | null
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
      <AppBar position="static" color="default" elevation={1}>
        <Toolbar>
          <IconButton
            data-testid="back-button"
            onClick={handleBack}
            edge="start"
            aria-label={fromQueue ? `Back to ${fromQueue.label}` : 'Go back'}
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

          {/* Lead score — opens breakdown dialog */}
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
                  mr: 2,
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
        </Toolbar>
      </AppBar>

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
        gap: 1,
        px: 2,
        py: 1,
        bgcolor: 'action.hover',
        borderBottom: 1,
        borderColor: 'divider',
      }}
    >
      <Typography variant="body2" fontWeight={600} sx={{ flexGrow: 1 }}>
        {fromQueue.label}
        <Typography component="span" variant="body2" color="text.secondary" sx={{ ml: 1 }}>
          · {isLoading ? '…' : positionLabel}
        </Typography>
      </Typography>
      <Button
        size="small"
        onClick={() => navigate(queuePath(fromQueue.key))}
        data-testid="queue-back-to-list"
      >
        Back to queue
      </Button>
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
  outreachContact?: OutreachContact | null
  showOutreachContactOnPrimaryTask?: boolean
  missingOutreachChannel?: OutreachContact['channel'] | null
  mailQueueStatus?: 'queued' | 'sent_recently' | null
  upNextToMail?: boolean
  onTasksChanged: () => void
  /** Called after a task is successfully completed (for queue auto-advance). */
  onAfterTaskCompleted?: () => void
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
    onTasksChanged,
    onAfterTaskCompleted,
  },
  ref,
) {
  const queryClient = useQueryClient()
  const panelRef = useRef<HTMLDivElement>(null)
  const taskListRef = useRef<LeadTaskListHandle>(null)
  const [tasks, setTasks] = useState<LeadTask[]>(initialTasks)
  const tasksRef = useRef<LeadTask[]>(initialTasks)

  useEffect(() => {
    setTasks(initialTasks)
    tasksRef.current = initialTasks
  }, [initialTasks])

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
        onAfterTaskCompleted?.()
      } catch (err) {
        // Rollback from snapshot
        setTasks(snapshot)
        console.error('Failed to complete task:', err)
      }
    } else {
      // HubSpot tasks are completed in LeadTaskList before this callback
      queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      onTasksChanged()
      onAfterTaskCompleted?.()
    }
  }

  return (
    <Paper ref={panelRef} sx={{ p: 2, mb: 2 }} data-testid="tasks-panel">
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
        onTaskCompleted={handleTaskCompleted}
        onOptimisticTaskCreate={handleOptimisticTaskCreate}
        onOptimisticTaskRevert={handleOptimisticTaskRevert}
      />
    </Paper>
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

const ActivityPanel = React.forwardRef<ActivityPanelHandle, ActivityPanelProps>(
  function ActivityPanel(
    { leadId, initialEntries, initialTotal, highlightEntryId },
    ref,
  ) {
    const panelRef = useRef<HTMLDivElement>(null)
    const [timelineEntries, setTimelineEntries] = useState<LeadTimelineEntry[]>(initialEntries)
    const [timelineTotal, setTimelineTotal] = useState(initialTotal)

    React.useEffect(() => {
      setTimelineEntries((prev) => {
        const serverIds = new Set(initialEntries.map((e) => e.id))
        const optimisticOnly = prev.filter((e) => !serverIds.has(e.id))
        return [...optimisticOnly, ...initialEntries]
      })
      setTimelineTotal(initialTotal)
    }, [initialEntries, initialTotal])

    React.useImperativeHandle(ref, () => ({
      scrollIntoView: () => {
        const el = panelRef.current
        if (el && typeof el.scrollIntoView === 'function') {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
      },
      prependEntry: (entry: LeadTimelineEntry) => {
        setTimelineEntries(prev => [entry, ...prev])
        setTimelineTotal(prev => prev + 1)
      },
    }))

    const handleLoadMore = async (page: number): Promise<{ entries: LeadTimelineEntry[]; total: number }> => {
      const result = await commandCenterService.getTimeline(leadId, page)
      return { entries: result.entries, total: result.total }
    }

    return (
      <Box ref={panelRef} sx={{ mb: 2, overflow: 'auto' }} data-testid="activity-panel">
        <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 1 }}>
          Activity History
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

  const {
    data: commandCenterData,
    isLoading: commandCenterLoading,
    error: commandCenterError,
  } = useQuery<CommandCenterPayload, Error>({
    queryKey: ['commandCenter', leadId],
    queryFn: () => commandCenterService.getCommandCenter(leadId),
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })

  const {
    data: queueNavigation,
    isLoading: queueNavLoading,
  } = useQuery<QueueNavigation>({
    queryKey: ['queue-navigation', fromQueue?.key, leadId],
    queryFn: () => queueService.getNavigation(fromQueue!.key, leadId),
    enabled: !!fromQueue,
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })

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
  } = useQuery<PropertyDetail, Error>({
    queryKey: ['lead', leadId],
    queryFn: () => leadService.getLeadDetail(leadId),
    staleTime: LEAD_WORKSPACE_STALE_MS,
  })

  const prefetchQueueLead = useCallback(
    (targetLeadId: number) => {
      prefetchLeadWorkspace(queryClient, targetLeadId)
      if (fromQueue) {
        prefetchQueueNavigation(queryClient, fromQueue.key, targetLeadId)
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
    linkTo?: string
    linkLabel?: string
  }>({
    open: false,
    message: '',
  })
  const [buildingOwnershipOpen, setBuildingOwnershipOpen] = useState(false)
  const [suppressDialogOpen, setSuppressDialogOpen] = useState(false)
  const [dncDialogOpen, setDncDialogOpen] = useState(false)
  const [dncPending, setDncPending] = useState(false)
  const [dncError, setDncError] = useState<string | null>(null)

  const advanceInQueue = useCallback(
    (nextLeadId: number) => {
      if (!fromQueue) return
      navigate(buildLeadUrl(nextLeadId, fromQueue.key), { state: { fromQueue } })
    },
    [fromQueue, navigate],
  )

  const exitQueueCaughtUp = useCallback(() => {
    if (!fromQueue) return
    navigate(queuePath(fromQueue.key))
    setActivitySnackbar({
      open: true,
      message: 'Queue caught up.',
    })
  }, [fromQueue, navigate])

  const advanceAfterTaskComplete = useCallback(async () => {
    if (!fromQueue) return
    const nextId = queueNavigation?.next_id
    if (nextId) {
      advanceInQueue(nextId)
      return
    }
    try {
      const nav = await queueService.getNavigation(fromQueue.key, leadId)
      if (nav.next_id) {
        advanceInQueue(nav.next_id)
      } else {
        exitQueueCaughtUp()
      }
    } catch {
      exitQueueCaughtUp()
    }
  }, [fromQueue, leadId, queueNavigation?.next_id, advanceInQueue, exitQueueCaughtUp])

  const handleStatusChanged = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
  }, [queryClient, leadId])

  const handleActivitySaved = useCallback((
    entry: LeadTimelineEntry,
    type: ActivityLogType,
    meta?: { completedTaskId?: number; completedHubSpotTaskId?: number },
  ) => {
    activityRef.current?.prependEntry(entry)
    setHighlightEntryId(entry.id)
    setActivitySnackbar({ open: true, message: ACTIVITY_SUCCESS_MESSAGES[type] })
    setActivityModal(null)
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    window.setTimeout(() => setHighlightEntryId(null), 2000)
    if (
      fromQueue
      && (meta?.completedTaskId != null || meta?.completedHubSpotTaskId != null)
    ) {
      void advanceAfterTaskComplete()
    }
  }, [queryClient, leadId, fromQueue, advanceAfterTaskComplete])

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
        const result = await openLetterService.enqueue([leadId])
        setActivitySnackbar({
          open: true,
          message: `Added to mail queue (${result.queued_count}/${result.batch_minimum})`,
          linkTo: '/queues/ready-to-mail',
          linkLabel: 'View batch',
        })
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        await queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
        await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
        return
      }
      case 'research_property':
        setBuildingOwnershipOpen(true)
        return
      case 'run_analysis': {
        navigate(`${location.pathname}?tab=analysis`, { replace: true })
        if (leadLoading) {
          setActivitySnackbar({
            open: true,
            message: 'Loading lead details before starting analysis…',
          })
          return
        }
        const units = leadData?.units
        if (units != null && units >= 5) {
          const deal = await multifamilyService.createDeal({
            property_address: leadData?.property_street ?? '',
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
        await leadTaskService.createTask(leadId, {
          title: 'Run skip trace on owner',
          task_type: 'skip_trace_owner',
        })
        tasksPanelRef.current?.scrollIntoView()
        setActivitySnackbar({ open: true, message: 'Skip trace task created' })
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        return
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
  }, [queryClient, leadId, navigate, location.pathname, leadData, leadLoading])

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

  useEffect(() => {
    if (!showLead) return
    if (tabParam?.toLowerCase() !== 'timeline') return
    activityRef.current?.scrollIntoView()
  }, [showLead, tabParam])

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
  const openTasks = commandCenterData!.open_tasks ?? []
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
    <Box>
      {/* Queue work bar + sticky lead header */}
      <Box sx={{ position: 'sticky', top: 0, zIndex: 100, bgcolor: 'background.default' }}>
        {fromQueue && (
          <QueueWorkHeader
            fromQueue={fromQueue}
            navigation={queueNavigation}
            isLoading={queueNavLoading}
            onAdvance={advanceInQueue}
            onPrefetchLead={prefetchQueueLead}
          />
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

      {/* Queue context banners — one per queue membership (Req 5.2) */}
      <QueueContextBanners commandCenterData={commandCenterData!} />

      {/* Two-column flex layout: activity column (left) + property sidebar (right, hidden below lg) */}
      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', p: { xs: 1, sm: 2 } }}>
        {/* Activity column — order: RecommendedActionPanel → TasksPanel → ActivityPanel → TabPanel */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {/* RecommendedActionPanel — first in ActivityColumn (Req 5.3) */}
          <Box sx={{ mb: 2 }}>
            <RecommendedActionPanel
              recommendedAction={recommendedActionWithContact}
              leadStatus={commandCenterData!.lead_status}
              openTasks={openTasks}
              mailQueueStatus={commandCenterData!.mail_queue_status ?? null}
              showOutreachContact={placement === 'recommended_action'}
              condoRiskStatus={commandCenterData!.condo_risk_status ?? null}
              onAction={handleRaAction}
              onCreateTask={handleCreateTask}
            />
          </Box>

          {/* TasksPanel — second in ActivityColumn (Req 7.1–7.4) */}
          <TasksPanel
            ref={tasksPanelRef}
            leadId={leadId}
            initialTasks={openTasks}
            outreachContact={outreachContact}
            showOutreachContactOnPrimaryTask={placement === 'primary_task'}
            missingOutreachChannel={missingOutreachChannel}
            mailQueueStatus={commandCenterData!.mail_queue_status ?? null}
            upNextToMail={Boolean(commandCenterData!.up_next_to_mail)}
            onTasksChanged={() => queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })}
            onAfterTaskCompleted={fromQueue ? () => { void advanceAfterTaskComplete() } : undefined}
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
        <PropertySidebar commandCenterData={commandCenterData!} />
      </Box>

      <LogActivityModal
        open={activityModal != null}
        activityType={activityModal}
        leadId={leadId}
        openTasks={openTasks}
        onClose={() => setActivityModal(null)}
        onSaved={handleActivitySaved}
      />

      <BuildingOwnershipReviewDrawer
        leadId={leadId}
        commandCenterData={commandCenterData!}
        open={buildingOwnershipOpen}
        onClose={() => setBuildingOwnershipOpen(false)}
        onUpdated={() => queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })}
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
          severity="success"
          onClose={() => setActivitySnackbar((s) => ({ ...s, open: false }))}
          data-testid="activity-success-alert"
          action={
            activitySnackbar.linkTo ? (
              <Button
                color="inherit"
                size="small"
                component={RouterLink}
                to={activitySnackbar.linkTo}
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
