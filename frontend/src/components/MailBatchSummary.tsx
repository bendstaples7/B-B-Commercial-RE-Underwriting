import React, { useCallback, useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  LinearProgress,
  Paper,
  Typography,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link as RouterLink } from 'react-router-dom'
import openLetterService, { type MailQueueSummary } from '@/services/openLetterApi'
import { getActiveCreativePreset, isDirectMailReadyToSend } from '@/utils/directMailSetup'

export interface MailBatchSummaryProps {
  title?: string
  queueData?: MailQueueSummary
  isLoading?: boolean
}

export const MailBatchSummary: React.FC<MailBatchSummaryProps> = ({
  title = 'Next batch',
  queueData,
  isLoading = false,
}) => {
  const queryClient = useQueryClient()
  const [sendDialogOpen, setSendDialogOpen] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)

  const { data: olcConfig } = useQuery({
    queryKey: ['open-letter-config'],
    queryFn: () => openLetterService.getConfig(),
  })

  const sendMutation = useMutation({
    mutationFn: (force: boolean) => openLetterService.sendBatch(force),
    onSuccess: () => {
      setSendDialogOpen(false)
      queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
      queryClient.invalidateQueries({ queryKey: ['mail-campaigns'] })
      queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
    },
    onError: (err: Error) => setSendError(err.message),
  })

  const handleSend = useCallback(() => {
    setSendError(null)
    const force = queueData ? queueData.queued_count < queueData.batch_minimum : false
    sendMutation.mutate(force)
  }, [queueData, sendMutation])

  const queuedCount = queueData?.queued_count ?? 0
  const batchMinimum = queueData?.batch_minimum ?? 50
  const progress = batchMinimum > 0 ? Math.min(100, (queuedCount / batchMinimum) * 100) : 0
  const canSend = queueData?.can_send ?? false
  const readyToSend = isDirectMailReadyToSend(olcConfig)
  const activeCreative = getActiveCreativePreset(olcConfig)

  return (
    <>
      <Paper sx={{ p: 2, mb: 2 }} data-testid="mail-batch-summary">
        <Typography variant="h6" gutterBottom>
          {title}
        </Typography>
        {isLoading ? (
          <LinearProgress sx={{ mb: 2 }} />
        ) : (
          <>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {queuedCount} of {batchMinimum} leads staged for the next batch
            </Typography>
            {activeCreative && (
              <Typography variant="body2" sx={{ mb: 1 }}>
                Active creative:{' '}
                <strong>{activeCreative.label || activeCreative.sender_display_name}</strong>
                {activeCreative.envelope_color ? ` · ${activeCreative.envelope_color} envelope` : ''}
                {activeCreative.font_name ? ` · ${activeCreative.font_name}` : ''}
              </Typography>
            )}
            <LinearProgress variant="determinate" value={progress} sx={{ mb: 2, height: 8, borderRadius: 1 }} />
            {queueData?.estimated_total != null && (
              <Typography variant="body2" sx={{ mb: 1 }}>
                Estimated total: ~${queueData.estimated_total.toFixed(2)}
                {queueData.estimated_cost_per_piece != null && (
                  <> ({queueData.estimated_cost_per_piece.toFixed(2)}/piece)</>
                )}
              </Typography>
            )}
            <Button
              variant="contained"
              startIcon={<SendIcon />}
              disabled={!canSend || !readyToSend || sendMutation.isPending}
              onClick={() => setSendDialogOpen(true)}
              data-testid="send-batch-button"
            >
              Send Batch
            </Button>
            {!readyToSend && (
              <Alert severity="warning" sx={{ mt: 2 }}>
                Finish Open Letter setup (product, template, creative sender name/phone, and return
                street) in{' '}
                <RouterLink to="/marketing/direct-mail">Setup</RouterLink>
                {' '}before sending.
              </Alert>
            )}
            {!olcConfig?.configured && (
              <Alert severity="warning" sx={{ mt: 2 }}>
                Open Letter is not connected.{' '}
                <RouterLink to="/marketing/direct-mail">Connect your account</RouterLink>
              </Alert>
            )}
            {readyToSend && !canSend && queuedCount > 0 && (
              <Typography variant="caption" display="block" sx={{ mt: 1 }} color="text.secondary">
                Add {batchMinimum - queuedCount} more leads to unlock send
                {queueData?.allow_send_below_minimum ? ' (or enable below-minimum send in Setup)' : ''}.
              </Typography>
            )}
          </>
        )}
      </Paper>

      <Dialog open={sendDialogOpen} onClose={() => setSendDialogOpen(false)}>
        <DialogTitle>Send mail batch?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will submit {queuedCount} mailers to Open Letter Connect
            {activeCreative
              ? ` using creative “${activeCreative.label || activeCreative.sender_display_name}”`
              : ''}
            .
            {queueData?.estimated_total != null && (
              <> Estimated charge: ~${queueData.estimated_total.toFixed(2)} on your OLC payment method.</>
            )}
          </DialogContentText>
          {sendError && <Alert severity="error" sx={{ mt: 2 }}>{sendError}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSendDialogOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleSend} disabled={sendMutation.isPending}>
            {sendMutation.isPending ? 'Submitting…' : 'Confirm send'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
