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
  Stack,
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
import type { RecommendedActionMeta, LeadStatus, LeadTask, CRMRecommendedAction, OutreachContact } from '@/types'
import { outreachDisplayLabel } from '@/constants/scoringRecommendedActions'
import { OutreachContactInline, OutreachContactMissingHint } from '@/components/OutreachContactCallout'
import { formatDateOnly } from '@/utils/helpers'
import {
  type QuickActionId,
  evaluateMoveToSkipTrace,
  unavailableReasonForQuickAction,
} from '@/utils/actionEligibility'

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
  create_task: <AddTaskIcon fontSize="small" />,
  run_analysis: <AnalyticsOutlinedIcon fontSize="small" />,
  research_property: <TravelExploreOutlinedIcon fontSize="small" />,
  add_contact_info: <ContactMailOutlinedIcon fontSize="small" />,
  search_property: <TravelExploreOutlinedIcon fontSize="small" />,
  research_pin: <PinDropOutlinedIcon fontSize="small" />,
  adjust_for_recent_sale: <EventAvailableOutlinedIcon fontSize="small" />,
  suppress: <DoNotDisturbOnOutlinedIcon fontSize="small" />,
  do_not_contact: <BlockIcon fontSize="small" />,
}

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
  suppress: [
    { label: 'Suppress Lead', action: 'suppress' },
  ],
  do_not_contact: [
    { label: 'Mark DNC', action: 'do_not_contact' },
  ],
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
  /** When true, show outreach contact inline under the action label */
  showOutreachContact?: boolean
  /** Drop outer border when nested inside a shared action card. */
  embedded?: boolean
  onAction: (action: string) => Promise<void>
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
  showOutreachContact = false,
  embedded = false,
  onAction,
  onCreateTask,
}: RecommendedActionPanelProps) {
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const isDNC = leadStatus === 'do_not_contact'
  const isInMailBatch = mailQueueStatus === 'queued'
  const universalActions = UNIVERSAL_ACTIONS
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
      Recent sale detected. Held in Skip Trace
      {mailEligibleDate
        ? ` until ${formatDateOnly(mailEligibleDate)}.`
        : ' until the two-year hold ends.'}
      {' '}It will move to Awaiting Skip Trace when the hold expires.
    </Alert>
  ) : null

  const handleAction = async (action: string) => {
    setActionError(null)
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

  const renderActionButton = (btn: ActionButton, testIdPrefix = 'ra-action-btn') => {
    const unavailableReason = unavailableReasonFor(btn)
    const isDisabled = unavailableReason != null
    const isLoading = pendingAction === btn.action
    const title =
      unavailableReason
      ?? btn.title
      ?? (btn.action === 'park'
        ? 'Hide this lead from active queues until a future re-activation date'
        : undefined)

    return (
      <Button
        key={btn.action}
        variant="outlined"
        size="small"
        disabled={isDisabled || pendingAction !== null}
        onClick={() => handleAction(btn.action)}
        title={title}
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

  const renderUniversalActions = (raButtons: ActionButton[] = []) => (
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
          return renderActionButton(btn, 'ra-universal-btn')
        })}
      </Stack>
    </Box>
  )

  // No RA assigned — still show universal quick actions
  if (!recommendedAction || !recommendedAction.value) {
    return (
      <Box
        data-testid="recommended-action-panel"
        sx={panelSx}
      >
        {mailHoldAlert}
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
        {openTasks.length > 0 ? (
          <>
            <Typography variant="body2" fontWeight={700}>
              Follow up on next task
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {openTasks[0].title}
            </Typography>
          </>
        ) : (
          <Typography variant="body2" color="text.secondary">
            No recommended action at this time.
          </Typography>
        )}
        {actionError && (
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
      </Box>
    )
  }

  const { value, label, explanation, recommended_contact_method: contactMethod, outreach_contact: outreachContact, winning_rule_label: winningRuleLabel } = recommendedAction
  const hasOpenTasks = openTasks.length > 0
  const showTaskFallback = value === 'nurture' && hasOpenTasks
  const displayLabel = showTaskFallback
    ? 'Follow up on next task'
    : label ?? (value ? outreachDisplayLabel(value, contactMethod) : 'No recommended action')
  const hideRaHeading = value === 'nurture' && !showTaskFallback
  const raButtons = (ACTION_BUTTONS[value] ?? []).filter(
    (btn) => (
      !universalActions.some((u) => u.action === btn.action)
      && (btn.action !== 'move_to_skip_trace' || evaluateMoveToSkipTrace(leadStatus).ok)
    ),
  )
  const prioritizedRaButtons = prioritizeButtonsForMethod(raButtons, contactMethod)
  const showCreateTaskCTA = value === 'create_task' && !hasOpenTasks && typeof onCreateTask === 'function'

  return (
    <Box
      data-testid="recommended-action-panel"
      sx={panelSx}
    >
      {mailHoldAlert}
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

      {/* RA label — hidden for nurture (no system suggestion, just quick actions) */}
      {!hideRaHeading && (
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

      {showTaskFallback && (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ mb: 2 }}
          data-testid="ra-next-task-title"
        >
          {openTasks[0].title}
        </Typography>
      )}

      {!hideRaHeading && showOutreachContact && outreachContact && (
        <OutreachContactInline contact={outreachContact} />
      )}

      {!hideRaHeading && showOutreachContact && !outreachContact && contactMethod && (
        <OutreachContactMissingHint channel={contactMethod as OutreachContact['channel']} />
      )}

      {!hideRaHeading && !showTaskFallback && explanation && (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ mb: winningRuleLabel ? 1 : 2, overflowWrap: 'anywhere', wordBreak: 'break-word' }}
          data-testid="ra-explanation"
        >
          {explanation}
        </Typography>
      )}

      {!hideRaHeading && !showTaskFallback && winningRuleLabel && (
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

      {/* Inline error — shown on action failure, does NOT change RA or Timeline */}
      {actionError && (
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

      {/* RA-specific action buttons */}
      {prioritizedRaButtons.length > 0 && (
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1}
          flexWrap="wrap"
          useFlexGap
          sx={actionStackSx}
        >
          {prioritizedRaButtons.map((btn) => renderActionButton(btn))}
        </Stack>
      )}
    </Box>
  )
}

export default RecommendedActionPanel
