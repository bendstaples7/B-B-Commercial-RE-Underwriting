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
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Chip,
  Link as MuiLink,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import { Link as RouterLink, useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import CloseIcon from '@mui/icons-material/Close'
import FormatListBulletedIcon from '@mui/icons-material/FormatListBulleted'
import UndoIcon from '@mui/icons-material/Undo'
import OpenInFullIcon from '@mui/icons-material/OpenInFull'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import MergeTypeIcon from '@mui/icons-material/MergeType'
import { commandCenterService, leadTaskService, leadScoreService, queueService } from '@/services/api'
import { entityResolutionApi } from '@/services/entityResolutionApi'
import { leadService } from '@/services/leadApi'
import { multifamilyService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { primaryOwnerDisplayName } from '@/utils/propertyContacts'
import { parseLogActivityParam, buildLeadUrl } from '@/utils/queueLogNavigation'
import { isFromQueueState, fromQueueFromKey, queuePath, SKIP_TRACE_AUTO_ADVANCE_QUEUE_KEYS, mergeQueueSessionHistory, writeQueueSessionHistory, clearQueueSessionHistory, type FromQueueState } from '@/utils/fromQueue'
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
import { sortTimelineEntriesDesc } from '@/utils/timelineSort'
import { findActivityContextForTask } from '@/utils/timelineTaskContext'
import { LeadDetailTabPanel } from '@/components/lead-detail/LeadDetailTabPanel'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import { BuildingOwnershipSection } from '@/components/BuildingOwnershipSection'
import {
  ccCardSx,
  ccHeaderAddressColumnSx,
  ccHeaderPaperSx,
  ccHeaderPrimaryClusterSx,
  ccHeaderTrailingPanelsSx,
  ccHeroAddressSx,
  ccHeroSecondarySx,
  ccPageBgSx,
  ccSectionTitleSx,
  ccStackGap,
} from '@/components/lead-detail/commandCenterChrome'
import { KeyContactCard } from '@/components/lead-detail/KeyContactCard'
import { PropertyKpiCard } from '@/components/lead-detail/PropertyKpiCard'
import { PropertyOverviewQuickStats, shouldShowCondoCheckCell } from '@/components/lead-detail/PropertyOverviewQuickStats'
import { SameAddressMergeBanner } from '@/components/lead-detail/SameAddressMergeBanner'
import { DuplicateReviewCallout, NeedsReviewChipPopover } from '@/components/lead-detail/NeedsReviewClarityPanel'
import { afterCommandCenterMutation } from '@/utils/afterCommandCenterMutation'
import { isDuplicateClusterReason, mergeDuplicateTwins } from '@/utils/needsReviewReason'
import { HeaderCondoCheckPanel } from '@/components/lead-detail/HeaderCondoCheckPanel'
import { HeaderLeadScorePanel, resolveHeaderCurrentQueues, type ScoreFlash } from '@/components/lead-detail/HeaderLeadScorePanel'
import { DeepDiveDetailsCard } from '@/components/lead-detail/DeepDiveDetailsCard'
import { SuppressLeadDialog } from '@/components/SuppressLeadDialog'
import { AppSnackbar } from '@/components/AppSnackbar'
import {
  enqueueResultSeverity,
  formatEnqueueSummary,
} from '@/utils/formatEnqueueSummary'
import { formatDateOnly } from '@/utils/formatters'
import { formatCookCountyPin } from '@/utils/cookCountyPin'
import { MissingPinActions } from '@/components/lead-detail/PinLookupControl'
import {
  QueueAdvanceHoldBanner,
  QUEUE_ADVANCE_HOLD_MS,
  QUEUE_ADVANCE_NEXT_LABEL,
  QUEUE_ADVANCE_QUEUE_LABEL,
} from '@/components/lead-detail/QueueAdvanceHoldBanner'
import { scrollCommandCenterSectionIntoView } from '@/utils/scrollCommandCenterSection'
import { parseHubSpotTaskId } from '@/utils/callCompletableTask'

export { ALL_LEAD_STATUSES } from '@/constants/leadStatuses'
export { tabParamToIndex } from '@/components/lead-detail/LeadDetailTabPanel'

export interface UnifiedLeadCommandCenterProps {
  leadId: number
}

// ── Score tier derivation (fallback when no LeadScoreRecord exists yet) ────────

function scoreToTier(score: number | null | undefined): ScoreTier | null {
  if (score == null || !Number.isFinite(Number(score))) return null
  const n = Number(score)
  if (n >= 75) return 'A'
  if (n >= 60) return 'B'
  if (n >= 40) return 'C'
  return 'D'
}

function cleanAddressPart(value?: string | null): string {
  return (value || '').trim().replace(/^,+|,+$/g, '').trim()
}

// ── PropertyOverviewHeader ────────────────────────────────────────────────────
// Requirements: 5.1, 10.1, 10.2

interface PropertyOverviewHeaderProps {
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
  /** Snapshot queue neighbour before Pin Lookup deprioritize PATCH. */
  onBeforePinDeprioritize?: () => void
  /** After Pin Lookup multi-PIN deprioritize succeeds (queue hold / refresh). */
  onAfterPinDeprioritize?: () => void | Promise<void>
  /** Brief score delta pill shown after an activity save (call/note/email). */
  scoreFlash?: ScoreFlash | null
  onCategoryChanged?: (next: 'residential' | 'commercial') => void | Promise<void>
  onPropertyOverviewChanged?: () => void | Promise<void>
  /** Opens same-address merge dialog (header ⋯ → Merge duplicate…). */
  onMergeDuplicate?: () => void
  onNeedsReviewResolved?: (result: {
    kind: 'merged' | 'dismissed' | 'cleared'
    winnerId?: number
    loserId?: number
  }) => void | Promise<void>
}

function formatPropertyAddress(data: CommandCenterPayload): string {
  const street = cleanAddressPart(data.property_street)
  const city = cleanAddressPart(data.property_city)
  const state = cleanAddressPart(data.property_state)
  const zip = cleanAddressPart(data.property_zip)
  const stateZip = [state, zip].filter(Boolean).join(' ')
  const locality = [city, stateZip].filter(Boolean).join(', ')
  if (street && locality) return `${street}, ${locality}`
  return street || locality || `Lead #${data.id}`
}

function PropertyOverviewHeader({
  leadId,
  commandCenterData,
  scoreRecord,
  onStatusChanged,
  onViewFullBreakdown,
  fromQueue,
  onBeforePinDeprioritize,
  onAfterPinDeprioritize,
  statusSelectorRef,
  scoreFlash,
  onCategoryChanged,
  onPropertyOverviewChanged,
  onMergeDuplicate,
  onNeedsReviewResolved,
}: PropertyOverviewHeaderProps & { statusSelectorRef?: React.RefObject<HTMLDivElement | null> }) {
  const [scoreDialogOpen, setScoreDialogOpen] = useState(false)
  const [pinSnack, setPinSnack] = useState<string | null>(null)
  const [overflowAnchor, setOverflowAnchor] = useState<HTMLElement | null>(null)
  const navigate = useNavigate()
  const overflowOpen = Boolean(overflowAnchor)

  const fullAddress = formatPropertyAddress(commandCenterData)
  const primaryOwner = primaryOwnerDisplayName(
    commandCenterData.contacts,
    commandCenterData.owner_first_name,
    commandCenterData.owner_last_name,
    commandCenterData.organizations,
  )
  const pinFormatted = formatCookCountyPin(commandCenterData.county_assessor_pin || '') || null
  const pinMissing = !pinFormatted
  const akaStreet = cleanAddressPart(commandCenterData.assessor_aka_street || '')
  const akaLocality = [
    cleanAddressPart(commandCenterData.assessor_aka_city || ''),
    [
      cleanAddressPart(commandCenterData.assessor_aka_state || ''),
      cleanAddressPart(commandCenterData.assessor_aka_zip || ''),
    ].filter(Boolean).join(' '),
  ].filter(Boolean).join(', ')
  const akaDisplay = akaStreet
    ? (akaLocality ? `${akaStreet}, ${akaLocality}` : akaStreet)
    : ''
  const leadStreetNorm = cleanAddressPart(commandCenterData.property_street || '').toLowerCase()
  const showAka = Boolean(
    akaDisplay
    && akaStreet.toLowerCase() !== leadStreetNorm,
  )

  const displayScore = scoreRecord?.total_score ?? commandCenterData.lead_score
  const scoreTier = scoreRecord?.score_tier ?? scoreToTier(displayScore)
  const showCondoCheck = shouldShowCondoCheckCell(commandCenterData)
  const centerKpis = !showCondoCheck

  const handleBack = () => {
    if (fromQueue) {
      navigate(queuePath(fromQueue.key))
      return
    }
    navigate(-1)
  }

  const handleOwnerClick = () => {
    const el = document.querySelector('[data-testid="key-contact-card"]') as HTMLElement | null
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1')
    el.focus({ preventScroll: true })
    const highlightToken = `${Date.now()}-${Math.random()}`
    el.setAttribute('data-owner-link-highlight', 'true')
    el.setAttribute('data-owner-link-highlight-token', highlightToken)
    window.setTimeout(() => {
      if (el.getAttribute('data-owner-link-highlight-token') !== highlightToken) return
      el.removeAttribute('data-owner-link-highlight')
      el.removeAttribute('data-owner-link-highlight-token')
    }, 2000)
  }

  const metadataParts: React.ReactNode[] = []
  if (primaryOwner) {
    metadataParts.push(
      <Box key="owner" component="span" sx={{ display: 'inline' }}>
        Owner:{' '}
        <MuiLink
          component="button"
          type="button"
          variant="inherit"
          underline="hover"
          onClick={handleOwnerClick}
          data-testid="property-overview-owner-link"
          sx={{
            font: 'inherit',
            color: 'primary.main',
            cursor: 'pointer',
            verticalAlign: 'baseline',
          }}
        >
          {primaryOwner}
        </MuiLink>
      </Box>,
    )
  }
  // Always show PIN (same for commercial + residential) so a blank isn't invisible.
  metadataParts.push(
    <Box
      key="pin"
      component="span"
      data-testid="property-overview-pin"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 0.5,
      }}
    >
      Parcel ID / PIN: {pinMissing ? '—' : pinFormatted}
      {pinMissing ? (
        <MissingPinActions
          leadId={leadId}
          currentPin={commandCenterData.county_assessor_pin}
          onSnack={setPinSnack}
          testIdPrefix="property-overview"
          align="start"
          hideEmptyCaption
          layout="inline"
          autoPreview
          isCookCounty={Boolean(commandCenterData.is_cook_county_eligible)}
          onBeforeDeprioritize={onBeforePinDeprioritize}
          onAfterDeprioritize={onAfterPinDeprioritize}
        />
      ) : null}
    </Box>,
  )

  return (
    <>
      <Paper
        component="header"
        data-testid="property-overview-header"
        data-live-ui-surface="property-overview-header"
        elevation={0}
        sx={ccHeaderPaperSx}
      >
          <Box
            sx={{
              display: 'flex',
              // ONE horizontal bar on md+ — never wrap condo under Last sale.
              flexWrap: { xs: 'wrap', md: 'nowrap' },
              // xs: pin back to the top of the stacked address/KPI column.
              // md+: center KPIs / condo / score against the taller address column.
              alignItems: { xs: 'flex-start', md: 'center' },
              gap: { xs: 1.25, md: 1.25 },
              minWidth: 0,
              width: '100%',
            }}
          >
          <IconButton
            data-testid="back-button"
            onClick={handleBack}
            edge="start"
            aria-label={fromQueue ? `Back to ${fromQueue.label}` : 'Go back'}
            size="small"
            sx={{ mt: 0.25, flex: '0 0 auto' }}
          >
            <ArrowBackIcon />
          </IconButton>

          <Box sx={ccHeaderPrimaryClusterSx} data-testid="cc-header-primary-cluster">
          <Box sx={ccHeaderAddressColumnSx}>
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: 0.35,
                minWidth: 0,
                // Hug content on md so KPIs sit beside the street text (no mid-row canyon).
                width: { xs: '100%', md: 'auto' },
                maxWidth: '100%',
              }}
              data-testid="property-overview-address"
            >
              <Typography
                data-testid="property-overview-address-line"
                sx={{
                  ...ccHeroAddressSx,
                  fontSize: { xs: '1.15rem', sm: '1.35rem' },
                  minWidth: 0,
                  maxWidth: '100%',
                  // Mobile: wrap on word boundaries (never mid-token shatter).
                  // Desktop: one line; ellipsis only if the row truly overflows.
                  whiteSpace: { xs: 'normal', md: 'nowrap' },
                  overflow: { xs: 'visible', md: 'hidden' },
                  textOverflow: { xs: 'clip', md: 'ellipsis' },
                  overflowWrap: { xs: 'break-word', md: 'normal' },
                  wordBreak: { xs: 'normal', md: 'keep-all' },
                }}
                title={fullAddress}
              >
                {fullAddress}
              </Typography>
              {showAka ? (
                <Typography
                  component="div"
                  data-testid="property-overview-aka"
                  sx={{
                    ...ccHeroSecondarySx,
                    mt: 0.15,
                    fontSize: '0.8rem',
                    minWidth: 0,
                    maxWidth: '100%',
                    textAlign: 'left',
                    // AKA secondary — single line; ellipsis OK if longer than street.
                    whiteSpace: { xs: 'normal', md: 'nowrap' },
                    overflow: { xs: 'visible', md: 'hidden' },
                    textOverflow: { xs: 'clip', md: 'ellipsis' },
                  }}
                  title={akaDisplay}
                >
                  Also known as:{' '}
                  <Box component="span" sx={{ color: 'text.primary', fontWeight: 500 }}>
                    {akaDisplay}
                  </Box>
                </Typography>
              ) : null}
            </Box>

            {metadataParts.length > 0 ? (
              <Typography
                sx={{
                  ...ccHeroSecondarySx,
                  mt: 0.25,
                  display: 'flex',
                  flexWrap: 'wrap',
                  alignItems: 'baseline',
                  columnGap: 1,
                  rowGap: 0.25,
                }}
                component="div"
              >
                {metadataParts.map((part, idx) => (
                  <React.Fragment key={idx}>
                    {idx > 0 ? (
                      <Box component="span" aria-hidden sx={{ color: 'text.disabled' }}>
                        ·
                      </Box>
                    ) : null}
                    {part}
                  </React.Fragment>
                ))}
              </Typography>
            ) : null}

            <Box
              data-testid="property-overview-badges"
              sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                flexWrap: 'wrap',
                mt: 0.75,
              }}
            >
              <Box ref={statusSelectorRef} data-testid="property-overview-status">
                <LeadStatusSelector
                  leadId={leadId}
                  status={commandCenterData.lead_status}
                  allStatuses={ALL_LEAD_STATUSES}
                  onStatusChanged={onStatusChanged}
                />
              </Box>
              {onMergeDuplicate ? (
                <>
                  <IconButton
                    size="small"
                    aria-label="Lead options"
                    aria-haspopup="true"
                    aria-expanded={overflowOpen ? 'true' : undefined}
                    data-testid="lead-header-overflow-menu"
                    onClick={(event) => setOverflowAnchor(event.currentTarget)}
                    sx={{ cursor: 'pointer' }}
                  >
                    <MoreVertIcon fontSize="small" />
                  </IconButton>
                  <Menu
                    anchorEl={overflowAnchor}
                    open={overflowOpen}
                    onClose={() => setOverflowAnchor(null)}
                    data-testid="lead-header-overflow-menu-panel"
                    anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
                    transformOrigin={{ vertical: 'top', horizontal: 'left' }}
                  >
                    <MenuItem
                      data-testid="same-address-merge-menu-item"
                      onClick={() => {
                        setOverflowAnchor(null)
                        onMergeDuplicate()
                      }}
                      sx={{ cursor: 'pointer' }}
                    >
                      <ListItemIcon>
                        <MergeTypeIcon fontSize="small" />
                      </ListItemIcon>
                      <ListItemText>Merge duplicate…</ListItemText>
                    </MenuItem>
                  </Menu>
                </>
              ) : null}
            </Box>
          </Box>

          <PropertyOverviewQuickStats
            commandCenterData={commandCenterData}
            centerInGap={centerKpis}
            leadId={leadId}
            onCategoryChanged={onCategoryChanged}
            onPropertyOverviewChanged={onPropertyOverviewChanged}
          />
          </Box>

          <Box
            sx={ccHeaderTrailingPanelsSx}
            data-testid="cc-header-trailing-panels"
            data-cc-trail-mode={centerKpis ? 'grow-score' : 'grow-with-condo'}
          >
            <HeaderCondoCheckPanel
              commandCenterData={commandCenterData}
              onOpenBuildingOwnership={() => {
                scrollCommandCenterSectionIntoView('building-ownership-section')
              }}
            />

            <HeaderLeadScorePanel
              score={displayScore}
              tier={scoreTier}
              scoreRecord={scoreRecord}
              onOpenBreakdown={() => setScoreDialogOpen(true)}
              flash={scoreFlash}
              currentQueues={resolveHeaderCurrentQueues(
                commandCenterData.work_queues,
                fromQueue,
                {
                  reviewActive: Boolean(
                    commandCenterData.review_required || commandCenterData.review_reason,
                  ),
                },
              )}
              viewingFromQueueKey={fromQueue?.key ?? null}
              renderQueueItem={(queue, viewingFrom) => {
                if (queue.key !== 'needs-review' || !onNeedsReviewResolved) return undefined
                if (
                  !commandCenterData.review_required && !commandCenterData.review_reason
                ) {
                  return undefined
                }
                return (
                  <NeedsReviewChipPopover
                    leadId={leadId}
                    commandCenterData={commandCenterData}
                    label={queue.label}
                    variant="inline"
                    viewingFrom={viewingFrom}
                    onResolved={onNeedsReviewResolved}
                    onOpenMerge={onMergeDuplicate}
                  />
                )
              }}
            />
          </Box>
          </Box>
      </Paper>

      {scoreRecord && (
        <ScoreBreakdownDialog
          score={scoreRecord}
          open={scoreDialogOpen}
          onClose={() => setScoreDialogOpen(false)}
          onViewFullBreakdown={onViewFullBreakdown}
        />
      )}
      <AppSnackbar
        open={Boolean(pinSnack)}
        onClose={() => setPinSnack(null)}
        message={pinSnack ?? ''}
      />
    </>
  )
}

// ── QueueWorkHeader ───────────────────────────────────────────────────────────

interface QueueWorkHeaderProps {
  fromQueue: FromQueueState
  navigation: QueueNavigation | undefined
  isLoading: boolean
  /** Last lead viewed in this queue session (e.g. before auto-advance). */
  sessionBackLeadId?: number | null
  onAdvance: (leadId: number) => void
  onBackToQueue: () => void
  onPrefetchLead?: (leadId: number) => void
}

function QueueWorkHeader({
  fromQueue,
  navigation,
  isLoading,
  sessionBackLeadId,
  onAdvance,
  onBackToQueue,
  onPrefetchLead,
}: QueueWorkHeaderProps) {
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
        {sessionBackLeadId != null ? (
          isXs ? (
            <IconButton
              size="small"
              onClick={() => onAdvance(sessionBackLeadId)}
              onMouseEnter={() => onPrefetchLead?.(sessionBackLeadId)}
              onFocus={() => onPrefetchLead?.(sessionBackLeadId)}
              aria-label="Go back to previous lead"
              data-testid="queue-go-back-btn"
            >
              <UndoIcon fontSize="small" />
            </IconButton>
          ) : (
            <Button
              size="small"
              variant="outlined"
              startIcon={<UndoIcon fontSize="small" />}
              onClick={() => onAdvance(sessionBackLeadId)}
              onMouseEnter={() => onPrefetchLead?.(sessionBackLeadId)}
              onFocus={() => onPrefetchLead?.(sessionBackLeadId)}
              data-testid="queue-go-back-btn"
              sx={{ cursor: 'pointer' }}
            >
              Go back
            </Button>
          )
        ) : null}
        {isXs ? (
          <IconButton
            size="small"
            onClick={onBackToQueue}
            aria-label="Back to queue"
            data-testid="queue-back-to-list"
          >
            <FormatListBulletedIcon fontSize="small" />
          </IconButton>
        ) : (
          <Button
            size="small"
            onClick={onBackToQueue}
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

// ── TasksPanel ────────────────────────────────────────────────────────────────
// Requirements: 7.1, 7.2, 7.3, 7.4, 12.4

interface TasksPanelProps {
  leadId: number
  initialTasks: LeadTask[]
  activityEntries?: LeadTimelineEntry[]
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
  /** Open the activity overlay to edit an existing task. */
  onEditTask?: (task: LeadTask) => void
}

export interface TasksPanelHandle {
  scrollIntoView: () => void
  openCreateForm: () => void
}

const TasksPanel = React.forwardRef<TasksPanelHandle, TasksPanelProps>(function TasksPanel(
  {
    leadId,
    initialTasks,
    activityEntries = [],
    outreachContact,
    showOutreachContactOnPrimaryTask = false,
    missingOutreachChannel = null,
    mailQueueStatus = null,
    upNextToMail = false,
    embedded = false,
    onTasksChanged,
    onAfterTaskCompleted,
    onEditTask,
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
          activityEntries={activityEntries}
          outreachContact={outreachContact}
          showOutreachContactOnPrimaryTask={showOutreachContactOnPrimaryTask}
          missingOutreachChannel={missingOutreachChannel}
          mailQueueStatus={mailQueueStatus}
          upNextToMail={upNextToMail}
          onTaskCreated={handleTaskCreated}
          onTaskUpdated={handleTaskUpdated}
          onEditTask={onEditTask}
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
            activityEntries={activityEntries}
            outreachContact={outreachContact}
            showOutreachContactOnPrimaryTask={showOutreachContactOnPrimaryTask}
            missingOutreachChannel={missingOutreachChannel}
            mailQueueStatus={mailQueueStatus}
            upNextToMail={upNextToMail}
            onTaskCreated={handleTaskCreated}
            onTaskUpdated={handleTaskUpdated}
            onEditTask={onEditTask}
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
  variant?: 'accordion' | 'feed'
  embedded?: boolean
  onEntriesChanged?: (entries: LeadTimelineEntry[]) => void
}

export interface ActivityPanelHandle {
  scrollIntoView: () => void
  prependEntry: (entry: LeadTimelineEntry) => void
}

const ACTIVITY_SUCCESS_MESSAGES: Record<ActivityLogType, string> = {
  note: 'Note saved.',
  call: 'Call logged.',
  email: 'Email logged.',
  meeting: 'Meeting logged.',
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

type ActivityFeedFilter = 'all' | 'mail'

function isMailTimelineEntry(entry: LeadTimelineEntry): boolean {
  return (
    entry.event_type === 'mail_sent'
    || entry.event_type === 'mailer_history'
    || entry.event_type === 'mail_queued'
    || entry.event_type === 'mail_delivered'
  )
}

function isDefaultFeedEntry(entry: LeadTimelineEntry): boolean {
  return entry.event_type !== 'recommended_action_changed'
}

function filterEntriesForFeed(
  entries: readonly LeadTimelineEntry[],
  feedFilter: ActivityFeedFilter,
): LeadTimelineEntry[] {
  return feedFilter === 'mail'
    ? entries.filter(isMailTimelineEntry)
    : entries.filter(isDefaultFeedEntry)
}

function mergeTimelineEntrySets(
  current: readonly LeadTimelineEntry[],
  incoming: readonly LeadTimelineEntry[],
): LeadTimelineEntry[] {
  const byId = new Map<number, LeadTimelineEntry>()
  for (const entry of current) byId.set(entry.id, entry)
  for (const entry of incoming) byId.set(entry.id, entry)
  return sortTimelineEntriesDesc(Array.from(byId.values()))
}

const ActivityPanel = React.forwardRef<ActivityPanelHandle, ActivityPanelProps>(
  function ActivityPanel(
    {
      leadId,
      initialEntries,
      initialTotal,
      highlightEntryId,
      variant = 'accordion',
      embedded = false,
      onEntriesChanged,
    },
    ref,
  ) {
    const panelRef = useRef<HTMLDivElement>(null)
    const [fullscreenOpen, setFullscreenOpen] = useState(false)
    const [feedFilter, setFeedFilter] = useState<ActivityFeedFilter>('all')
    const initialScopedEntries = normalizeTimelineEntriesForLead(initialEntries, leadId)
    const [timelineEntries, setTimelineEntries] = useState<LeadTimelineEntry[]>(() =>
      scopeRowsToLead(initialScopedEntries, leadId, 'timeline'),
    )
    const [timelineTotal, setTimelineTotal] = useState(initialTotal)
    const leadIdRef = useRef(leadId)
    leadIdRef.current = leadId
    const timelineEntriesRef = useRef(timelineEntries)
    timelineEntriesRef.current = timelineEntries
    // Durable backstop for rows added via `prependEntry` (call/note/status
    // saves). `timelineEntries` local state can, in principle, be replaced by
    // the sync effect below before a slow/racy commandCenter refetch has
    // caught up with the write — this map survives that and gets re-merged
    // in on every sync pass until the server confirms the same id, so a
    // refetch that *briefly* omits the new row can never make it vanish from
    // the feed (see lead 10737).
    const pendingPrependsRef = useRef<Map<number, LeadTimelineEntry>>(new Map())

    React.useEffect(() => {
      setFullscreenOpen(false)
      setFeedFilter('all')
    }, [leadId])

    React.useEffect(() => {
      onEntriesChanged?.(timelineEntries)
    }, [onEntriesChanged, timelineEntries])

    // Drop prior-lead rows entirely when navigating. Only keep optimistic
    // prepends that belong to the *current* lead (same lead_id), then
    // fail-closed filter anything foreign before paint. LeadTimeline is a
    // presenter — scoping ownership stays here.
    React.useEffect(() => {
      const serverEntries = normalizeTimelineEntriesForLead(initialEntries, leadId)
      const serverIds = new Set(serverEntries.map((e) => e.id))

      // Server has caught up with these — stop tracking them as pending.
      for (const id of Array.from(pendingPrependsRef.current.keys())) {
        if (serverIds.has(id)) pendingPrependsRef.current.delete(id)
      }

      const localOptimistic = timelineEntriesRef.current.filter(
        (e) => e.lead_id === leadId && !serverIds.has(e.id),
      )
      const stillPending = Array.from(pendingPrependsRef.current.values()).filter(
        (e) => (
          e.lead_id === leadId
          && !serverIds.has(e.id)
          && !localOptimistic.some((o) => o.id === e.id)
        ),
      )
      const optimisticOnly = [...stillPending, ...localOptimistic]
      const scoped = scopeRowsToLeadWithTotal(
        sortTimelineEntriesDesc([...optimisticOnly, ...serverEntries]),
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
        pendingPrependsRef.current.set(normalized.id, normalized)
        // Safety net: never track a pending row forever if the server
        // genuinely never reflects it (e.g. scoping rejects it upstream).
        window.setTimeout(() => {
          pendingPrependsRef.current.delete(normalized.id)
        }, 60000)
        setTimelineEntries((prev) =>
          sortTimelineEntriesDesc(
            scopeRowsToLead([normalized, ...prev], activeLeadId, 'timeline'),
          ),
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
      const previousRaw = scopeRowsToLead(
        timelineEntriesRef.current,
        requestedLeadId,
        'timeline',
      )
      const mergedRaw = mergeTimelineEntrySets(previousRaw, scoped.rows)
      const rows = filterEntriesForFeed(scoped.rows, feedFilter)
      const visibleLoaded = filterEntriesForFeed(mergedRaw, feedFilter).length
      const rawExhausted = mergedRaw.length >= scoped.total || scoped.rows.length === 0
      setTimelineEntries(mergedRaw)
      return {
        entries: rows,
        total: rawExhausted
          ? visibleLoaded
          : Math.max(visibleLoaded + 1, scoped.total),
      }
    }

    const visibleEntries = useMemo(
      () => sortTimelineEntriesDesc(
        filterEntriesForFeed(timelineEntries, feedFilter),
      ),
      [feedFilter, timelineEntries],
    )
    // Feed filters are client-side over loaded pages — keep load-more until
    // raw server pages are exhausted, then collapse to the visible count.
    const rawTimelineExhausted = timelineEntries.length >= timelineTotal
    const visibleTotal =
      rawTimelineExhausted
        ? visibleEntries.length
        : Math.max(visibleEntries.length + 1, timelineTotal)

    const timeline = (
      <LeadTimeline
        leadId={leadId}
        initialEntries={visibleEntries}
        initialTotal={visibleTotal}
        onLoadMore={handleLoadMore}
        highlightEntryId={highlightEntryId}
        variant={fullscreenOpen ? 'feed' : variant}
        previewMode={false}
      />
    )

    const filterChips = (
      <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap data-testid="activity-feed-filters">
        <Chip
          size="small"
          label="All"
          clickable
          color={feedFilter === 'all' ? 'primary' : 'default'}
          variant={feedFilter === 'all' ? 'filled' : 'outlined'}
          onClick={() => setFeedFilter('all')}
          data-testid="activity-filter-all"
        />
        <Chip
          size="small"
          label="Mail"
          clickable
          color={feedFilter === 'mail' ? 'primary' : 'default'}
          variant={feedFilter === 'mail' ? 'filled' : 'outlined'}
          onClick={() => setFeedFilter('mail')}
          data-testid="activity-filter-mail"
        />
      </Stack>
    )

    return (
      <Box
        ref={panelRef}
        component={embedded ? Paper : 'div'}
        {...(embedded ? { elevation: 0 } : {})}
        sx={embedded ? { ...ccCardSx, mb: 0 } : { mb: 2 }}
        data-testid="activity-panel"
      >
        {!fullscreenOpen && (
          <>
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 1,
                mb: 1.5,
                flexWrap: 'wrap',
              }}
            >
              <Typography sx={{ ...ccSectionTitleSx, mb: 0 }} component="h2">
                Activity
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                {filterChips}
                <Button
                size="small"
                startIcon={<OpenInFullIcon fontSize="small" />}
                onClick={() => setFullscreenOpen(true)}
                data-testid="activity-fullscreen-btn"
                aria-label="View activity full screen"
              >
                Full screen
              </Button>
              </Box>
            </Box>
            {timeline}
          </>
        )}
        <Dialog
          open={fullscreenOpen}
          onClose={() => setFullscreenOpen(false)}
          fullScreen
          aria-labelledby="activity-fullscreen-title"
          data-testid="activity-fullscreen-dialog"
        >
          <DialogTitle
            id="activity-fullscreen-title"
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 1,
              py: 1.5,
            }}
          >
            <Typography component="span" variant="h6" fontWeight={700}>
              Activity
            </Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {filterChips}
              <IconButton
              aria-label="Close full screen activity"
              onClick={() => setFullscreenOpen(false)}
              data-testid="activity-fullscreen-close"
              edge="end"
            >
              <CloseIcon />
            </IconButton>
            </Box>
          </DialogTitle>
          <DialogContent
            dividers
            sx={{
              display: 'flex',
              flexDirection: 'column',
              p: { xs: 2, sm: 3 },
              maxWidth: 960,
              width: '100%',
              mx: 'auto',
            }}
          >
            {timeline}
          </DialogContent>
        </Dialog>
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
    if (isFromQueueState(state?.fromQueue)) return mergeQueueSessionHistory(state.fromQueue, leadId)
    const fromKey = fromQueueFromKey(searchParams.get('queue'), searchParams.get('outreach'))
    return fromKey ? mergeQueueSessionHistory(fromKey, leadId) : null
  }, [leadId, location.state, searchParams])
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
    // Poll while condo analysis was auto-scheduled on open until it settles.
    refetchInterval: (query) =>
      query.state.data?.building_ownership_pending ? 2500 : false,
  })
  const openTasks = useMemo(
    () => commandCenterData?.open_tasks ?? [],
    [commandCenterData?.open_tasks],
  )
  const [taskActivityEntries, setTaskActivityEntries] = useState<LeadTimelineEntry[]>([])

  useEffect(() => {
    const entries = commandCenterData?.timeline.entries ?? []
    setTaskActivityEntries(
      scopeRowsToLead(
        normalizeTimelineEntriesForLead(entries, leadId),
        leadId,
        'timeline',
      ),
    )
  }, [commandCenterData?.timeline.entries, leadId])

  const handleActivityEntriesChanged = useCallback((entries: LeadTimelineEntry[]) => {
    setTaskActivityEntries((prev) =>
      mergeTimelineEntrySets(
        prev,
        scopeRowsToLead(entries, leadId, 'timeline'),
      ),
    )
  }, [leadId])

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

  // Mirrors of the latest fetched data for callbacks (e.g. score-flash delta)
  // that must read current values without forcing a new function identity
  // on every refetch.
  const scoreDataRef = useRef(scoreData)
  scoreDataRef.current = scoreData
  const commandCenterDataRef = useRef(commandCenterData)
  commandCenterDataRef.current = commandCenterData

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
  // visible center ActivityPanel (below Open Tasks) — so the Needs Review
  // queue's "View Activity" deep-link (?tab=timeline) instead scrolls the
  // ActivityPanel into view once the data has loaded and the panel has rendered.
  const tabParam = searchParams.get('tab')
  const activityRef = useRef<ActivityPanelHandle>(null)
  const tasksPanelRef = useRef<TasksPanelHandle>(null)
  const statusSelectorRef = useRef<HTMLDivElement | null>(null)
  const theme = useTheme()
  const isLgUp = useMediaQuery(theme.breakpoints.up('lg'), { noSsr: true })
  const showLead = !!commandCenterData && !commandCenterError
  const [activityModal, setActivityModal] = useState<ActivityLogType | null>(null)
  const [editingTask, setEditingTask] = useState<LeadTask | null>(null)
  const [highlightEntryId, setHighlightEntryId] = useState<number | null>(null)
  const [scoreFlash, setScoreFlash] = useState<ScoreFlash | null>(null)
  const scoreFlashTimeoutRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (scoreFlashTimeoutRef.current != null) {
        window.clearTimeout(scoreFlashTimeoutRef.current)
      }
    }
  }, [])
  const [sameAddressMergeOpen, setSameAddressMergeOpen] = useState(false)
  const duplicateReviewActive = isDuplicateClusterReason(commandCenterData?.review_reason)
  const mergeTwins = useMemo(
    () => mergeDuplicateTwins(
      leadId,
      commandCenterData?.same_address_leads,
      commandCenterData?.duplicate_cluster,
    ),
    [commandCenterData?.duplicate_cluster, commandCenterData?.same_address_leads, leadId],
  )
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
  const handleNeedsReviewResolved = useCallback(async (result: {
    kind: 'merged' | 'dismissed' | 'cleared'
    winnerId?: number
    loserId?: number
  }) => {
    if (result.kind === 'merged' && result.winnerId != null && result.loserId != null) {
      const mergeFlash = { message: 'Records combined.' }
      setActivitySnackbar({ open: true, ...mergeFlash })
      await afterCommandCenterMutation(queryClient, {
        winnerId: result.winnerId,
        loserId: result.loserId,
        navigate,
        fromQueue,
        flashSnackbar: result.winnerId === leadId ? undefined : mergeFlash,
      })
      return
    }
    setActivitySnackbar({
      open: true,
      message: result.kind === 'dismissed' ? 'Marked not a duplicate.' : 'Marked reviewed.',
    })
    await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    void queryClient.invalidateQueries({ queryKey: ['queue-needs-review'] })
    void queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
  }, [fromQueue, leadId, navigate, queryClient])
  const [suppressDialogOpen, setSuppressDialogOpen] = useState(false)
  const [dncDialogOpen, setDncDialogOpen] = useState(false)
  const [dncPending, setDncPending] = useState(false)
  const [dncError, setDncError] = useState<string | null>(null)
  const [mailNudgeOpen, setMailNudgeOpen] = useState(false)
  const [mailNudgePending, setMailNudgePending] = useState(false)
  const [mailNudgeError, setMailNudgeError] = useState<string | null>(null)
  const mailNudgeSessionDismissRef = useRef(false)
  const mailNudgeDismissedAtCountRef = useRef<number | null>(null)

  useEffect(() => {
    mailNudgeSessionDismissRef.current = false
    mailNudgeDismissedAtCountRef.current = null
    setMailNudgeOpen(false)
    setMailNudgeError(null)
  }, [leadId])

  useEffect(() => {
    const unanswered = commandCenterData?.unanswered_call_count
    if (
      typeof unanswered === 'number'
      && mailNudgeDismissedAtCountRef.current != null
      && unanswered > mailNudgeDismissedAtCountRef.current
    ) {
      mailNudgeSessionDismissRef.current = false
    }
  }, [commandCenterData?.unanswered_call_count])

  useEffect(() => {
    if (!commandCenterData?.unanswered_mail_nudge_owed) return
    if (activityModal != null || dncDialogOpen || suppressDialogOpen) return
    if (mailNudgeSessionDismissRef.current) return
    setMailNudgeOpen(true)
  }, [
    commandCenterData?.unanswered_mail_nudge_owed,
    commandCenterData?.unanswered_call_count,
    activityModal,
    dncDialogOpen,
    suppressDialogOpen,
  ])

  const dismissMailNudgeLocal = useCallback((opts?: { persistCount?: boolean }) => {
    mailNudgeSessionDismissRef.current = true
    if (opts?.persistCount) {
      const unanswered = commandCenterData?.unanswered_call_count
      mailNudgeDismissedAtCountRef.current =
        typeof unanswered === 'number' ? unanswered : mailNudgeDismissedAtCountRef.current
    }
    setMailNudgeOpen(false)
    setMailNudgeError(null)
  }, [commandCenterData?.unanswered_call_count])

  const handleMailNudgeKeepCalling = useCallback(async () => {
    setMailNudgePending(true)
    setMailNudgeError(null)
    try {
      await commandCenterService.unansweredMailNudgeKeepCalling(leadId)
      dismissMailNudgeLocal({ persistCount: true })
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    } catch (err) {
      setMailNudgeError(err instanceof Error ? err.message : 'Could not save. Try again.')
    } finally {
      setMailNudgePending(false)
    }
  }, [dismissMailNudgeLocal, leadId, queryClient])

  const handleMailNudgeSwitchToMail = useCallback(async () => {
    setMailNudgePending(true)
    setMailNudgeError(null)
    try {
      await commandCenterService.unansweredMailNudgeSwitchToMail(leadId)
      dismissMailNudgeLocal()
      setActivitySnackbar({ open: true, message: 'Switched to Direct Mail' })
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    } catch (err) {
      setMailNudgeError(err instanceof Error ? err.message : 'Could not switch. Try again.')
    } finally {
      setMailNudgePending(false)
    }
  }, [dismissMailNudgeLocal, leadId, queryClient])

  type QueueFlashSnackbar = {
    message: string
    severity?: 'success' | 'warning' | 'error'
    linkTo?: string
    linkLabel?: string
  }

  const advanceInQueue = useCallback(
    (nextLeadId: number, flash?: QueueFlashSnackbar) => {
      if (!fromQueue) return
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
      writeQueueSessionHistory(fromQueue.key, {
        visitedHistory: nextQueueState.visitedHistory,
        forwardStack: nextQueueState.forwardStack,
      }, fromQueue.outreach)
      navigate(buildLeadUrl(nextLeadId, fromQueue.key, fromQueue.outreach), {
        state: {
          fromQueue: nextQueueState,
          ...(flash ? { flashSnackbar: flash } : {}),
        },
      })
    },
    [fromQueue, forwardStack, leadId, navigate, visitedHistory],
  )

  const exitQueueCaughtUp = useCallback((flash?: QueueFlashSnackbar) => {
    if (!fromQueue) return
    clearQueueSessionHistory(fromQueue.key, fromQueue.outreach)
    navigate(queuePath(fromQueue.key), {
      state: flash ? { flashSnackbar: flash } : undefined,
    })
    if (flash) {
      setActivitySnackbar({ open: true, ...flash })
    } else {
      setActivitySnackbar({
        open: true,
        message: 'Queue caught up.',
      })
    }
  }, [fromQueue, navigate])

  const returnToQueue = useCallback(() => {
    if (!fromQueue) return
    clearQueueSessionHistory(fromQueue.key, fromQueue.outreach)
    navigate(queuePath(fromQueue.key))
  }, [fromQueue, navigate])

  const refreshQueueCachesForAdvance = useCallback(() => {
    if (!fromQueue) return
    const queueListKey = `queue-${fromQueue.key}`
    // Fire-and-forget: navigation must not wait on list refetch. Kick this off
    // when the hold starts so Back still lands on fresh data after the drain.
    void queryClient.invalidateQueries({
      queryKey: [queueListKey],
      refetchType: 'all',
    })
    void queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    if (fromQueue.key === 'todays-action') {
      void queryClient.invalidateQueries({
        queryKey: ['queue-todays-action-outreach-counts'],
        refetchType: 'all',
      })
    }
    queryClient.removeQueries({ queryKey: [queueListKey] })
  }, [fromQueue, queryClient])

  const advanceAfterTaskComplete = useCallback((
    snapshottedNextId?: number | null,
    flash?: QueueFlashSnackbar,
  ) => {
    if (!fromQueue) return
    refreshQueueCachesForAdvance()

    // undefined = nav not ready — stay put (never re-fetch neighbour after removal).
    if (snapshottedNextId === undefined) {
      if (flash) {
        setActivitySnackbar({ open: true, ...flash })
      }
      return
    }

    try {
      if (snapshottedNextId != null) {
        advanceInQueue(snapshottedNextId, flash)
      } else {
        exitQueueCaughtUp(flash)
      }
    } catch {
      exitQueueCaughtUp(flash)
    }
  }, [fromQueue, advanceInQueue, exitQueueCaughtUp, refreshQueueCachesForAdvance])

  type QueueAdvanceHoldState = {
    startedAt: number
    durationMs: number
    nextId: number | null
    flash?: QueueFlashSnackbar
    message: string
  }

  const [queueAdvanceHold, setQueueAdvanceHold] = useState<QueueAdvanceHoldState | null>(null)
  const holdTimeoutRef = useRef<number | null>(null)
  const holdGenerationRef = useRef(0)

  const clearQueueAdvanceHoldTimers = useCallback(() => {
    if (holdTimeoutRef.current != null) {
      window.clearTimeout(holdTimeoutRef.current)
      holdTimeoutRef.current = null
    }
  }, [])

  const cancelQueueAdvanceHold = useCallback((opts?: { snackStay?: boolean }) => {
    holdGenerationRef.current += 1
    clearQueueAdvanceHoldTimers()
    setQueueAdvanceHold(null)
    if (opts?.snackStay) {
      setActivitySnackbar({ open: true, message: 'Staying on this lead.' })
    }
  }, [clearQueueAdvanceHoldTimers])

  const snapshotNextQueueLeadId = useCallback((): number | null | undefined => {
    if (!fromQueue || queueNavLoading || !queueNavigation) return undefined
    return forwardStack.at(-1) ?? queueNavigation.next_id ?? null
  }, [fromQueue, forwardStack, queueNavLoading, queueNavigation])

  const scheduleQueueAdvanceHold = useCallback((opts: {
    nextId: number | null | undefined
    flash?: QueueFlashSnackbar
    message: string
  }) => {
    if (!fromQueue) return
    // Nav still loading — refresh queues / snack, never arm a hold.
    if (opts.nextId === undefined) {
      void advanceAfterTaskComplete(undefined, opts.flash ?? { message: opts.message })
      return
    }

    clearQueueAdvanceHoldTimers()
    const generation = ++holdGenerationRef.current
    const startedAt = Date.now()
    const durationMs = QUEUE_ADVANCE_HOLD_MS
    const nextId = opts.nextId
    const flash = opts.flash
    setQueueAdvanceHold({
      startedAt,
      durationMs,
      nextId,
      flash,
      message: opts.message,
    })

    // Warm the next workspace + queue lists during the drain so navigation
    // isn't blocked after the bar empties.
    refreshQueueCachesForAdvance()
    if (nextId != null) prefetchQueueLead(nextId)

    holdTimeoutRef.current = window.setTimeout(() => {
      if (holdGenerationRef.current !== generation) return
      clearQueueAdvanceHoldTimers()
      // Leave the banner mounted until the next lead remounts so the drain
      // and the route change happen in the same beat — no empty-bar linger.
      advanceAfterTaskComplete(nextId, flash)
    }, durationMs)
  }, [fromQueue, advanceAfterTaskComplete, clearQueueAdvanceHoldTimers, refreshQueueCachesForAdvance, prefetchQueueLead])

  // Drop a pending hold when the lead identity changes; always clear timers on unmount.
  useEffect(() => {
    holdGenerationRef.current += 1
    clearQueueAdvanceHoldTimers()
    setQueueAdvanceHold(null)
    return () => {
      holdGenerationRef.current += 1
      clearQueueAdvanceHoldTimers()
    }
  }, [leadId, clearQueueAdvanceHoldTimers])

  const handleManualQueueAdvance = useCallback((nextLeadId: number) => {
    cancelQueueAdvanceHold()
    advanceInQueue(nextLeadId)
  }, [advanceInQueue, cancelQueueAdvanceHold])

  /** Captured before Pin Lookup deprioritize PATCH removes this lead from the queue. */
  const pinDeprioritizeNextIdRef = useRef<number | null | undefined>(undefined)

  /**
   * Shared by status-change and activity-save paths: optimistically patches
   * the new row into the `commandCenter` cache's `timeline.entries` (so any
   * consumer reading that cache sees it immediately, independent of the
   * ActivityPanel ref) and prepends it into the live ActivityPanel, with the
   * usual highlight flash.
   */
  const prependTimelineEntry = useCallback((entry: LeadTimelineEntry) => {
    queryClient.setQueryData<CommandCenterPayload>(
      ['commandCenter', leadId],
      (current) => {
        if (!current) return current
        const normalized: LeadTimelineEntry = { ...entry, lead_id: entry.lead_id ?? leadId }
        if (current.timeline.entries.some((e) => e.id === normalized.id)) return current
        return {
          ...current,
          timeline: {
            ...current.timeline,
            entries: sortTimelineEntriesDesc([normalized, ...current.timeline.entries]),
            total: current.timeline.total + 1,
          },
        }
      },
    )
    activityRef.current?.prependEntry(entry)
    setHighlightEntryId(entry.id)
    window.setTimeout(() => setHighlightEntryId(null), 2000)
  }, [queryClient, leadId])

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
      prependTimelineEntry(result.timeline_entry)
    }
    // Header prefers leadScore history over CC lead_score — must refresh or score looks stuck.
    // Fire-and-forget: awaiting RQ refetch under Vitest fake timers can deadlock.
    void queryClient.invalidateQueries({ queryKey: ['leadScore', leadId] })
    void queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    if (!fromQueue) return
    void queryClient.invalidateQueries({ queryKey: ['queue-navigation', fromQueue.key] })
    void queryClient.invalidateQueries({ queryKey: [`queue-${fromQueue.key}`] })
    // Stay on this lead after status change — only task/activity completion advances the queue.
  }, [queryClient, leadId, fromQueue, prependTimelineEntry])

  const handleActivitySaved = useCallback((
    entry: LeadTimelineEntry,
    type: ActivityLogType,
    meta?: {
      completedTaskId?: number
      completedHubSpotTaskId?: number
      warning?: string
    },
  ) => {
    prependTimelineEntry(entry)
    setActivitySnackbar({
      open: true,
      message: meta?.warning ?? ACTIVITY_SUCCESS_MESSAGES[type],
      severity: meta?.warning ? 'warning' : 'success',
    })
    setActivityModal(null)
    setEditingTask(null)

    // Optimistically drop the task the response says was completed — do not
    // wait for the full refetch below (visible immediately even during a
    // queue-advance hold).
    if (meta?.completedTaskId != null || meta?.completedHubSpotTaskId != null) {
      queryClient.setQueryData<CommandCenterPayload>(
        ['commandCenter', leadId],
        (current) => {
          if (!current) return current
          const nextTasks = current.open_tasks.filter((task) => {
            if (meta.completedTaskId != null && task.id === meta.completedTaskId) return false
            if (
              meta.completedHubSpotTaskId != null
              && parseHubSpotTaskId(task.id) === meta.completedHubSpotTaskId
            ) return false
            return true
          })
          if (nextTasks.length === current.open_tasks.length) return current
          return { ...current, open_tasks: nextTasks }
        },
      )
    }

    void queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })

    // Score gauge must move (or explicitly say it didn't) even while a queue
    // advance hold is showing — never wait for the hold to pass. Fire-and-
    // forget: awaiting RQ refetch under Vitest fake timers can deadlock.
    const previousScore = scoreDataRef.current?.latest?.total_score
      ?? commandCenterDataRef.current?.lead_score
      ?? null
    void queryClient.invalidateQueries({ queryKey: ['leadScore', leadId] }).then(() => {
      const refreshed = queryClient.getQueryData<PropertyScoreResponse>(['leadScore', leadId])
      const nextScore = refreshed?.latest?.total_score ?? null
      if (previousScore == null || nextScore == null) return
      const delta = Math.round(nextScore) - Math.round(previousScore)
      if (scoreFlashTimeoutRef.current != null) window.clearTimeout(scoreFlashTimeoutRef.current)
      setScoreFlash(
        delta === 0
          ? { label: 'Score unchanged', tone: 'neutral' }
          : { label: `${delta > 0 ? '+' : ''}${delta}`, tone: delta > 0 ? 'up' : 'down' },
      )
      scoreFlashTimeoutRef.current = window.setTimeout(() => setScoreFlash(null), 4000)
    })

    if (
      fromQueue
      && (meta?.completedTaskId != null || meta?.completedHubSpotTaskId != null)
    ) {
      scheduleQueueAdvanceHold({
        nextId: snapshotNextQueueLeadId(),
        message: meta?.warning ?? ACTIVITY_SUCCESS_MESSAGES[type] ?? 'Activity saved',
      })
    }
  }, [
    queryClient,
    leadId,
    fromQueue,
    scheduleQueueAdvanceHold,
    snapshotNextQueueLeadId,
    prependTimelineEntry,
  ])

  const editingTaskDraft = useMemo(() => {
    if (!editingTask || typeof editingTask.id !== 'number' || editingTask.id <= 0) return null
    const ctx = findActivityContextForTask(editingTask.id, taskActivityEntries)
    return {
      task: editingTask,
      note: ctx?.body ?? '',
      phoneDigits: ctx?.phoneNumber ?? null,
    }
  }, [editingTask, taskActivityEntries])

  const handleEditOpenTask = useCallback((task: LeadTask) => {
    setEditingTask(task)
    setActivityModal('note')
  }, [])

  const handleTaskUpdatedFromOverlay = useCallback((task: LeadTask) => {
    setEditingTask(null)
    setActivityModal(null)
    setActivitySnackbar({ open: true, message: 'Task updated' })
    queryClient.setQueryData<CommandCenterPayload>(
      ['commandCenter', leadId],
      (current) => {
        if (!current) return current
        return {
          ...current,
          open_tasks: current.open_tasks.map((row) => (
            row.id === task.id ? { ...row, ...task } : row
          )),
        }
      },
    )
    void queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    void queryClient.invalidateQueries({ queryKey: ['leadScore', leadId] })
  }, [leadId, queryClient])

  const handleRaAction = useCallback(async (action: string) => {
    switch (action) {
      case 'log_call':
        setEditingTask(null)
        setActivityModal('call')
        return
      case 'log_note':
        setEditingTask(null)
        setActivityModal('note')
        return
      case 'log_email':
        setEditingTask(null)
        setActivityModal('email')
        return
      case 'log_meeting':
        setActivityModal('meeting')
        return
      case 'create_task':
        tasksPanelRef.current?.scrollIntoView()
        window.setTimeout(() => tasksPanelRef.current?.openCreateForm(), 300)
        return
      case 'add_to_mail_batch': {
        // Snapshot neighbour before enqueue removes this lead from Today's Action.
        const nextLeadId = snapshotNextQueueLeadId()
        const result = await openLetterService.enqueue([leadId], fromQueue?.key ?? 'command-center')
        const flash = {
          message: formatEnqueueSummary(result),
          severity: enqueueResultSeverity(result),
          ...(result.added > 0
            ? { linkTo: '/queues/ready-to-mail', linkLabel: 'View staged batch' }
            : {}),
        } as const
        setActivitySnackbar({
          open: true,
          ...flash,
        })
        // Arm hold before query invalidation — awaiting RQ under fake timers
        // can starve the advance chrome and hang tests.
        if (result.added > 0 && fromQueue) {
          scheduleQueueAdvanceHold({
            nextId: nextLeadId,
            flash,
            message: flash.message,
          })
        }
        void queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        void queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
        void queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
        return
      }
      case 'research_property': {
        scrollCommandCenterSectionIntoView('building-ownership-section')
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
            ? 'Already in Skip Trace pipeline'
            : result.completed_task_id
              ? 'Current task completed and lead moved to Skip Trace'
              : 'Lead moved to Skip Trace',
        })
        if (!result.already_done) {
          const advanceNextId = (
            fromQueue && SKIP_TRACE_AUTO_ADVANCE_QUEUE_KEYS.has(fromQueue.key)
          )
            ? snapshotNextQueueLeadId()
            : undefined
          // Snapshot + arm hold *before* status refetch invalidation so the
          // advance chrome is not blocked by React Query under fake timers.
          if (advanceNextId !== undefined) {
            scheduleQueueAdvanceHold({
              nextId: advanceNextId,
              message: result.completed_task_id
                ? 'Current task completed and lead moved to Skip Trace'
                : 'Lead moved to Skip Trace',
            })
          }
          await handleStatusChanged(result.lead_status as LeadStatus, {
            lead_score: result.lead_score,
            recommended_action: result.recommended_action,
          })
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
    scheduleQueueAdvanceHold,
    snapshotNextQueueLeadId,
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
    setHighlightEntryId(null)
    setActivityModal(null)
    setEditingTask(null)
    setSuppressDialogOpen(false)
    setDncDialogOpen(false)
    setDncPending(false)
    setDncError(null)

    const state = location.state as {
      fromQueue?: FromQueueState
      flashSnackbar?: {
        message: string
        severity?: 'success' | 'warning' | 'error'
        linkTo?: string
        linkLabel?: string
      }
    } | null
    const flash = state?.flashSnackbar
    if (flash?.message) {
      setActivitySnackbar({ open: true, ...flash })
      navigate(
        {
          pathname: location.pathname,
          search: location.search,
        },
        {
          replace: true,
          state: state?.fromQueue ? { fromQueue: state.fromQueue } : null,
        },
      )
    } else {
      setActivitySnackbar({ open: false, message: '' })
    }
  }, [leadId]) // eslint-disable-line react-hooks/exhaustive-deps -- remount flash only on lead change

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

  // RQ success-gap: settled with neither data nor error must not reach `!` accesses
  // (that throw blanks the lead route — no ErrorBoundary on /leads/:id historically).
  if (!commandCenterData) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error" sx={{ mb: 2 }}>
          Lead data is unavailable. Refresh the page or go back to Properties.
        </Alert>
        <Button component={RouterLink} to="/properties" variant="outlined">
          Back to Properties
        </Button>
      </Box>
    )
  }

  // Main layout
  const outreachContact = resolveOutreachContactFromCommandCenter(commandCenterData)
  const recommendedActionValue = commandCenterData.recommended_action?.value ?? null
  const contactMethod = commandCenterData.recommended_action?.recommended_contact_method ?? null
  const placement = outreachContactPlacement(openTasks, outreachContact, recommendedActionValue, {
    // Key Contact card mounts on both lg+ rail and below-lg main stack.
    keyContactCardVisible: true,
  })
  const missingOutreachChannel =
    placement !== 'none' && placement !== 'key_contact_card' && contactMethod && !outreachContact
      ? (contactMethod as OutreachContact['channel'])
      : null
  const recommendedActionWithContact = {
    ...commandCenterData.recommended_action,
    outreach_contact: outreachContact,
  }
  const primaryOwnerName = primaryOwnerDisplayName(
    commandCenterData.contacts,
    commandCenterData.owner_first_name,
    commandCenterData.owner_last_name,
    commandCenterData.organizations,
  )

  return (
    <Box
      data-testid="unified-lead-command-center"
      sx={{
        ...ccPageBgSx,
        maxWidth: '100%',
        minWidth: 0,
        boxSizing: 'border-box',
        pb: 3,
      }}
    >
      {/*
        position: sticky already establishes a containing block (same as
        relative) for the absolutely-positioned QueueAdvanceHoldBanner below —
        the banner overlays this chrome with zero in-flow height instead of
        pushing Property Overview down.
      */}
      <Box
        data-testid="cc-sticky-chrome"
        sx={{ position: 'sticky', top: 0, zIndex: 100, bgcolor: 'grey.50', maxWidth: '100%' }}
      >
        {fromQueue && (
          <QueueWorkHeader
            fromQueue={fromQueue}
            navigation={sessionQueueNavigation}
            isLoading={queueNavLoading}
            sessionBackLeadId={visitedHistory.at(-1) ?? null}
            onAdvance={handleManualQueueAdvance}
            onBackToQueue={() => {
              cancelQueueAdvanceHold()
              returnToQueue()
            }}
            onPrefetchLead={prefetchQueueLead}
          />
        )}
        {queueAdvanceHold && (
          <QueueAdvanceHoldBanner
            key={queueAdvanceHold.startedAt}
            message={queueAdvanceHold.message}
            durationMs={queueAdvanceHold.durationMs}
            destinationLabel={
              queueAdvanceHold.nextId == null
                ? QUEUE_ADVANCE_QUEUE_LABEL
                : QUEUE_ADVANCE_NEXT_LABEL
            }
            onPause={() => cancelQueueAdvanceHold({ snackStay: true })}
          />
        )}

        <Box
          sx={{ pt: 1, display: 'flex', flexDirection: 'column', gap: 0.75 }}
          data-testid="cc-header-stack"
        >
          <PropertyOverviewHeader
            leadId={leadId}
            commandCenterData={commandCenterData}
            scoreRecord={scoreData?.latest}
            onStatusChanged={handleStatusChanged}
            onViewFullBreakdown={handleViewScoreBreakdown}
            fromQueue={fromQueue}
            statusSelectorRef={statusSelectorRef}
            scoreFlash={scoreFlash}
            onNeedsReviewResolved={handleNeedsReviewResolved}
            onCategoryChanged={async () => {
              await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
            }}
            onPropertyOverviewChanged={async () => {
              await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
            }}
            onBeforePinDeprioritize={() => {
              pinDeprioritizeNextIdRef.current = snapshotNextQueueLeadId()
            }}
            onAfterPinDeprioritize={async () => {
              await handleStatusChanged('deprioritize')
              if (fromQueue) {
                scheduleQueueAdvanceHold({
                  nextId: pinDeprioritizeNextIdRef.current,
                  flash: { message: 'Lead deprioritized' },
                  message: 'Lead deprioritized',
                })
              }
            }}
            onMergeDuplicate={() => setSameAddressMergeOpen(true)}
          />
          <DuplicateReviewCallout
            leadId={leadId}
            commandCenterData={commandCenterData}
            onOpenMerge={() => setSameAddressMergeOpen(true)}
            onResolved={handleNeedsReviewResolved}
          />
          <SameAddressMergeBanner
            leadId={leadId}
            open={sameAddressMergeOpen}
            onOpenChange={setSameAddressMergeOpen}
            hideBanner={duplicateReviewActive}
            twins={mergeTwins}
            currentOwnerLabel={
              primaryOwnerDisplayName(
                commandCenterData.contacts,
                commandCenterData.owner_first_name,
                commandCenterData.owner_last_name,
                commandCenterData.organizations,
              ) || `Lead #${leadId}`
            }
            currentPeopleNames={(commandCenterData.contacts ?? [])
              .filter((contact) => (contact.role || '') !== 'former_owner')
              .map((contact) =>
                [contact.first_name, contact.last_name].filter(Boolean).join(' ').trim(),
              )
              .filter(Boolean)}
            onMerged={async ({ winnerId, loserId }) => {
              const mergeFlash = { message: 'Records combined.' }
              setActivitySnackbar({ open: true, ...mergeFlash })
              await afterCommandCenterMutation(queryClient, {
                winnerId,
                loserId,
                navigate,
                fromQueue,
                flashSnackbar: winnerId === leadId ? undefined : mergeFlash,
              })
            }}
          />
        </Box>
      </Box>

      <Box sx={{ pt: ccStackGap, display: 'flex', flexDirection: 'column', gap: ccStackGap }}>
        <Box sx={{ display: 'flex', gap: ccStackGap, alignItems: 'flex-start', maxWidth: '100%', minWidth: 0 }}>
          <Box
            sx={{
              flex: 1,
              minWidth: 0,
              maxWidth: '100%',
              display: 'flex',
              flexDirection: 'column',
              gap: ccStackGap,
              overflow: 'hidden',
            }}
            data-testid="command-center-main-column"
          >
            <Paper sx={ccCardSx} data-testid="lead-action-section">
              <RecommendedActionPanel
                recommendedAction={recommendedActionWithContact}
                leadStatus={commandCenterData.lead_status}
                openTasks={openTasks}
                mailQueueStatus={commandCenterData.mail_queue_status ?? null}
                isMailable={commandCenterData.is_mailable ?? false}
                mailEligible={commandCenterData.mail_eligible}
                mailIneligibleReason={commandCenterData.mail_ineligible_reason}
                mailEligibleDate={commandCenterData.mail_eligible_date}
                ownerMailingReadiness={commandCenterData.owner_mailing_readiness ?? null}
                contactsLikelyPriorOwner={Boolean(
                  commandCenterData.contacts_likely_prior_owner,
                )}
                onApplyParsedMailing={async () => {
                  await commandCenterService.applyParsedOwnerMailing(leadId)
                  await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
                }}
                showOutreachContact={placement === 'recommended_action'}
                embedded
                showActionCenterTiles
                entityResearch={commandCenterData.entity_research ?? null}
                needsEntityResearch={Boolean(commandCenterData.needs_entity_research)}
                onRefreshEntityResearch={async () => {
                  await entityResolutionApi.resolve(leadId, { action: 'resolve', async: false })
                  await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
                }}
                onAction={handleRaAction}
                onDeprioritize={async (reason) => {
                  const nextLeadId = snapshotNextQueueLeadId()
                  const result = await commandCenterService.updateStatus(
                    leadId,
                    'deprioritize',
                    reason || undefined,
                  )
                  if (fromQueue) {
                    scheduleQueueAdvanceHold({
                      nextId: nextLeadId,
                      flash: { message: 'Lead deprioritized' },
                      message: 'Lead deprioritized',
                    })
                  } else {
                    setActivitySnackbar({
                      open: true,
                      message: 'Lead deprioritized',
                    })
                  }
                  await handleStatusChanged(result.lead_status as LeadStatus, {
                    lead_score: result.lead_score,
                    recommended_action: result.recommended_action,
                  })
                }}
                onDismissRecentSale={async () => {
                  await leadService.dismissRecentSale(leadId, {
                    reason: 'not_this_unit',
                    clear_pin: true,
                  })
                  setActivitySnackbar({
                    open: true,
                    message: 'Recent sale cleared — pick the correct unit PIN if needed',
                  })
                  await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
                  await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
                }}
                onCreateTask={handleCreateTask}
              />
            </Paper>

            <Box
              data-testid="command-center-activity-stack"
              sx={{ display: 'flex', flexDirection: 'column', gap: ccStackGap }}
            >
            <Paper sx={ccCardSx} data-testid="open-tasks-card">
              <TasksPanel
                ref={tasksPanelRef}
                leadId={leadId}
                initialTasks={openTasks}
                activityEntries={taskActivityEntries}
                outreachContact={outreachContact}
                showOutreachContactOnPrimaryTask={placement === 'primary_task'}
                missingOutreachChannel={missingOutreachChannel}
                mailQueueStatus={commandCenterData.mail_queue_status ?? null}
                upNextToMail={Boolean(commandCenterData.up_next_to_mail)}
                embedded
                onTasksChanged={() => queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })}
                onEditTask={handleEditOpenTask}
                onAfterTaskCompleted={fromQueue ? () => {
                  scheduleQueueAdvanceHold({
                    nextId: snapshotNextQueueLeadId(),
                    message: 'Task completed',
                  })
                } : undefined}
              />
            </Paper>

            <ActivityPanel
              ref={activityRef}
              leadId={leadId}
              initialEntries={commandCenterData.timeline.entries}
              initialTotal={commandCenterData.timeline.total}
              highlightEntryId={highlightEntryId}
              variant="feed"
              embedded
              onEntriesChanged={handleActivityEntriesChanged}
            />

            {!isLgUp && (
              <>
                <KeyContactCard
                  name={primaryOwnerName}
                  commandCenterData={commandCenterData}
                />
                <PropertyKpiCard
                  commandCenterData={commandCenterData}
                  propertyDetail={leadData}
                />
                <PropertySidebar
                  variant="inline"
                  commandCenterData={commandCenterData}
                  onViewSaleHistory={handleViewSaleHistory}
                  hideContactSection
                  collapseSecondary
                />
              </>
            )}

            <BuildingOwnershipSection
              leadId={leadId}
              commandCenterData={commandCenterData}
            />
            </Box>

            <LeadBriefingPanel
                leadId={leadId}
                initialBriefing={commandCenterData.quick_briefing ?? null}
              />

            <DeepDiveDetailsCard>
              {leadData ? (
                <LeadDetailTabPanel
                  leadId={leadId}
                  leadData={leadData}
                  commandCenterData={commandCenterData}
                  scoreData={scoreData}
                  scoreLoading={scoreLoading}
                />
              ) : leadLoading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress size={28} aria-label="Loading property details" />
                </Box>
              ) : null}
            </DeepDiveDetailsCard>
          </Box>

          <Box
            sx={{
              width: 320,
              flexShrink: 0,
              display: { xs: 'none', lg: 'flex' },
              flexDirection: 'column',
              gap: ccStackGap,
            }}
          >
            {isLgUp && (
              <>
                <KeyContactCard
                  name={primaryOwnerName}
                  commandCenterData={commandCenterData}
                  sticky
                />
                <PropertyKpiCard
                  commandCenterData={commandCenterData}
                  propertyDetail={leadData}
                />
                <PropertySidebar
                  commandCenterData={commandCenterData}
                  onViewSaleHistory={handleViewSaleHistory}
                  hideContactSection
                  collapseSecondary
                  sticky={false}
                />
              </>
            )}
          </Box>
        </Box>
      </Box>

      <LogActivityModal
        open={activityModal != null}
        activityType={activityModal}
        leadId={leadId}
        openTasks={openTasks}
        preferredPhoneDigits={
          commandCenterData.dial_target?.value
          ?? (
            outreachContact?.channel === 'phone' || outreachContact?.channel === 'text'
              ? outreachContact.value
              : null
          )
        }
        editTask={editingTaskDraft}
        onClose={() => {
          setActivityModal(null)
          setEditingTask(null)
        }}
        onSaved={handleActivitySaved}
        onTaskUpdated={handleTaskUpdatedFromOverlay}
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

      <Dialog
        open={mailNudgeOpen}
        onClose={mailNudgePending ? undefined : () => { dismissMailNudgeLocal() }}
        aria-labelledby="unanswered-mail-nudge-title"
        data-testid="unanswered-mail-nudge-dialog"
      >
        <DialogTitle id="unanswered-mail-nudge-title">
          Try Direct Mail instead?
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            You&apos;ve called 3 times with no answer. Switch this lead to Direct Mail, or keep calling?
          </DialogContentText>
          {mailNudgeError && (
            <DialogContentText color="error" sx={{ mt: 1 }} data-testid="unanswered-mail-nudge-error">
              {mailNudgeError}
            </DialogContentText>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => { void handleMailNudgeSwitchToMail() }}
            disabled={mailNudgePending}
            data-testid="unanswered-mail-nudge-switch"
          >
            Switch to Direct Mail
          </Button>
          <Button
            variant="contained"
            autoFocus
            onClick={() => { void handleMailNudgeKeepCalling() }}
            disabled={mailNudgePending}
            data-testid="unanswered-mail-nudge-keep-calling"
          >
            {mailNudgePending ? 'Saving…' : 'Keep calling'}
          </Button>
        </DialogActions>
      </Dialog>

      <AppSnackbar
        open={activitySnackbar.open}
        onClose={() => setActivitySnackbar((s) => ({ ...s, open: false }))}
        message={activitySnackbar.message}
        severity={activitySnackbar.severity ?? 'success'}
        data-testid="activity-success-snackbar"
        alertTestId="activity-success-alert"
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
      />
    </Box>
  )
}
