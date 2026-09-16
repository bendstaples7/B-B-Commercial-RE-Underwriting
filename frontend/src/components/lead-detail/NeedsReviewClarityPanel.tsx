/**
 * Needs Review callout on Command Center: reason + duplicate cluster actions.
 *
 * Membership chips stay in WorkQueueMembershipStrip; this panel explains *why*
 * the lead is in Needs Review and offers Merge / Dismiss / Mark reviewed.
 */
import { useState } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Link,
  Paper,
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
} from '@/utils/needsReviewReason'
import { ccCardSx } from '@/components/lead-detail/commandCenterChrome'

export interface NeedsReviewClarityPanelProps {
  leadId: number
  commandCenterData: CommandCenterPayload
  onResolved: (result: {
    kind: 'merged' | 'dismissed' | 'cleared'
    winnerId?: number
    loserId?: number
  }) => void | Promise<void>
}

function memberFlags(member: DuplicateClusterMember): string {
  const bits: string[] = []
  if (member.hubspot_confirmed) bits.push('HubSpot')
  if (member.has_phone) bits.push('phone')
  if (member.has_email) bits.push('email')
  return bits.length ? bits.join(' · ') : '—'
}

export function NeedsReviewClarityPanel({
  leadId,
  commandCenterData,
  onResolved,
}: NeedsReviewClarityPanelProps) {
  const [busy, setBusy] = useState<'merge' | 'dismiss' | 'clear' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reviewRequired = Boolean(commandCenterData.review_required)
  const reason = commandCenterData.review_reason ?? null
  if (!reviewRequired && !reason) return null

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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
      setBusy(null)
    }
  }

  return (
    <Paper
      sx={{ ...ccCardSx, px: 1.5, py: 1.25 }}
      data-testid="needs-review-clarity-panel"
    >
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 1,
          mb: members.length ? 1 : 0,
        }}
      >
        <Chip
          size="small"
          color="warning"
          label="Needs Review"
          component={RouterLink}
          to="/queues/needs-review"
          clickable
          data-testid="needs-review-clarity-chip"
        />
        <Typography variant="body2" fontWeight={600} data-testid="needs-review-clarity-reason">
          {reasonLabel}
        </Typography>
        {triggeredAt && (
          <Typography variant="caption" color="text.secondary">
            Triggered {triggeredAt}
          </Typography>
        )}
        <Box sx={{ flex: 1 }} />
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
            Merge into #{winnerId}
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
            Dismiss duplicate
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
      </Box>

      {isDuplicate && members.length > 0 && (
        <Box sx={{ overflowX: 'auto' }} data-testid="needs-review-cluster-table">
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
                        <Chip size="small" label="Suggested winner" sx={{ ml: 0.75 }} />
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

      {error && (
        <Typography variant="caption" color="error" sx={{ mt: 1, display: 'block' }}>
          {error}
        </Typography>
      )}
    </Paper>
  )
}

export default NeedsReviewClarityPanel
