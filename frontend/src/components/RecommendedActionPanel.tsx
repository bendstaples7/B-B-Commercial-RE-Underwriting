/**
 * RecommendedActionPanel — displays the current Recommended Action for a lead,
 * including its label, explanation, and 1–5 action buttons.
 *
 * Requirements: 7.2, 7.3, 7.4, 4.3
 */
import { useState } from 'react'
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
import type { RecommendedActionMeta, LeadStatus, LeadTask, CRMRecommendedAction } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function humanizeValue(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

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

const UNIVERSAL_ACTIONS: ActionButton[] = [
  { label: 'Log Call', action: 'log_call', isOutreach: true },
  { label: 'Log Note', action: 'log_note' },
  { label: 'Log Email', action: 'log_email', isOutreach: true },
]

const ACTION_BUTTONS: Record<CRMRecommendedAction, ActionButton[]> = {
  review_now: [
    { label: 'Research Property', action: 'research_property' },
    { label: 'Log Note', action: 'log_note' },
    { label: 'Create Task', action: 'create_task' },
  ],
  mail_ready: [
    { label: 'Add to Mail Batch', action: 'add_to_mail_batch', isOutreach: true },
    { label: 'Log Note', action: 'log_note' },
  ],
  call_ready: [
    { label: 'Log Call', action: 'log_call', isOutreach: true },
    { label: 'Create Task', action: 'create_task' },
  ],
  valuation_needed: [
    { label: 'Run Analysis', action: 'run_analysis' },
    { label: 'Research Property', action: 'research_property' },
  ],
  needs_manual_review: [
    { label: 'Research Property', action: 'research_property' },
    { label: 'Log Note', action: 'log_note' },
    { label: 'Create Task', action: 'create_task' },
  ],
  enrich_data: [
    { label: 'Run Skip Trace', action: 'skip_trace' },
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
  follow_up_now: [
    { label: 'Log Call', action: 'log_call', isOutreach: true },
    { label: 'Log Note', action: 'log_note', isOutreach: true },
    { label: 'Create Task', action: 'create_task' },
  ],
  ready_for_outreach: [
    { label: 'Log Call', action: 'log_call', isOutreach: true },
    { label: 'Add to Mail Batch', action: 'add_to_mail_batch', isOutreach: true },
    { label: 'Log Note', action: 'log_note', isOutreach: true },
    { label: 'Create Task', action: 'create_task' },
  ],
  add_contact_info: [
    { label: 'Add Contact Info', action: 'add_contact_info' },
    { label: 'Run Skip Trace', action: 'skip_trace' },
  ],
  create_task: [
    { label: 'Create Task', action: 'create_task' },
  ],
  nurture: [],
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
  onAction,
  onCreateTask,
}: RecommendedActionPanelProps) {
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<string | null>(null)

  const isDNC = leadStatus === 'do_not_contact'

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

  const renderActionButton = (btn: ActionButton, testIdPrefix = 'ra-action-btn') => {
    const isDisabled = isDNC && btn.isOutreach === true
    const isLoading = pendingAction === btn.action
    const title = btn.title ?? (btn.action === 'park'
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
          ) : undefined
        }
        data-testid={`${testIdPrefix}-${btn.action}`}
        aria-label={btn.label}
      >
        {isLoading ? 'Working…' : btn.label}
      </Button>
    )
  }

  const renderUniversalActions = (raButtons: ActionButton[] = []) => (
    <Box sx={{ mb: raButtons.length > 0 ? 2 : 0, mt: 2 }}>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
        Quick actions
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap data-testid="ra-universal-actions">
        {UNIVERSAL_ACTIONS.map((btn) => renderActionButton(btn, 'ra-universal-btn'))}
      </Stack>
    </Box>
  )

  // No RA assigned — still show universal quick actions
  if (!recommendedAction || !recommendedAction.value) {
    return (
      <Box
        data-testid="recommended-action-panel"
        sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}
      >
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
        <Typography variant="body2" color="text.secondary">
          No recommended action at this time.
        </Typography>
        {renderUniversalActions()}
      </Box>
    )
  }

  const { value, label, explanation } = recommendedAction
  const displayLabel = label ?? humanizeValue(value)
  const hideRaHeading = value === 'nurture'
  const raButtons = (ACTION_BUTTONS[value] ?? []).filter(
    (btn) => !UNIVERSAL_ACTIONS.some((u) => u.action === btn.action),
  )
  const hasOpenTasks = openTasks.length > 0
  const showCreateTaskCTA = value === 'create_task' && !hasOpenTasks && typeof onCreateTask === 'function'

  return (
    <Box
      data-testid="recommended-action-panel"
      sx={{ p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}
    >
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
          variant="subtitle1"
          fontWeight="bold"
          gutterBottom
          data-testid="ra-label"
        >
          {displayLabel}
        </Typography>
      )}

      {!hideRaHeading && explanation && (
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ mb: 2 }}
          data-testid="ra-explanation"
        >
          {explanation}
        </Typography>
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
      {renderUniversalActions(raButtons)}

      {/* RA-specific action buttons */}
      {raButtons.length > 0 && (
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {raButtons.map((btn) => renderActionButton(btn))}
        </Stack>
      )}
    </Box>
  )
}

export default RecommendedActionPanel
