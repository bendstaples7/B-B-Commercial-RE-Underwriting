/**
 * RecommendedActionPanel — displays the current Recommended Action for a lead,
 * including its label, explanation, and 1–5 action buttons.
 *
 * Requirements: 7.2, 7.3, 7.4, 4.3
 */
import { useState, type ReactElement } from 'react'
import { Link } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import BlockIcon from '@mui/icons-material/Block'
import AddTaskIcon from '@mui/icons-material/AddTask'
import PhoneIcon from '@mui/icons-material/Phone'
import StickyNote2OutlinedIcon from '@mui/icons-material/StickyNote2Outlined'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import LocalPostOfficeOutlinedIcon from '@mui/icons-material/LocalPostOfficeOutlined'
import PersonSearchOutlinedIcon from '@mui/icons-material/PersonSearchOutlined'
import TravelExploreOutlinedIcon from '@mui/icons-material/TravelExploreOutlined'
import AnalyticsOutlinedIcon from '@mui/icons-material/AnalyticsOutlined'
import ContactMailOutlinedIcon from '@mui/icons-material/ContactMailOutlined'
import PinDropOutlinedIcon from '@mui/icons-material/PinDropOutlined'
import EventAvailableOutlinedIcon from '@mui/icons-material/EventAvailableOutlined'
import DoNotDisturbOnOutlinedIcon from '@mui/icons-material/DoNotDisturbOnOutlined'
import BusinessOutlinedIcon from '@mui/icons-material/BusinessOutlined'
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline'
import type { RecommendedActionMeta, LeadStatus, LeadTask, CRMRecommendedAction, OutreachContact, EntityResearchSummary, OwnerMailingReadiness } from '@/types'
import { outreachDisplayLabel } from '@/constants/scoringRecommendedActions'
import { OutreachContactInline, OutreachContactMissingHint } from '@/components/OutreachContactCallout'
import { formatDateOnly } from '@/utils/helpers'
import { formatDate } from '@/utils/formatters'
import {
  type QuickActionId,
  evaluateMoveToSkipTrace,
  unavailableReasonForQuickAction,
} from '@/utils/actionEligibility'
import {
  formatOwnerMailingLine,
  renderOriginalMailingWithStrikes,
} from '@/utils/ownerMailingAddressDiff'
import { ccActionTileSx, ccSectionTitleSx } from '@/components/lead-detail/commandCenterChrome'

// ---------------------------------------------------------------------------
// Action button definitions per RA type
// ---------------------------------------------------------------------------

interface ActionButton {
  label: string
  action: string
  /** Whether this button is an outreach action (disabled for DNC leads) */
  isOutreach?: boolean
  title?: string
}

const ACTION_ICONS: Record<string, ReactElement> = {
  log_call: <PhoneIcon fontSize="small" />,
  log_note: <StickyNote2OutlinedIcon fontSize="small" />,
  log_email: <EmailOutlinedIcon fontSize="small" />,
  add_to_mail_batch: <LocalPostOfficeOutlinedIcon fontSize="small" />,
  move_to_skip_trace: <PersonSearchOutlinedIcon fontSize="small" />,
  research_llc: <BusinessOutlinedIcon fontSize="small" />,
  create_task: <AddTaskIcon fontSize="small" />,
  run_analysis: <AnalyticsOutlinedIcon fontSize="small" />,
  research_property: <TravelExploreOutlinedIcon fontSize="small" />,
  add_contact_info: <ContactMailOutlinedIcon fontSize="small" />,
  search_property: <TravelExploreOutlinedIcon fontSize="small" />,
  research_pin: <PinDropOutlinedIcon fontSize="small" />,
  adjust_for_recent_sale: <EventAvailableOutlinedIcon fontSize="small" />,
  suppress: <DoNotDisturbOnOutlinedIcon fontSize="small" />,
  do_not_contact: <BlockIcon fontSize="small" />,
  deprioritize: <PauseCircleOutlineIcon fontSize="small" />,
}

const CONDO_DEPRIORITIZE_REASON =
  'Likely condoized / multi-PIN tax situs — confirm deprioritize.'

/** Fixed Quick actions order for every lead — unavailable actions stay visible but disabled. */
const UNIVERSAL_ACTIONS: ActionButton[] = [
  { label: 'Log Call', action: 'log_call', isOutreach: true },
  { label: 'Log Note', action: 'log_note' },
  { label: 'Log Email', action: 'log_email', isOutreach: true },
  {
    label: 'Add to Mail Queue',
    action: 'add_to_mail_batch',
    isOutreach: true,
  },
  {
    label: 'Move to Skip Trace',
    action: 'move_to_skip_trace',
    isOutreach: true,
    title: 'Complete the current task, change status to Skip Trace, and create awaiting skip-trace work',
  },
  {
    label: 'Deprioritize',
    action: 'deprioritize',
    title: 'Park this lead from active queues',
  },
]

const RUN_ANALYSIS_BUTTON: ActionButton = { label: 'Run Analysis', action: 'run_analysis' }

function withRunAnalysis(buttons: ActionButton[]): ActionButton[] {
  if (buttons.some((b) => b.action === 'run_analysis')) return buttons
  return [...buttons, RUN_ANALYSIS_BUTTON]
}

const METHOD_PRIMARY_ACTIONS: Record<string, string> = {
  phone: 'log_call',
  email: 'log_email',
  text: 'log_call',
}

function prioritizeButtonsForMethod(
  buttons: ActionButton[],
  method?: string | null,
): ActionButton[] {
  if (!method) return buttons
  const primary = METHOD_PRIMARY_ACTIONS[method]
  if (!primary) return buttons
  const match = buttons.find((b) => b.action === primary)
  if (!match) return buttons
  return [match, ...buttons.filter((b) => b.action !== primary)]
}

const ACTION_BUTTONS: Record<CRMRecommendedAction, ActionButton[]> = {
  review_now: withRunAnalysis([
    { label: 'Research Property', action: 'research_property' },
    { label: 'Log Note', action: 'log_note' },
    { label: 'Create Task', action: 'create_task' },
  ]),
  mail_ready: withRunAnalysis([
    { label: 'Log Note', action: 'log_note' },
  ]),
  call_ready: withRunAnalysis([
    { label: 'Log Call', action: 'log_call', isOutreach: true },
    { label: 'Create Task', action: 'create_task' },
  ]),
  valuation_needed: [
    { label: 'Run Analysis', action: 'run_analysis' },
    { label: 'Research Property', action: 'research_property' },
  ],
  needs_manual_review: [
    { label: 'Log Note', action: 'log_note' },
    { label: 'Create Task', action: 'create_task' },
  ],
  enrich_data: [
    { label: 'Move to Skip Trace', action: 'move_to_skip_trace' },
    { label: 'Add Contact Info', action: 'add_contact_info' },
    { label: 'Research Property', action: 'research_property' },
  ],
  resolve_match: [
    { label: 'Search Property', action: 'search_property' },
    { label: 'Research PIN', action: 'research_pin' },
  ],
  analyze_property: [
    { label: 'Run Analysis', action: 'run_analysis' },
  ],
  follow_up_now: withRunAnalysis([
    { label: 'Log Call', action: 'log_call', isOutreach: true },
    { label: 'Log Note', action: 'log_note', isOutreach: true },
    { label: 'Create Task', action: 'create_task' },
  ]),
  ready_for_outreach: withRunAnalysis([
    { label: 'Log Call', action: 'log_call', isOutreach: true },
    { label: 'Log Note', action: 'log_note', isOutreach: true },
    { label: 'Create Task', action: 'create_task' },
  ]),
  add_contact_info: [
    { label: 'Add Contact Info', action: 'add_contact_info' },
    { label: 'Move to Skip Trace', action: 'move_to_skip_trace' },
  ],
  create_task: [
    { label: 'Create Task', action: 'create_task' },
  ],
  nurture: [],
  hold: [
    { label: 'Adjust for Recent Sale', action: 'adjust_for_recent_sale' },
  ],
  // Terminal RA values — lead is already parked/DNC; no extra CTA.
  // Suppress/DNC dialogs remain reachable via the status selector in CC.
  suppress: [],
  do_not_contact: [],
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface RecommendedActionPanelProps {
  recommendedAction: RecommendedActionMeta | null
  leadStatus: LeadStatus
  openTasks: LeadTask[]
  mailQueueStatus?: 'queued' | 'sent_recently' | null
  isMailable?: boolean
  mailEligible?: boolean
  mailIneligibleReason?: string | null
  mailEligibleDate?: string | null
  /** Owner mailing parse preview when Add to Mail Queue is blocked. */
  ownerMailingReadiness?: OwnerMailingReadiness | null
  /** Persist parsed mailing_* and refresh command center. */
  onApplyParsedMailing?: () => Promise<void>
  /** When true, contacts are prior-owner / post-sale stale — hide mailing "fix" chrome. */
  contactsLikelyPriorOwner?: boolean
  /** When true, show outreach contact inline under the action label */
  showOutreachContact?: boolean
  /** Drop outer border when nested inside a shared action card. */
  embedded?: boolean
  /** Show Action Center icon tiles for standardized universal Quick actions. */
  showActionCenterTiles?: boolean
  /** Illinois LLC / org research status for visibility + refresh. */
  entityResearch?: EntityResearchSummary | null
  onRefreshEntityResearch?: () => Promise<void>
  /** Owner looks like unresolved LLC/org — show Research LLC tile (independent of RA). */
  needsEntityResearch?: boolean
  onAction: (action: string) => Promise<void>
  /** Park lead with optional reason (universal Deprioritize / Confirm deprioritize). */
  onDeprioritize?: (reason: string) => Promise<void>
  onCreateTask?: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * RecommendedActionPanel renders the current Recommended Action with its
 * label, explanation, and action buttons.
 *
 * - Shows "DO NOT CONTACT" badge and disables outreach buttons when
 *   leadStatus === 'do_not_contact' (Req 7.2, 14.2).
 * - Shows inline error on action failure without changing Timeline or RA (Req 7.4).
 * - Shows "Create Task" CTA when RA is `create_task` and no open tasks (Req 4.3).
 */
export function RecommendedActionPanel({
  recommendedAction,
  leadStatus,
  openTasks,
  mailQueueStatus = null,
  isMailable = false,
  mailEligible,
  mailIneligibleReason = null,
  mailEligibleDate = null,
  ownerMailingReadiness = null,
  onApplyParsedMailing,
  contactsLikelyPriorOwner = false,
  showOutreachContact = false,
  embedded = false,
  showActionCenterTiles = false,
  entityResearch = null,
  onRefreshEntityResearch,
  needsEntityResearch = false,
  onAction,
  onDeprioritize,
  onCreateTask,
}: RecommendedActionPanelProps) {
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [researchPending, setResearchPending] = useState(false)
  const [applyMailingPending, setApplyMailingPending] = useState(false)
  const [deprioritizeOpen, setDeprioritizeOpen] = useState(false)
  const [deprioritizeReason, setDeprioritizeReason] = useState('')
  const [deprioritizePending, setDeprioritizePending] = useState(false)

  const isDNC = leadStatus === 'do_not_contact'
  const isInMailBatch = mailQueueStatus === 'queued'
  const confirmCondoDeprioritize = recommendedAction?.winning_rule === 'likely_condo'
  const universalActions = UNIVERSAL_ACTIONS.map((btn) => {
    if (btn.action !== 'deprioritize') return btn
    if (!confirmCondoDeprioritize) return btn
    return {
      ...btn,
      label: 'Confirm deprioritize',
      title: CONDO_DEPRIORITIZE_REASON,
    }
  })
  const llcResearchPrimary =
    typeof onRefreshEntityResearch === 'function'
    && !confirmCondoDeprioritize
    && (
      needsEntityResearch
      || (
        recommendedAction?.value === 'enrich_data'
        && recommendedAction?.winning_rule === 'research_entity_owner'
      )
    )
  const eligibilityCtx = {
    leadStatus,
    mailQueueStatus,
    mailEligible,
    isMailable,
    mailIneligibleReason,
    mailEligibleDate,
  }
  const panelSx = embedded
    ? { p: 0, maxWidth: '100%', minWidth: 0, overflow: 'hidden' }
    : { p: 2, border: 1, borderColor: 'divider', borderRadius: 1, maxWidth: '100%', minWidth: 0, overflow: 'hidden' }
  const mailHoldAlert = mailIneligibleReason === 'recently_sold' ? (
    <Alert severity="warning" sx={{ mb: 2 }} data-testid="recent-sale-mail-hold">
      Recent sale detected. Deprioritized for the recent-sale hold
      {mailEligibleDate
        ? ` until ${formatDateOnly(mailEligibleDate)}.`
        : ' until the two-year hold ends.'}
      {' '}When the hold expires, the lead moves to Skip Trace for active work.
    </Alert>
  ) : null

  const showMailAddressAlert =
    !contactsLikelyPriorOwner
    && (
      mailIneligibleReason === 'invalid_owner_address'
      || Boolean(ownerMailingReadiness?.can_apply_parsed)
      || (
        mailEligible === false
        && ownerMailingReadiness != null
        && !ownerMailingReadiness.is_mailable
      )
    )
    && mailIneligibleReason !== 'recently_sold'

  const handleApplyParsedMailing = async () => {
    if (!onApplyParsedMailing) return
    setActionError(null)
    setApplyMailingPending(true)
    try {
      await onApplyParsedMailing()
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Could not apply parsed mailing address.',
      )
    } finally {
      setApplyMailingPending(false)
    }
  }

  const mailAddressAlert = showMailAddressAlert ? (
    <Alert
      severity="info"
      sx={{ mb: 2 }}
      data-testid="owner-mailing-readiness"
    >
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, width: '100%' }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 2,
            flexWrap: 'wrap',
            width: '100%',
          }}
        >
          <Typography variant="body2" component="div" sx={{ minWidth: 0, flex: '1 1 220px' }}>
            Owner mailing address needs a fix before mail
          </Typography>
          {ownerMailingReadiness?.can_apply_parsed && onApplyParsedMailing ? (
            <Button
              size="small"
              variant="contained"
              color="primary"
              disabled={applyMailingPending || pendingAction !== null}
              onClick={() => void handleApplyParsedMailing()}
              startIcon={
                applyMailingPending
                  ? <CircularProgress size={14} color="inherit" />
                  : undefined
              }
              data-testid="apply-parsed-owner-mailing"
              sx={{ flexShrink: 0 }}
            >
              Use corrected address
            </Button>
          ) : null}
        </Box>
        {ownerMailingReadiness?.reason ? (
          <Typography variant="caption" color="text.secondary" component="div">
            {ownerMailingReadiness.reason}
          </Typography>
        ) : null}
        {ownerMailingReadiness?.parsed ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.35 }}>
            <Typography
              variant="body2"
              component="div"
              data-testid="mailing-address-original"
              sx={{ color: 'text.secondary' }}
            >
              <Box component="span" sx={{ fontWeight: 600, color: 'text.primary', mr: 0.75 }}>
                Original
              </Box>
              {renderOriginalMailingWithStrikes(
                ownerMailingReadiness.raw,
                ownerMailingReadiness.parsed,
              )}
            </Typography>
            <Typography
              variant="body2"
              component="div"
              data-testid="mailing-address-corrected"
            >
              <Box component="span" sx={{ fontWeight: 600, mr: 0.75 }}>
                Corrected
              </Box>
              {formatOwnerMailingLine(ownerMailingReadiness.parsed)}
            </Typography>
          </Box>
        ) : ownerMailingReadiness?.raw.street ? (
          <Typography
            variant="body2"
            color="text.secondary"
            component="div"
            data-testid="mailing-address-original"
          >
            <Box component="span" sx={{ fontWeight: 600, color: 'text.primary', mr: 0.75 }}>
              Original
            </Box>
            {formatOwnerMailingLine(ownerMailingReadiness.raw)}
          </Typography>
        ) : null}
      </Box>
    </Alert>
  ) : null

  const handleAction = async (action: string) => {
    setActionError(null)
    if (action === 'research_llc' && typeof onRefreshEntityResearch === 'function') {
      setResearchPending(true)
      try {
        await onRefreshEntityResearch()
      } catch (err) {
        setActionError(
          err instanceof Error ? err.message : 'Entity research failed.',
        )
      } finally {
        setResearchPending(false)
      }
      return
    }
    setPendingAction(action)
    try {
      await onAction(action)
    } catch (err) {
      setActionError(
        err instanceof Error ? err.message : 'Action failed. Please try again.'
      )
    } finally {
      setPendingAction(null)
    }
  }

  const unavailableReasonFor = (btn: ActionButton): string | null => {
    if (btn.action === 'deprioritize') {
      if (typeof onDeprioritize !== 'function') {
        return 'Deprioritize is not available here'
      }
      if (
        leadStatus === 'deprioritize'
        || leadStatus === 'suppressed'
        || leadStatus === 'deal_won'
        || leadStatus === 'deal_lost'
        || leadStatus === 'do_not_contact'
      ) {
        return 'Not available for this lead status'
      }
      return null
    }
    if (
      btn.action === 'log_call'
      || btn.action === 'log_note'
      || btn.action === 'log_email'
      || btn.action === 'add_to_mail_batch'
      || btn.action === 'move_to_skip_trace'
    ) {
      const reason = unavailableReasonForQuickAction(
        btn.action as QuickActionId,
        eligibilityCtx,
      )
      if (reason) return reason
    }
    if (isDNC && btn.isOutreach === true) {
      return 'Outreach is blocked — lead is Do Not Contact'
    }
    return null
  }

  const openDeprioritizeDialog = () => {
    setActionError(null)
    setDeprioritizeReason(confirmCondoDeprioritize ? CONDO_DEPRIORITIZE_REASON : '')
    setDeprioritizeOpen(true)
  }

  const confirmDeprioritize = async () => {
    if (!onDeprioritize) return
    setDeprioritizePending(true)
    setActionError(null)
    try {
      await onDeprioritize(deprioritizeReason.trim())
      setDeprioritizeOpen(false)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Could not deprioritize lead.')
    } finally {
      setDeprioritizePending(false)
    }
  }

  const renderActionButton = (btn: ActionButton, testIdPrefix = 'ra-action-btn', primary = false) => {
    const unavailableReason = unavailableReasonFor(btn)
    const isDisabled = unavailableReason != null
      || (btn.action === 'research_llc' && researchPending)
    const isLoading =
      pendingAction === btn.action
      || (btn.action === 'research_llc' && researchPending)
    const title =
      unavailableReason
      ?? btn.title
      ?? (btn.action === 'park'
        ? 'Hide this lead from active queues until a future re-activation date'
        : undefined)

    const button = (
      <Button
        key={btn.action}
        variant={primary ? 'contained' : 'outlined'}
        size="small"
        disabled={isDisabled || (pendingAction !== null && pendingAction !== btn.action)}
        onClick={() => {
          if (btn.action === 'deprioritize') {
            openDeprioritizeDialog()
            return
          }
          void handleAction(btn.action)
        }}
        title={isDisabled ? undefined : title}
        startIcon={
          isLoading ? (
            <CircularProgress size={14} color="inherit" />
          ) : (
            ACTION_ICONS[btn.action] ?? undefined
          )
        }
        data-testid={`${testIdPrefix}-${btn.action}`}
        aria-label={btn.label}
        sx={{
          width: { xs: '100%', sm: 'auto' },
          justifyContent: { xs: 'flex-start', sm: 'center' },
          flexShrink: 0,
          maxWidth: '100%',
        }}
      >
        {isLoading ? 'Working…' : btn.label}
      </Button>
    )
    return isDisabled && unavailableReason ? (
      <Tooltip key={btn.action} title={unavailableReason}>
        <span
          tabIndex={0}
          role="button"
          aria-disabled="true"
          aria-label={`${btn.label} unavailable: ${unavailableReason}`}
          style={{ display: 'inline-flex', maxWidth: '100%' }}
        >
          {button}
        </span>
      </Tooltip>
    ) : button
  }

  const actionStackSx = {
    width: '100%',
    maxWidth: '100%',
  } as const

  const renderInMailBatchControls = (testIdPrefix: string) => (
    <Stack
      key="in-mail-batch"
      direction={{ xs: 'column', sm: 'row' }}
      spacing={1}
      alignItems={{ xs: 'stretch', sm: 'center' }}
      flexWrap="wrap"
      useFlexGap
      sx={{ width: { xs: '100%', sm: 'auto' } }}
    >
      <Button
        variant="outlined"
        size="small"
        disabled
        data-testid={`${testIdPrefix}-in-mail-batch`}
        sx={{ width: { xs: '100%', sm: 'auto' } }}
      >
        In mail batch
      </Button>
      <Button
        component={Link}
        to="/queues/ready-to-mail"
        variant="text"
        size="small"
        data-testid={`${testIdPrefix}-view-mail-batch`}
        sx={{ width: { xs: '100%', sm: 'auto' } }}
      >
        View batch
      </Button>
    </Stack>
  )

  const renderAlreadyInSkipTraceControls = (testIdPrefix: string) => {
    const skipEval = evaluateMoveToSkipTrace(leadStatus)
    return (
      <Button
        key="already-skip-trace"
        variant="outlined"
        size="small"
        disabled
        title={skipEval.message ?? 'Already in the Skip Trace work queue'}
        data-testid={`${testIdPrefix}-already-skip-trace`}
        sx={{
          width: { xs: '100%', sm: 'auto' },
          justifyContent: { xs: 'flex-start', sm: 'center' },
        }}
      >
        In Skip Trace
      </Button>
    )
  }

  const renderActionCenterTiles = (extraTiles: ActionButton[] = []) => {
    if (!showActionCenterTiles) return null

    const tileButtons: ActionButton[] = [
      ...(llcResearchPrimary
        ? [{
            label: researchPending ? 'Researching…' : 'Research LLC',
            action: 'research_llc',
            title: 'Look up Illinois LLC / organization records for this owner',
          } satisfies ActionButton]
        : []),
      ...universalActions,
      ...extraTiles.filter(
        (btn) => (
          btn.action !== 'research_llc'
          && btn.action !== 'move_to_skip_trace'
          && btn.action !== 'deprioritize'
          // Terminal RA values map to Suppress/DNC buttons — never float those as
          // Action Center tiles (Deprioritize is already universal; lead may already be parked).
          && btn.action !== 'suppress'
          && btn.action !== 'do_not_contact'
          && !universalActions.some((u) => u.action === btn.action)
          && !(llcResearchPrimary && btn.action === 'research_llc')
        ),
      ),
    ]

    const renderUniversalTile = (btn: ActionButton) => {
      if (btn.action === 'add_to_mail_batch' && isInMailBatch) {
        return (
          <Box
            key="in-mail-batch"
            sx={{ display: 'contents' }}
          >
            <Button
              disabled
              data-testid="action-center-tile-in-mail-batch"
              aria-label="In mail batch"
              sx={ccActionTileSx}
            >
              {ACTION_ICONS.add_to_mail_batch}
              In mail batch
            </Button>
            <Button
              component={Link}
              to="/queues/ready-to-mail"
              data-testid="action-center-tile-view-mail-batch"
              aria-label="View batch"
              sx={ccActionTileSx}
            >
              {ACTION_ICONS.add_to_mail_batch}
              View batch
            </Button>
          </Box>
        )
      }

      if (
        btn.action === 'move_to_skip_trace'
        && evaluateMoveToSkipTrace(leadStatus).alreadyDone
      ) {
        const skipEval = evaluateMoveToSkipTrace(leadStatus)
        const reason = skipEval.message ?? 'Already in the Skip Trace work queue'
        return (
          <Tooltip key="already-skip-trace" title={reason}>
            <span style={{ display: 'inline-flex', flex: '1 1 0', minWidth: 0 }}>
              <Button
                disabled
                title={reason}
                data-testid="action-center-tile-already-skip-trace"
                aria-label={`Move to Skip Trace unavailable: ${reason}`}
                sx={{ ...ccActionTileSx, width: '100%' }}
              >
                {ACTION_ICONS.move_to_skip_trace}
                In Skip Trace
              </Button>
            </span>
          </Tooltip>
        )
      }

      const unavailableReason = unavailableReasonFor(btn)
      const isDisabled =
        unavailableReason != null
        || pendingAction !== null
        || deprioritizePending
        || (btn.action === 'research_llc' && researchPending)
      const isLoading =
        pendingAction === btn.action
        || (btn.action === 'research_llc' && researchPending)
      const title = unavailableReason ?? btn.title
      const highlightConfirm = btn.action === 'deprioritize' && confirmCondoDeprioritize

      const tileBtn = (
        <Button
          key={btn.action}
          onClick={() => {
            if (btn.action === 'deprioritize') {
              openDeprioritizeDialog()
              return
            }
            void handleAction(btn.action)
          }}
          disabled={isDisabled}
          data-testid={`action-center-tile-${btn.action}`}
          aria-label={btn.label}
          title={isDisabled ? undefined : title}
          sx={{
            ...ccActionTileSx,
            ...(highlightConfirm
              ? {
                  bgcolor: 'primary.main',
                  color: 'primary.contrastText',
                  '&:hover': { bgcolor: 'primary.dark', borderColor: 'primary.dark' },
                }
              : {}),
          }}
        >
          {isLoading ? <CircularProgress size={22} color="inherit" /> : (ACTION_ICONS[btn.action] ?? null)}
          {isLoading ? 'Working…' : btn.label}
        </Button>
      )

      return isDisabled && unavailableReason ? (
        <Tooltip key={btn.action} title={unavailableReason}>
          <span
            tabIndex={0}
            role="button"
            aria-disabled="true"
            aria-label={`${btn.label} unavailable: ${unavailableReason}`}
            style={{ display: 'inline-flex', flex: '1 1 0', minWidth: 0 }}
          >
            {tileBtn}
          </span>
        </Tooltip>
      ) : tileBtn
    }

    return (
      <Box sx={{ mb: 1.25 }} data-testid="action-center-tiles">
        <Typography sx={{ ...ccSectionTitleSx, mb: 1 }} component="h3">
          Action Center
        </Typography>
        <Box
          sx={{
            display: 'flex',
            flexWrap: { xs: 'wrap', sm: 'nowrap' },
            gap: 1,
            width: '100%',
          }}
        >
          {tileButtons.map((btn) => renderUniversalTile(btn))}
        </Box>
      </Box>
    )
  }

  const renderUniversalActions = (raButtons: ActionButton[] = []) => {
    // Tiles replace the Quick actions row when Action Center chrome is on.
    if (showActionCenterTiles) return null

    return (
    <Box sx={{ mb: raButtons.length > 0 ? 2 : 0, mt: 2, maxWidth: '100%' }}>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        Quick actions
      </Typography>
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        flexWrap="wrap"
        useFlexGap
        sx={actionStackSx}
        data-testid="ra-universal-actions"
      >
        {universalActions.map((btn) => {
          if (btn.action === 'add_to_mail_batch' && isInMailBatch) {
            return renderInMailBatchControls('ra-universal-btn')
          }
          if (
            btn.action === 'move_to_skip_trace'
            && evaluateMoveToSkipTrace(leadStatus).alreadyDone
          ) {
            return renderAlreadyInSkipTraceControls('ra-universal-btn')
          }
          return renderActionButton(btn, 'ra-universal-btn')
        })}
      </Stack>
    </Box>
    )
  }

  const renderEntityResearch = () => {
    if (!entityResearch) return null
    const llcPrimaryActive = llcResearchPrimary
    return (
      <Box sx={{ mb: 2 }} data-testid="entity-research-status">
        <Typography variant="caption" color="text.secondary" display="block">
          {entityResearch.entity_lookup_checked_at
            ? `Last researched ${formatDate(entityResearch.entity_lookup_checked_at)}`
            : 'Never researched (Illinois LLC / org)'}
          {entityResearch.entity_lookup_status
            ? ` · ${String(entityResearch.entity_lookup_status).replace(/_/g, ' ')}`
            : ''}
          {entityResearch.organization_name
            ? ` · ${entityResearch.organization_name}`
            : ''}
        </Typography>
        {entityResearch.entity_lookup_error && (
          <Typography variant="caption" color="error" display="block">
            {entityResearch.entity_lookup_error}
          </Typography>
        )}
        {!llcPrimaryActive && typeof onRefreshEntityResearch === 'function' && (
          <Button
            size="small"
            variant="outlined"
            sx={{ mt: 0.75 }}
            disabled={researchPending || pendingAction !== null}
            onClick={async () => {
              setResearchPending(true)
              setActionError(null)
              try {
                await onRefreshEntityResearch()
              } catch (err) {
                setActionError(
                  err instanceof Error ? err.message : 'Entity research failed.',
                )
              } finally {
                setResearchPending(false)
              }
            }}
            data-testid="refresh-entity-research-btn"
          >
            {researchPending ? 'Researching…' : 'Refresh research'}
          </Button>
        )}
      </Box>
    )
  }

  const deprioritizeDialog = (
    <Dialog
      open={deprioritizeOpen}
      onClose={() => {
        if (!deprioritizePending) setDeprioritizeOpen(false)
      }}
      fullWidth
      maxWidth="xs"
      data-testid="deprioritize-confirm-dialog"
    >
      <DialogTitle>
        {confirmCondoDeprioritize ? 'Confirm deprioritize' : 'Deprioritize lead'}
      </DialogTitle>
      <DialogContent>
        {actionError && (
          <Alert severity="error" sx={{ mb: 1.5 }} data-testid="deprioritize-error">
            {actionError}
          </Alert>
        )}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Park this lead from active queues. You can change status later.
        </Typography>
        <TextField
          label="Reason"
          value={deprioritizeReason}
          onChange={(e) => setDeprioritizeReason(e.target.value.slice(0, 500))}
          fullWidth
          multiline
          minRows={2}
          inputProps={{ maxLength: 500 }}
          data-testid="deprioritize-reason"
        />
      </DialogContent>
      <DialogActions>
        <Button
          onClick={() => setDeprioritizeOpen(false)}
          disabled={deprioritizePending}
        >
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={() => { void confirmDeprioritize() }}
          disabled={deprioritizePending || !onDeprioritize}
          data-testid="deprioritize-confirm"
        >
          {deprioritizePending ? 'Saving…' : 'Deprioritize'}
        </Button>
      </DialogActions>
    </Dialog>
  )

  // No RA assigned — still show entity research + universal quick actions
  if (!recommendedAction || !recommendedAction.value) {
    return (
      <Box
        data-testid="recommended-action-panel"
        sx={panelSx}
      >
        {mailHoldAlert}
        {mailAddressAlert}
        {isDNC && (
          <Chip
            icon={<BlockIcon />}
            label="DO NOT CONTACT"
            color="error"
            size="small"
            sx={{ mb: 1 }}
            data-testid="dnc-badge"
          />
        )}
        {renderActionCenterTiles()}
        {openTasks.length > 0 ? (
          <Typography variant="body2" color="text.secondary" data-testid="ra-next-task-title">
            {openTasks[0].title}
          </Typography>
        ) : (
          <Typography variant="body2" color="text.secondary">
            No recommended action at this time.
          </Typography>
        )}
        {renderEntityResearch()}
        {actionError && !deprioritizeOpen && (
          <Alert
            severity="error"
            sx={{ mt: 2, mb: 0 }}
            onClose={() => setActionError(null)}
            data-testid="ra-action-error"
          >
            {actionError}
          </Alert>
        )}
        {renderUniversalActions()}
        {deprioritizeDialog}
      </Box>
    )
  }

  const { value, label, explanation, recommended_contact_method: contactMethod, outreach_contact: outreachContact, winning_rule_label: winningRuleLabel } = recommendedAction
  const hasOpenTasks = openTasks.length > 0
  const recentSaleHoldRa = (
    value === 'hold'
    || recommendedAction.winning_rule === 'recent_sale_hold'
  )
  const displayLabel = (() => {
    if (llcResearchPrimary) {
      return 'Research LLC'
    }
    // Mid-hold parks as deprioritize but must show hold copy, not "Deprioritized".
    if (leadStatus === 'deprioritize' && !recentSaleHoldRa) {
      return 'Deprioritized'
    }
    if (leadStatus === 'suppressed') {
      return 'Suppressed'
    }
    if (leadStatus === 'deal_won' || leadStatus === 'deal_lost') {
      return leadStatus === 'deal_won' ? 'Deal won' : 'Deal lost'
    }
    return label ?? (value ? outreachDisplayLabel(value, contactMethod) : 'No recommended action')
  })()
  const displayExplanation = (() => {
    if (llcResearchPrimary) {
      return explanation && recommendedAction.winning_rule === 'research_entity_owner'
        ? explanation
        : 'Owner looks like a company — research Illinois LLC / org records'
    }
    if (leadStatus === 'deprioritize' && !recentSaleHoldRa) {
      return 'Parked from active queues.'
    }
    if (leadStatus === 'suppressed') {
      return 'Removed from active queues.'
    }
    if (leadStatus === 'deal_won' || leadStatus === 'deal_lost') {
      return null
    }
    return explanation
  })()
  // Nurture / terminal park — hide empty system suggestion chrome when appropriate.
  // Entity Research LLC path always keeps the recommended line visible.
  // Recent-sale hold keeps the hold RA label even while status is deprioritize.
  const hideRaLabel = (
    (value === 'nurture' && !llcResearchPrimary)
    || (leadStatus === 'deprioritize' && !recentSaleHoldRa)
    || leadStatus === 'suppressed'
    || leadStatus === 'deal_won'
    || leadStatus === 'deal_lost'
  )
  const skipTracePrimary = value === 'add_contact_info'
  const baseRaButtons = (ACTION_BUTTONS[value] ?? []).filter(
    (btn) => (
      !universalActions.some((u) => u.action === btn.action)
      && (btn.action !== 'move_to_skip_trace' || evaluateMoveToSkipTrace(leadStatus).ok)
    ),
  )
  // Action Center tiles already include universals (+ Research LLC when primary).
  // Do not re-render a second outlined button row in tile mode.
  const raButtons = (() => {
    if (showActionCenterTiles) {
      // Extra RA-only tiles (not already in Action Center / Research LLC).
      // Create Task stays on its dedicated CTA, not as a tile.
      return baseRaButtons.filter(
        (btn) => (
          btn.action !== 'move_to_skip_trace'
          && btn.action !== 'research_llc'
          && btn.action !== 'create_task'
        ),
      )
    }
    if (llcResearchPrimary) {
      const llcBtn: ActionButton = {
        label: researchPending ? 'Researching…' : 'Research LLC',
        action: 'research_llc',
      }
      // Skip Trace stays in Quick actions / universals — do not duplicate.
      return [llcBtn, ...baseRaButtons.filter((b) => b.action !== 'move_to_skip_trace')]
    }
    if (skipTracePrimary) {
      const skipFirst = baseRaButtons.filter((b) => b.action === 'move_to_skip_trace')
      const rest = baseRaButtons.filter((b) => b.action !== 'move_to_skip_trace')
      return [...skipFirst, ...rest]
    }
    return prioritizeButtonsForMethod(baseRaButtons, contactMethod)
  })()
  const prioritizedRaButtons = raButtons
  const showCreateTaskCTA = value === 'create_task' && !hasOpenTasks && typeof onCreateTask === 'function'

  return (
    <Box
      data-testid="recommended-action-panel"
      sx={panelSx}
    >
      {mailHoldAlert}
      {mailAddressAlert}
      {/* DNC badge — shown when lead is do_not_contact */}
      {isDNC && (
        <Chip
          icon={<BlockIcon />}
          label="DO NOT CONTACT"
          color="error"
          size="small"
          sx={{ mb: 1.5 }}
          data-testid="dnc-badge"
        />
      )}

      {renderActionCenterTiles(showActionCenterTiles ? prioritizedRaButtons : [])}

      {/* Action Center: one line = label + explanation (no second sentence row). */}
      {showActionCenterTiles && !hideRaLabel ? (
        <Typography
          sx={{
            fontSize: '0.8rem',
            fontWeight: 600,
            letterSpacing: 0.01,
            color: 'text.secondary',
            mb: 1,
            mt: 0,
            lineHeight: 1.35,
          }}
          data-testid="ra-label"
        >
          <Box component="span" data-testid="ra-recommended-heading" sx={{ fontWeight: 700 }}>
            Recommended next action:{' '}
          </Box>
          {displayLabel}
          {displayExplanation ? (
            <Box component="span" data-testid="ra-explanation" sx={{ fontWeight: 500 }}>
              {' — '}
              {displayExplanation}
            </Box>
          ) : null}
        </Typography>
      ) : null}

      {!showActionCenterTiles && !hideRaLabel && (
        <Typography
          sx={{
            fontSize: '0.8rem',
            fontWeight: 700,
            letterSpacing: 0.02,
            color: 'text.secondary',
            mb: 0.75,
          }}
          data-testid="ra-label"
        >
          {displayLabel}
        </Typography>
      )}

      {!hideRaLabel && showOutreachContact && outreachContact && (
        <OutreachContactInline contact={outreachContact} />
      )}

      {!hideRaLabel && showOutreachContact && !outreachContact && contactMethod && (
        <OutreachContactMissingHint channel={contactMethod as OutreachContact['channel']} />
      )}

      {!showActionCenterTiles && displayExplanation && (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{
            mb: winningRuleLabel ? 1 : 2,
            mt: 0,
            overflowWrap: 'anywhere',
            wordBreak: 'break-word',
          }}
          data-testid="ra-explanation"
        >
          {displayExplanation}
        </Typography>
      )}

      {renderEntityResearch()}

      {!hideRaLabel && winningRuleLabel && (
        <Alert
          severity="info"
          variant="outlined"
          sx={{
            mb: 2,
            py: 0.25,
            maxWidth: '100%',
            '& .MuiAlert-message': {
              fontSize: '0.8rem',
              overflowWrap: 'anywhere',
              wordBreak: 'break-word',
            },
          }}
          data-testid="ra-winning-rule"
        >
          Why this next step: {winningRuleLabel}
        </Alert>
      )}

      {/* Inline error — shown on action failure, does NOT change RA or Timeline.
          Deprioritize failures render inside the dialog while it is open. */}
      {actionError && !deprioritizeOpen && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          onClose={() => setActionError(null)}
          data-testid="ra-action-error"
        >
          {actionError}
        </Alert>
      )}

      {/* create_task CTA — shown when RA is create_task and no open tasks */}
      {showCreateTaskCTA && (
        <Box sx={{ mb: 2 }} data-testid="create-task-cta">
          <Button
            variant="contained"
            color="primary"
            startIcon={<AddTaskIcon />}
            onClick={onCreateTask}
            data-testid="create-task-cta-button"
          >
            Create Task
          </Button>
        </Box>
      )}

      {/* Universal quick actions — always available unless DNC blocks outreach */}
      {renderUniversalActions(prioritizedRaButtons)}

      {/* RA-specific action buttons — only when Action Center tiles are off */}
      {!showActionCenterTiles && prioritizedRaButtons.length > 0 && (
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          flexWrap="wrap"
          useFlexGap
          sx={actionStackSx}
        >
          {prioritizedRaButtons.map((btn) => renderActionButton(
            btn,
            'ra-action-btn',
            false,
          ))}
        </Stack>
      )}

      {deprioritizeDialog}
    </Box>
  )
}

export default RecommendedActionPanel
