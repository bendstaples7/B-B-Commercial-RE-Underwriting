import React from 'react'
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
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { formatLastMailedDate } from '@/utils/formatLastMailedDate'
import { mailCampaignStatusColor } from '@/utils/mailCampaignStatusColor'
import openLetterService, { type MailCampaign } from '@/services/openLetterApi'

function formatPct(rate: number | null | undefined): string {
  if (rate == null) return '—'
  return `${(rate * 100).toFixed(1)}%`
}

function CampaignRow({ campaign }: { campaign: MailCampaign }) {
  const delivered = campaign.delivery_stats?.Delivered
  const mailed = campaign.delivery_stats?.Mailed
  const deliveryRate =
    delivered != null && mailed ? delivered / Math.max(mailed, 1) : null

  return (
    <TableRow>
      <TableCell>{formatLastMailedDate(campaign.submitted_at || campaign.created_at)}</TableCell>
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
    </TableRow>
  )
}

export const MailCampaignsPanel: React.FC<{ embedded?: boolean }> = ({ embedded = false }) => {
  const queryClient = useQueryClient()
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['mail-campaigns'],
    queryFn: () => openLetterService.listCampaigns(),
  })

  const handleRefresh = async () => {
    const campaigns = data?.campaigns ?? []
    await Promise.allSettled(
      campaigns
        .filter((c) => c.olc_order_id)
        .map((c) => openLetterService.getCampaign(c.id, true)),
    )
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
      <TableContainer component={Paper} sx={{ overflowX: 'auto', maxWidth: '100%' }}>
        <Table size="small" sx={{ minWidth: 640 }}>
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Template</TableCell>
              <TableCell>Pieces</TableCell>
              <TableCell>Cost</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Scan rate</TableCell>
              <TableCell>Delivered</TableCell>
              <TableCell>Response</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(data?.campaigns ?? []).length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center">
                  <Typography color="text.secondary" sx={{ py: 3 }}>
                    No campaigns yet. Send a batch from Ready to Mail.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              data?.campaigns.map((c) => <CampaignRow key={c.id} campaign={c} />)
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}
