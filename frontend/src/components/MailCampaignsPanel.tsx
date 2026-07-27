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
  Tooltip,
  Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatLastMailedDate } from '@/utils/formatLastMailedDate'
import {
  mailCampaignStatusChipLabel,
  mailCampaignStatusColor,
  mailCampaignStatusLabel,
} from '@/utils/mailCampaignStatusColor'
import { mailSubmitReconciliationParts } from '@/utils/formatMailSubmitReconciliation'
import openLetterService, {
  type CreativeRollupRow,
  type MailCampaign,
  type MailCampaignGapKind,
} from '@/services/openLetterApi'
import { Link as RouterLink } from 'react-router-dom'
import { MailCampaignGapLeadsDialog } from '@/components/MailCampaignGapLeadsDialog'

const headerCellSx = {
  fontWeight: 600,
  color: 'text.secondary',
  fontSize: '0.75rem',
  letterSpacing: 0.02,
  py: 0.75,
  px: 1,
} as const

const bodyCellSx = {
  fontWeight: 400,
  color: 'text.primary',
  fontSize: '0.75rem',
  py: 0.75,
  px: 1,
  lineHeight: 1.35,
} as const

const wrapCellSx = {
  ...bodyCellSx,
  overflowWrap: 'anywhere' as const,
  wordBreak: 'break-word' as const,
}

const statusHeaderSx = {
  ...headerCellSx,
  width: '6.5rem',
  whiteSpace: 'nowrap' as const,
}

const statusBodySx = {
  ...bodyCellSx,
  width: '6.5rem',
  whiteSpace: 'nowrap' as const,
}

/** Submitted cell: count + captions share one left stack (button-links default to center). */
const submittedCellSx = {
  ...bodyCellSx,
  textAlign: 'left' as const,
  verticalAlign: 'top' as const,
}

const gapCaptionLinkSx = {
  display: 'inline',
  p: 0,
  m: 0,
  border: 0,
  background: 'none',
  verticalAlign: 'baseline',
  textAlign: 'left' as const,
  font: 'inherit',
  cursor: 'pointer',
  color: 'primary.main',
  textDecoration: 'underline',
  textUnderlineOffset: 2,
  '&:hover': { textDecoration: 'underline' },
} as const

function formatPct(rate: number | null | undefined): string {
  if (rate == null) return '—'
  return `${(rate * 100).toFixed(1)}%`
}

function yn(value: boolean | null | undefined): string {
  if (value == null) return '—'
  return value ? 'Yes' : 'No'
}

function creativeSender(creative: MailCampaign['creative']): string {
  if (!creative) return '—'
  return (
    creative.sender_display_name
    || creative.label
    || [creative.first_name, creative.last_name].filter(Boolean).join(' ')
    || '—'
  )
}

function CampaignRow({
  campaign,
  onCancel,
  onRelease,
  cancelling,
  onOpenGap,
}: {
  campaign: MailCampaign
  onCancel: (id: number) => void
  onRelease: (id: number) => void
  cancelling: boolean
  onOpenGap: (campaignId: number, kind: MailCampaignGapKind) => void
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
  const submittedCount = campaign.submitted_count ?? campaign.lead_count
  const scanPieces =
    (campaign.scan_stats?.scanned ?? 0) + (campaign.scan_stats?.not_scanned ?? 0)
  const hasScanPieces = scanPieces > 0
  const omitCount = campaign.olc_omitted_count
  const hasOmitCache = omitCount != null && omitCount > 0
  // Prefer cached omit count; fall back to scan vs submitted mismatch before first heal sync.
  const showOmitLink = hasOmitCache || (omitCount == null && hasScanPieces && scanPieces !== submittedCount)
  const omitCaption = hasOmitCache
    ? `${omitCount} not on OLC`
    : `OLC tracked ${scanPieces}`
  const reconParts = mailSubmitReconciliationParts(campaign)

  return (
    <TableRow data-testid={`mail-campaign-row-${campaign.id}`}>
      <TableCell sx={bodyCellSx}>
        <Typography variant="inherit" component="div" sx={{ fontSize: 'inherit' }}>
          #{campaign.id}
        </Typography>
        {campaign.olc_order_id ? (
          <Typography variant="caption" color="text.secondary" component="div">
            OLC {campaign.olc_order_id}
          </Typography>
        ) : (
          <Typography variant="caption" color="text.secondary" component="div">
            No OLC order yet
          </Typography>
        )}
      </TableCell>
      <TableCell sx={bodyCellSx}>
        {formatLastMailedDate(campaign.submitted_at || campaign.created_at)}
      </TableCell>
      <TableCell sx={wrapCellSx}>{creativeSender(creative)}</TableCell>
      <TableCell sx={wrapCellSx}>{creative?.envelope_color || '—'}</TableCell>
      <TableCell sx={bodyCellSx}>{creative?.font_color || '—'}</TableCell>
      <TableCell sx={bodyCellSx}>{yn(creative?.include_email)}</TableCell>
      <TableCell sx={bodyCellSx}>{yn(creative?.include_website)}</TableCell>
      <TableCell sx={wrapCellSx}>
        {campaign.template_name || campaign.template_id || '—'}
      </TableCell>
      <TableCell sx={submittedCellSx}>
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-start',
            gap: 0.25,
            width: '100%',
          }}
        >
          <Typography
            component="div"
            sx={{ fontSize: 'inherit', fontWeight: 'inherit', lineHeight: 'inherit', textAlign: 'left' }}
          >
            {submittedCount}
          </Typography>
          {reconParts ? (
            <Typography
              variant="caption"
              color="text.secondary"
              component="div"
              sx={{ textAlign: 'left', width: '100%' }}
            >
              {reconParts.stagedLabel}
              {reconParts.invalidLabel ? (
                <>
                  {' · '}
                  <Box
                    component="button"
                    type="button"
                    onClick={() => onOpenGap(campaign.id, 'invalid_local')}
                    data-testid={`mail-campaign-invalid-link-${campaign.id}`}
                    sx={gapCaptionLinkSx}
                  >
                    {reconParts.invalidLabel}
                  </Box>
                </>
              ) : null}
              {reconParts.dropSummary ? ` · ${reconParts.dropSummary}` : ''}
            </Typography>
          ) : null}
          {showOmitLink ? (
            <Typography
              variant="caption"
              color="text.secondary"
              component="div"
              sx={{ textAlign: 'left', width: '100%' }}
            >
              <Box
                component="button"
                type="button"
                onClick={() => onOpenGap(campaign.id, 'olc_omitted')}
                data-testid={`mail-campaign-olc-omit-link-${campaign.id}`}
                sx={gapCaptionLinkSx}
              >
                {omitCaption}
              </Box>
            </Typography>
          ) : null}
        </Box>
      </TableCell>
      <TableCell sx={bodyCellSx}>
        {campaign.address_feedback ? (
          <Typography variant="caption" component="div" sx={{ whiteSpace: 'nowrap' }}>
            C{campaign.address_feedback.corrected ?? 0}
            {' / '}
            F{campaign.address_feedback.failed ?? 0}
            {' / '}
            V{campaign.address_feedback.verified ?? 0}
          </Typography>
        ) : (
          '—'
        )}
      </TableCell>
      <TableCell sx={bodyCellSx}>
        {campaign.cost != null
          ? `$${Number(campaign.cost).toFixed(2)}`
          : '—'}
      </TableCell>
      <TableCell sx={statusBodySx}>
        <Tooltip title={mailCampaignStatusLabel(campaign.status)} enterDelay={400}>
          <Chip
            label={mailCampaignStatusChipLabel(campaign.status)}
            size="small"
            color={mailCampaignStatusColor(campaign.status)}
            sx={{
              height: 22,
              fontSize: '0.7rem',
              fontWeight: 500,
              '& .MuiChip-label': { px: 1 },
            }}
          />
        </Tooltip>
      </TableCell>
      <TableCell sx={bodyCellSx}>{formatPct(deliveryRate)}</TableCell>
      <TableCell sx={bodyCellSx}>{formatPct(campaign.response_rate)}</TableCell>
      <TableCell sx={bodyCellSx}>
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
      <TableContainer
        component={Paper}
        sx={{
          maxWidth: '100%',
          overflowX: 'auto',
        }}
      >
        <Table size="small" sx={{ width: '100%', tableLayout: 'fixed' }}>
          <TableHead>
            <TableRow>
              <TableCell sx={headerCellSx}>Sender</TableCell>
              <TableCell sx={headerCellSx}>Envelope</TableCell>
              <TableCell sx={headerCellSx}>Ink</TableCell>
              <TableCell sx={headerCellSx}>Email included</TableCell>
              <TableCell sx={headerCellSx}>Website included</TableCell>
              <TableCell sx={headerCellSx}>Campaigns</TableCell>
              <TableCell sx={headerCellSx}>Submitted</TableCell>
              <TableCell sx={headerCellSx}>Response</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={[
                  row.sender_display_name,
                  row.envelope_color,
                  row.font_color,
                  String(row.include_email),
                  String(row.include_website),
                ].join('|')}
              >
                <TableCell sx={wrapCellSx}>{row.sender_display_name}</TableCell>
                <TableCell sx={wrapCellSx}>{row.envelope_color}</TableCell>
                <TableCell sx={bodyCellSx}>
                  {row.font_color && row.font_color !== '—' ? row.font_color : '—'}
                </TableCell>
                <TableCell sx={bodyCellSx}>{yn(row.include_email)}</TableCell>
                <TableCell sx={bodyCellSx}>{yn(row.include_website)}</TableCell>
                <TableCell sx={bodyCellSx}>{row.campaign_count}</TableCell>
                <TableCell sx={bodyCellSx}>{row.lead_count}</TableCell>
                <TableCell sx={bodyCellSx}>{formatPct(row.response_rate)}</TableCell>
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
  const [gapDialog, setGapDialog] = useState<{
    campaignId: number
    kind: MailCampaignGapKind
  } | null>(null)
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['mail-campaigns'],
    queryFn: () => openLetterService.listCampaigns(1, 100),
    refetchInterval: 60_000,
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
          <Box
            sx={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 1,
              alignItems: 'center',
              width: { xs: '100%', sm: 'auto' },
            }}
          >
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ fontWeight: 600, mr: { xs: 0, sm: 0.5 } }}
            >
              Go to queues
            </Typography>
            <Button
              size="small"
              variant="outlined"
              component={RouterLink}
              to="/queues/ready-to-mail"
              sx={{ width: { xs: '100%', sm: 'auto' } }}
            >
              Ready to Mail
            </Button>
            <Button
              size="small"
              variant="outlined"
              component={RouterLink}
              to="/queues/skip-trace"
              sx={{ width: { xs: '100%', sm: 'auto' } }}
            >
              Skip Trace
            </Button>
          </Box>
          <Button
            size="small"
            variant="outlined"
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
            gap: 1,
          }}
        >
          <Button
            size="small"
            variant="outlined"
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
      <Box>
        <Typography variant="subtitle1" gutterBottom>
          Mailer campaigns
        </Typography>
        <TableContainer
          component={Paper}
          sx={{
            maxWidth: '100%',
            overflowX: 'auto',
          }}
        >
          <Table
            size="small"
            sx={{ width: '100%', tableLayout: 'fixed' }}
            data-testid="mail-campaigns-table"
          >
            <TableHead>
              <TableRow>
                <TableCell sx={headerCellSx}>Campaign</TableCell>
                <TableCell sx={headerCellSx}>Date</TableCell>
                <TableCell sx={headerCellSx}>Sender</TableCell>
                <TableCell sx={headerCellSx}>Envelope</TableCell>
                <TableCell sx={headerCellSx}>Ink</TableCell>
                <TableCell sx={headerCellSx}>Email included</TableCell>
                <TableCell sx={headerCellSx}>Website included</TableCell>
                <TableCell sx={headerCellSx}>Template</TableCell>
                <TableCell sx={{ ...headerCellSx, textAlign: 'left' }}>Submitted</TableCell>
                <TableCell sx={headerCellSx}>OLC feedback</TableCell>
                <TableCell sx={headerCellSx}>Cost</TableCell>
                <TableCell sx={statusHeaderSx}>Status</TableCell>
                <TableCell sx={headerCellSx}>Delivered</TableCell>
                <TableCell sx={headerCellSx}>Response</TableCell>
                <TableCell sx={headerCellSx}>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(data?.campaigns ?? []).length === 0 ? (
                <TableRow>
                  <TableCell colSpan={15} align="center" sx={bodyCellSx}>
                    <Typography color="text.secondary" sx={{ py: 3, fontSize: '0.875rem' }}>
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
                    onOpenGap={(campaignId, kind) => setGapDialog({ campaignId, kind })}
                  />
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
      <MailCampaignGapLeadsDialog
        open={gapDialog != null}
        onClose={() => setGapDialog(null)}
        campaignId={gapDialog?.campaignId ?? null}
        kind={gapDialog?.kind ?? null}
      />
    </Box>
  )
}
