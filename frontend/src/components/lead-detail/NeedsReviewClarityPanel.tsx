/**
 * Needs Review clarity — Option 1: popover on the Needs Review membership chip.
 *
 * Explains why the lead is in Needs Review and offers Keep suggested /
 * Not a duplicate / Mark reviewed. Not a sticky header banner.
 */
import { useState, type MouseEvent } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
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
}

function memberFlags(member: DuplicateClusterMember): string {
  const bits: string[] = []
  if (member.hubspot_confirmed) bits.push('HubSpot')
  if (member.has_phone) bits.push('phone')
  if (member.has_email) bits.push('email')
  return bits.length ? bits.join(' · ') : '—'
}

export function NeedsReviewClarityContent({
  leadId,
  commandCenterData,
  onResolved,
  onClose,
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
  const canMerge =
    isDuplicate
    && winnerId != null
    && winnerId !== leadId
    && String(cluster?.confidence || '').toLowerCase() !== 'ambiguous'
  const members = cluster?.members ?? []
  const triggeredAt = commandCenterData.review_triggered_at
    ? new Date(commandCenterData.review_triggered_at).toLocaleDateString()
    : null

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
    <Box sx={{ p: 2, width: 400, maxWidth: '92vw' }} data-testid="needs-review-clarity-panel">
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

      {isDuplicate && members.length > 0 && (
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
        {canMerge && winnerId != null && (
          <Button
            size="small"
            variant="contained"
            startIcon={busy === 'merge' ? <CircularProgress size={14} /> : <MergeTypeIcon />}
            disabled={busy != null}
            data-testid="needs-review-merge-into-winner"
            onClick={() => {
              const ok = window.confirm(
                `Merge lead #${leadId} into #${winnerId}? This soft-merges the duplicate and cannot be undone from this screen.`,
              )
              if (!ok) return
              void run('merge', async () => {
                await commandCenterService.mergeInto(leadId, winnerId)
                await onResolved({ kind: 'merged', winnerId, loserId: leadId })
              })
            }}
          >
            Keep suggested (#{winnerId})
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
          >
            Mark reviewed
          </Button>
        )}
        <Button
          size="small"
          component={RouterLink}
          to="/queues/needs-review"
          data-testid="needs-review-clarity-queue-link"
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
}

/** Warning chip (or inline name) that opens the Needs Review clarity popover. */
export function NeedsReviewChipPopover({
  leadId,
  commandCenterData,
  label = 'Needs Review',
  onResolved,
  variant = 'chip',
  viewingFrom = false,
}: NeedsReviewChipPopoverProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const open = Boolean(anchor)
  const reviewActive = Boolean(
    commandCenterData.review_required || commandCenterData.review_reason,
  )
  if (!reviewActive) return null

  const openPopover = (e: MouseEvent<HTMLElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setAnchor(e.currentTarget)
  }

  const trigger =
    variant === 'inline' ? (
      <Link
        component="button"
        type="button"
        underline="hover"
        onClick={openPopover}
        data-testid="work-queue-strip-needs-review"
        data-viewing-from={viewingFrom ? 'true' : undefined}
        aria-haspopup="dialog"
        aria-expanded={open}
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
        onClick={openPopover}
        data-testid="work-queue-strip-needs-review"
        aria-haspopup="dialog"
        aria-expanded={open}
        sx={{ fontWeight: 700, cursor: 'pointer' }}
      />
    )

  return (
    <>
      {trigger}
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
        />
      </Popover>
    </>
  )
}

/** @deprecated Prefer NeedsReviewChipPopover — kept for tests that import the old name. */
export function NeedsReviewClarityPanel(props: NeedsReviewClarityContentProps) {
  return <NeedsReviewClarityContent {...props} />
}

export default NeedsReviewChipPopover
