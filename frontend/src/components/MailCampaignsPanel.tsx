import React, { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatLastMailedDate } from '@/utils/formatLastMailedDate'
import { mailCampaignStatusColor } from '@/utils/mailCampaignStatusColor'
import openLetterService, {
  type CreativeRollupRow,
  type MailCampaign,
} from '@/services/openLetterApi'

function formatPct(rate: number | null | undefined): string {
  if (rate == null) return '—'
  return `${(rate * 100).toFixed(1)}%`
}

function yn(value: boolean | null | undefined): string {
  if (value == null) return '—'
  return value ? 'Yes' : 'No'
}

function CampaignRow({
  campaign,
  onCancel,
  onRelease,
  cancelling,
}: {
  campaign: MailCampaign
  onCancel: (id: number) => void
  onRelease: (id: number) => void
  cancelling: boolean
}) {
  const delivered = campaign.delivery_stats?.Delivered
  const mailed = campaign.delivery_stats?.Mailed
  const deliveryRate =
    delivered != null && mailed ? delivered / Math.max(mailed, 1) : null
  const creative = campaign.creative
  const canCancel = ['pending', 'failed', 'submitted', 'processing'].includes(
    campaign.status,
  )
  const canRelease = campaign.status === 'cancelled'

  return (
    <TableRow>
      <TableCell>{formatLastMailedDate(campaign.submitted_at || campaign.created_at)}</TableCell>
      <TableCell>{creative?.sender_display_name || '—'}</TableCell>
      <TableCell>{creative?.envelope_color || '—'}</TableCell>
      <TableCell>
        {[creative?.font_name, creative?.font_color].filter(Boolean).join(' / ') || '—'}
      </TableCell>
      <TableCell>{yn(creative?.include_email)}</TableCell>
      <TableCell>{yn(creative?.include_website)}</TableCell>
      <TableCell>{campaign.template_name || campaign.template_id || '—'}</TableCell>
      <TableCell>{campaign.lead_count}</TableCell>
      <TableCell>
        {campaign.cost != null ? `$${campaign.cost.toFixed(2)}` : '—'}
      </TableCell>
      <TableCell>
        <Chip label={campaign.status} size="small" color={mailCampaignStatusColor(campaign.status)} />
      </TableCell>
      <TableCell>{formatPct(campaign.scan_rate)}</TableCell>
      <TableCell>{formatPct(deliveryRate)}</TableCell>
      <TableCell>{formatPct(campaign.response_rate)}</TableCell>
      <TableCell>
        {canCancel ? (
          <Button
            size="small"
            color="warning"
            disabled={cancelling}
            onClick={() => onCancel(campaign.id)}
          >
            Cancel
          </Button>
        ) : canRelease ? (
          <Button
            size="small"
            disabled={cancelling}
            onClick={() => onRelease(campaign.id)}
          >
            Release to queue
          </Button>
        ) : (
          '—'
        )}
      </TableCell>
    </TableRow>
  )
}

function CreativeCompareTable({ rows }: { rows: CreativeRollupRow[] }) {
  if (!rows.length) return null
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle1" gutterBottom>
        Compare creatives
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Scan rate uses Open Letter QR scans as an open proxy. Response rate counts
        calls attributed to that mail campaign.
      </Typography>
      <TableContainer component={Paper} sx={{ overflowX: 'auto', maxWidth: '100%' }}>
        <Table size="small" sx={{ minWidth: 720 }}>
          <TableHead>
            <TableRow>
              <TableCell>Sender</TableCell>
              <TableCell>Envelope</TableCell>
              <TableCell>Font</TableCell>
              <TableCell>Email?</TableCell>
              <TableCell>Website?</TableCell>
              <TableCell>Campaigns</TableCell>
              <TableCell>Pieces</TableCell>
              <TableCell>Scan rate</TableCell>
              <TableCell>Response</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={[
                  row.sender_display_name,
                  row.envelope_color,
                  row.font_name,
                  row.font_color,
                  String(row.include_email),
                  String(row.include_website),
                ].join('|')}
              >
                <TableCell>{row.sender_display_name}</TableCell>
                <TableCell>{row.envelope_color}</TableCell>
                <TableCell>
                  {[row.font_name, row.font_color].filter((v) => v && v !== '—').join(' / ') || '—'}
                </TableCell>
                <TableCell>{yn(row.include_email)}</TableCell>
                <TableCell>{yn(row.include_website)}</TableCell>
                <TableCell>{row.campaign_count}</TableCell>
                <TableCell>{row.lead_count}</TableCell>
                <TableCell>{formatPct(row.scan_rate)}</TableCell>
                <TableCell>{formatPct(row.response_rate)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}

export const MailCampaignsPanel: React.FC<{ embedded?: boolean }> = ({ embedded = false }) => {
  const queryClient = useQueryClient()
  const [feedbackNote, setFeedbackNote] = useState<string | null>(null)
  const [cancelWarning, setCancelWarning] = useState<string | null>(null)
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['mail-campaigns'],
    queryFn: () => openLetterService.listCampaigns(),
  })

  const cancelMutation = useMutation({
    mutationFn: ({ id, release_queue }: { id: number; release_queue?: boolean }) =>
      openLetterService.cancelCampaign(id, { release_queue }),
    onSuccess: (result) => {
      if (result.queue_held) {
        setFeedbackNote(`Campaign #${result.id} cancelled (queue held until Connect cancel).`)
      } else {
        setFeedbackNote(
          `Campaign #${result.id} cancelled` +
            (result.requeued_count != null ? ` (${result.requeued_count} leads re-queued).` : '.'),
        )
      }
      setCancelWarning(result.warning || null)
      void queryClient.invalidateQueries({ queryKey: ['mail-campaigns'] })
      void queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
    },
    onError: (e: unknown) => {
      setCancelWarning(
        e instanceof Error && e.message ? e.message : 'Failed to cancel campaign.',
      )
    },
  })

  const handleCancel = (id: number) => {
    const ok = window.confirm(
      'Cancel this campaign? If Open Letter confirms cancel (or there is no OLC order), ' +
        'leads are re-queued. If the API cannot cancel the order, the queue is held until ' +
        'you cancel in Connect and click Release to queue.',
    )
    if (!ok) return
    cancelMutation.mutate({ id })
  }

  const handleRelease = (id: number) => {
    const ok = window.confirm(
      'Release held leads back to Ready to Mail? Only do this after cancelling the ' +
        'Open Letter order in Connect so pieces are not double-mailed.',
    )
    if (!ok) return
    cancelMutation.mutate({ id, release_queue: true })
  }

  const handleRefresh = async () => {
    setFeedbackNote(null)
    const campaigns = data?.campaigns ?? []
    const results = await Promise.allSettled(
      campaigns
        // Include cancelled campaigns that still have an OLC order so address
        // feedback (Failed/Corrected) can be imported after cancel/requeue.
        .filter((c) => !!c.olc_order_id)
        .map((c) => openLetterService.getCampaign(c.id, true)),
    )
    const totals = { corrected: 0, failed: 0, verified: 0 }
    for (const result of results) {
      if (result.status !== 'fulfilled') continue
      const fb = result.value.address_feedback
      if (!fb) continue
      totals.corrected += fb.corrected || 0
      totals.failed += fb.failed || 0
      totals.verified += fb.verified || 0
    }
    if (totals.corrected || totals.failed || totals.verified) {
      setFeedbackNote(
        `Address feedback: ${totals.corrected} corrected, ${totals.failed} failed, ${totals.verified} verified.`,
      )
    }
    await queryClient.invalidateQueries({ queryKey: ['mail-campaigns'] })
  }

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (error) {
    return <Alert severity="error">Failed to load campaigns.</Alert>
  }

  return (
    <Box sx={{ maxWidth: '100%', minWidth: 0, overflowX: 'hidden' }}>
      {!embedded && (
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            mb: 2,
            flexWrap: 'wrap',
            gap: 1,
            alignItems: { xs: 'stretch', sm: 'center' },
            flexDirection: { xs: 'column', sm: 'row' },
          }}
        >
          <Typography variant="h6">Campaign History</Typography>
          <Button
            size="small"
            startIcon={<RefreshIcon />}
            onClick={handleRefresh}
            disabled={isFetching}
            sx={{ width: { xs: '100%', sm: 'auto' } }}
          >
            Refresh analytics
          </Button>
        </Box>
      )}
      {embedded && (
        <Box
          sx={{
            display: 'flex',
            justifyContent: { xs: 'stretch', sm: 'flex-end' },
            mb: 1,
            flexWrap: 'wrap',
          }}
        >
          <Button
            size="small"
            startIcon={<RefreshIcon />}
            onClick={handleRefresh}
            disabled={isFetching}
            sx={{ width: { xs: '100%', sm: 'auto' } }}
          >
            Refresh analytics
          </Button>
        </Box>
      )}
      {feedbackNote && (
        <Alert severity="info" sx={{ mb: 2 }} onClose={() => setFeedbackNote(null)}>
          {feedbackNote}
        </Alert>
      )}
      {cancelWarning && (
        <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setCancelWarning(null)}>
          {cancelWarning}
        </Alert>
      )}
      <CreativeCompareTable rows={data?.creative_rollup ?? []} />
      <TableContainer component={Paper} sx={{ overflowX: 'auto', maxWidth: '100%' }}>
        <Table size="small" sx={{ minWidth: 1060 }}>
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Sender</TableCell>
              <TableCell>Envelope</TableCell>
              <TableCell>Font</TableCell>
              <TableCell>Email?</TableCell>
              <TableCell>Website?</TableCell>
              <TableCell>Template</TableCell>
              <TableCell>Pieces</TableCell>
              <TableCell>Cost</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Scan rate</TableCell>
              <TableCell>Delivered</TableCell>
              <TableCell>Response</TableCell>
              <TableCell>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(data?.campaigns ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={14} align="center">
                  <Typography color="text.secondary" sx={{ py: 3 }}>
                    No campaigns yet. Send a batch from Ready to Mail.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              data?.campaigns.map((c) => (
                <CampaignRow
                  key={c.id}
                  campaign={c}
                  onCancel={handleCancel}
                  onRelease={handleRelease}
                  cancelling={cancelMutation.isPending}
                />
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}
