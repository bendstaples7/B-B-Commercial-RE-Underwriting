/**
 * Needs Review clarity — chip popover for generic reasons; always-visible
 * duplicate callout with this-vs-other comparison + merge.
 */
import { useState, type MouseEvent } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Link,
  Popover,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import MergeTypeIcon from '@mui/icons-material/MergeType'
import CloseIcon from '@mui/icons-material/Close'
import CheckIcon from '@mui/icons-material/Check'
import type { CommandCenterPayload, DuplicateClusterMember } from '@/types'
import { commandCenterService } from '@/services/api'
import {
  formatNeedsReviewReason,
  isDuplicateClusterReason,
  POSSIBLE_DUPLICATE_RECORDS_LABEL,
} from '@/utils/needsReviewReason'
import { formatDate } from '@/utils/formatters'

export interface NeedsReviewClarityContentProps {
  leadId: number
  commandCenterData: CommandCenterPayload
  onResolved: (result: {
    kind: 'merged' | 'dismissed' | 'cleared'
    winnerId?: number
    loserId?: number
  }) => void | Promise<void>
  /** Called after a successful resolve so the popover can close. */
  onClose?: () => void
  /** Opens the pick-who-stays merge dialog (preferred over silent keep-suggested). */
  onOpenMerge?: () => void
  variant?: 'popover' | 'callout'
}

function memberFlags(member: DuplicateClusterMember): string {
  const bits: string[] = []
  if (member.hubspot_confirmed) bits.push('HubSpot')
  if (member.has_phone) bits.push('phone')
  if (member.has_email) bits.push('email')
  return bits.length ? bits.join(' · ') : '—'
}

function ComparisonField({
  label,
  current,
  other,
}: {
  label: string
  current: string
  other: string
}) {
  const differ = current !== other
  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: '88px 1fr 1fr',
        gap: 1,
        py: 0.5,
        borderBottom: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Typography variant="caption" color="text.secondary" sx={{ pt: 0.15 }}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={differ ? 700 : 400}>
        {current}
      </Typography>
      <Typography variant="body2" fontWeight={differ ? 700 : 400}>
        {other}
      </Typography>
    </Box>
  )
}

function DuplicatePairComparison({
  leadId,
  current,
  other,
}: {
  leadId: number
  current: DuplicateClusterMember
  other: DuplicateClusterMember
}) {
  return (
    <Box sx={{ mt: 1 }} data-testid="needs-review-cluster-comparison">
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: '88px 1fr 1fr',
          gap: 1,
          pb: 0.5,
        }}
      >
        <Typography variant="caption" color="text.secondary">
          Field
        </Typography>
        <Typography variant="caption" fontWeight={700}>
          This lead #{leadId}
          {current.is_suggested_winner ? ' · suggested keep' : ''}
        </Typography>
        <Typography variant="caption" fontWeight={700} data-testid={`needs-review-cluster-row-${other.id}`}>
          <Link
            component={RouterLink}
            to={`/leads/${other.id}?queue=needs-review`}
            underline="hover"
            variant="caption"
            fontWeight={700}
          >
            #{other.id}
          </Link>
          {other.is_suggested_winner ? ' · suggested keep' : ''}
        </Typography>
      </Box>
      <ComparisonField
        label="Owner"
        current={current.owner_display_name || '—'}
        other={other.owner_display_name || '—'}
      />
      <ComparisonField
        label="Street"
        current={current.property_street || '—'}
        other={other.property_street || '—'}
      />
      <ComparisonField
        label="PIN"
        current={current.county_assessor_pin || '—'}
        other={other.county_assessor_pin || '—'}
      />
      <ComparisonField
        label="Status"
        current={current.lead_status || '—'}
        other={other.lead_status || '—'}
      />
      <ComparisonField
        label="Signals"
        current={memberFlags(current)}
        other={memberFlags(other)}
      />
    </Box>
  )
}

export function NeedsReviewClarityContent({
  leadId,
  commandCenterData,
  onResolved,
  onClose,
  onOpenMerge,
  variant = 'popover',
}: NeedsReviewClarityContentProps) {
  const [busy, setBusy] = useState<'merge' | 'dismiss' | 'clear' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reason = commandCenterData.review_reason ?? null
  const cluster = commandCenterData.duplicate_cluster ?? null
  const isDuplicate = isDuplicateClusterReason(reason)
  const reasonLabel = formatNeedsReviewReason({
    id: leadId,
    review_reason: reason,
    suggested_winner_id: cluster?.suggested_winner_id,
    duplicate_cluster_ids: cluster?.cluster_ids,
    duplicate_confidence: cluster?.confidence,
  })
  const winnerId = cluster?.suggested_winner_id ?? null
  const members = cluster?.members ?? []
  const siblings = members.filter((member) => member.id !== leadId)
  const mergeLoserId = winnerId != null && winnerId !== leadId ? leadId : (siblings[0]?.id ?? null)
  const mergeWinnerId = winnerId != null && winnerId !== leadId ? winnerId : leadId
  const canMerge =
    isDuplicate
    && mergeLoserId != null
    && mergeWinnerId != null
    && mergeLoserId !== mergeWinnerId
  const pairCurrent = members.find((member) => member.id === leadId) ?? members[0]
  const pairOther = members.length === 2
    ? members.find((member) => member.id !== pairCurrent?.id) ?? null
    : null
  const triggeredAt = commandCenterData.review_triggered_at
    ? formatDate(commandCenterData.review_triggered_at)
    : null
  const keepLabel = winnerId != null && winnerId !== leadId
    ? `Keep suggested (#${winnerId})`
    : mergeLoserId != null
      ? `Merge #${mergeLoserId} into this`
      : 'Merge'

  const run = async (kind: 'merge' | 'dismiss' | 'clear', fn: () => Promise<void>) => {
    setBusy(kind)
    setError(null)
    try {
      await fn()
      setBusy(null)
      onClose?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
      setBusy(null)
    }
  }

  return (
    <Box
      sx={{ p: variant === 'callout' ? 0 : 2, width: variant === 'callout' ? '100%' : 440, maxWidth: '92vw' }}
      data-testid="needs-review-clarity-panel"
    >
      <Typography variant="subtitle2" fontWeight={700} data-testid="needs-review-clarity-reason">
        {isDuplicate ? POSSIBLE_DUPLICATE_RECORDS_LABEL : reasonLabel}
      </Typography>
      {isDuplicate ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          Same owner + same building may be listed more than once. Confirm which record to keep.
          {winnerId != null ? ` Suggested keep: #${winnerId}.` : ''}
        </Typography>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {reasonLabel}
        </Typography>
      )}
      {triggeredAt && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
          Triggered {triggeredAt}
        </Typography>
      )}

      {isDuplicate && pairCurrent && pairOther ? (
        <DuplicatePairComparison leadId={leadId} current={pairCurrent} other={pairOther} />
      ) : null}

      {isDuplicate && members.length > 0 && !pairOther && (
        <Box sx={{ overflowX: 'auto', mt: 1 }} data-testid="needs-review-cluster-table">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Lead</TableCell>
                <TableCell>Owner</TableCell>
                <TableCell>Street</TableCell>
                <TableCell>PIN</TableCell>
                <TableCell>Signals</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {members.map((member) => {
                const isCurrent = member.id === leadId
                return (
                  <TableRow
                    key={member.id}
                    selected={member.is_suggested_winner}
                    data-testid={`needs-review-cluster-row-${member.id}`}
                  >
                    <TableCell>
                      {isCurrent ? (
                        <Typography variant="body2" fontWeight={600}>
                          #{member.id} (this lead)
                        </Typography>
                      ) : (
                        <Link
                          component={RouterLink}
                          to={`/leads/${member.id}?queue=needs-review`}
                          underline="hover"
                          variant="body2"
                        >
                          #{member.id}
                        </Link>
                      )}
                      {member.is_suggested_winner && (
                        <Chip size="small" label="Suggested keep" sx={{ ml: 0.75 }} />
                      )}
                    </TableCell>
                    <TableCell>{member.owner_display_name || '—'}</TableCell>
                    <TableCell>{member.property_street || '—'}</TableCell>
                    <TableCell>{member.county_assessor_pin || '—'}</TableCell>
                    <TableCell>{memberFlags(member)}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Box>
      )}

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1.5 }}>
        {onOpenMerge && isDuplicate ? (
          <Button
            size="small"
            variant="contained"
            startIcon={<MergeTypeIcon />}
            disabled={busy != null}
            data-testid="needs-review-open-merge"
            onClick={() => {
              onOpenMerge()
              onClose?.()
            }}
            sx={{ cursor: 'pointer' }}
          >
            Merge
          </Button>
        ) : null}
        {canMerge && mergeLoserId != null && mergeWinnerId != null && (
          <Button
            size="small"
            variant={onOpenMerge ? 'outlined' : 'contained'}
            startIcon={busy === 'merge' ? <CircularProgress size={14} /> : <MergeTypeIcon />}
            disabled={busy != null}
            data-testid="needs-review-merge-into-winner"
            onClick={() => {
              const ok = window.confirm(
                `Merge lead #${mergeLoserId} into #${mergeWinnerId}? This soft-merges the duplicate and cannot be undone from this screen.`,
              )
              if (!ok) return
              void run('merge', async () => {
                await commandCenterService.mergeInto(mergeLoserId, mergeWinnerId)
                await onResolved({ kind: 'merged', winnerId: mergeWinnerId, loserId: mergeLoserId })
              })
            }}
            sx={{ cursor: 'pointer' }}
          >
            {keepLabel}
          </Button>
        )}
        {isDuplicate ? (
          <Button
            size="small"
            variant="outlined"
            startIcon={busy === 'dismiss' ? <CircularProgress size={14} /> : <CloseIcon />}
            disabled={busy != null}
            data-testid="needs-review-dismiss-duplicate"
            onClick={() => {
              void run('dismiss', async () => {
                await commandCenterService.dismissDuplicateReview(leadId)
                await onResolved({ kind: 'dismissed' })
              })
            }}
            sx={{ cursor: 'pointer' }}
          >
            Not a duplicate
          </Button>
        ) : (
          <Button
            size="small"
            variant="outlined"
            startIcon={busy === 'clear' ? <CircularProgress size={14} /> : <CheckIcon />}
            disabled={busy != null}
            data-testid="needs-review-mark-reviewed"
            onClick={() => {
              void run('clear', async () => {
                await commandCenterService.clearReview(leadId)
                await onResolved({ kind: 'cleared' })
              })
            }}
            sx={{ cursor: 'pointer' }}
          >
            Mark reviewed
          </Button>
        )}
        <Button
          size="small"
          component={RouterLink}
          to="/queues/needs-review"
          data-testid="needs-review-clarity-queue-link"
          sx={{ cursor: 'pointer' }}
        >
          Open queue
        </Button>
      </Box>

      {error && (
        <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
          {error}
        </Typography>
      )}
    </Box>
  )
}

export interface NeedsReviewChipPopoverProps {
  leadId: number
  commandCenterData: CommandCenterPayload
  /** Chip / inline label (usually "Needs Review"). */
  label?: string
  onResolved: NeedsReviewClarityContentProps['onResolved']
  /** `inline` matches the Current queues text list in the score box. */
  variant?: 'chip' | 'inline'
  /** Bold when this is the queue the user opened the lead from. */
  viewingFrom?: boolean
  onOpenMerge?: () => void
}

/** Warning chip (or inline name) that opens the Needs Review clarity popover. */
export function NeedsReviewChipPopover({
  leadId,
  commandCenterData,
  label = 'Needs Review',
  onResolved,
  variant = 'chip',
  viewingFrom = false,
  onOpenMerge,
}: NeedsReviewChipPopoverProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const open = Boolean(anchor)
  const reviewActive = Boolean(
    commandCenterData.review_required || commandCenterData.review_reason,
  )
  if (!reviewActive) return null

  const isDuplicate = isDuplicateClusterReason(commandCenterData.review_reason)
  const handleClick = (e: MouseEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    if (isDuplicate) {
      document.getElementById('needs-review-duplicate-callout')?.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
      })
      return
    }
    setAnchor(e.currentTarget)
  }

  const trigger =
    variant === 'inline' ? (
      <Link
        component="button"
        type="button"
        underline="hover"
        onClick={handleClick}
        data-testid="work-queue-strip-needs-review"
        data-viewing-from={viewingFrom ? 'true' : undefined}
        aria-haspopup={isDuplicate ? undefined : 'dialog'}
        aria-expanded={isDuplicate ? undefined : open}
        sx={{
          fontFamily: 'inherit',
          fontSize: 'inherit',
          lineHeight: 'inherit',
          fontWeight: viewingFrom ? 700 : 400,
          color: viewingFrom ? 'text.primary' : 'text.secondary',
          cursor: 'pointer',
          verticalAlign: 'baseline',
        }}
      >
        {viewingFrom ? <strong>{label}</strong> : label}
      </Link>
    ) : (
      <Chip
        size="small"
        color="warning"
        label={label}
        clickable
        onClick={handleClick}
        data-testid="work-queue-strip-needs-review"
        aria-haspopup={isDuplicate ? undefined : 'dialog'}
        aria-expanded={isDuplicate ? undefined : open}
        sx={{ fontWeight: 700, cursor: 'pointer' }}
      />
    )

  return (
    <>
      {trigger}
      {isDuplicate ? null : (
        <Popover
          open={open}
          anchorEl={anchor}
          onClose={() => setAnchor(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
          transformOrigin={{ vertical: 'top', horizontal: 'left' }}
          PaperProps={{ 'data-testid': 'needs-review-clarity-popover' } as object}
        >
          <NeedsReviewClarityContent
            leadId={leadId}
            commandCenterData={commandCenterData}
            onResolved={onResolved}
            onClose={() => setAnchor(null)}
            onOpenMerge={onOpenMerge}
          />
        </Popover>
      )}
    </>
  )
}

export function DuplicateReviewCallout({
  leadId,
  commandCenterData,
  onResolved,
  onOpenMerge,
}: NeedsReviewClarityContentProps) {
  if (!isDuplicateClusterReason(commandCenterData.review_reason)) return null
  return (
    <Alert
      id="needs-review-duplicate-callout"
      severity="warning"
      data-testid="needs-review-duplicate-callout"
      sx={{
        cursor: 'auto',
        alignItems: 'flex-start',
        '& .MuiAlert-message': { width: '100%', cursor: 'auto' },
      }}
    >
      <NeedsReviewClarityContent
        leadId={leadId}
        commandCenterData={commandCenterData}
        onResolved={onResolved}
        onOpenMerge={onOpenMerge}
        variant="callout"
      />
    </Alert>
  )
}

/** @deprecated Prefer NeedsReviewChipPopover — kept for tests that import the old name. */
export function NeedsReviewClarityPanel(props: NeedsReviewClarityContentProps) {
  return <NeedsReviewClarityContent {...props} />
}

export default NeedsReviewChipPopover
