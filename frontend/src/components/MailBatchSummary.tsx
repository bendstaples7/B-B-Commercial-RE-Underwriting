import React, { useCallback, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  LinearProgress,
  Paper,
  Skeleton,
  Typography,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link as RouterLink } from 'react-router-dom'
import openLetterService, { type MailQueueSummary } from '@/services/openLetterApi'
import {
  extractOlcListRows,
  getActiveCreativePreset,
  getOlcCatalogSendLines,
  isDirectMailReadyToSend,
} from '@/utils/directMailSetup'
import { formatLastMailedDate } from '@/utils/formatLastMailedDate'
import type { OlcProduct } from '@/utils/olcProductHelpers'

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

  const { data: productsPayload } = useQuery({
    queryKey: ['open-letter-products'],
    queryFn: () => openLetterService.listProducts(),
    enabled: Boolean(olcConfig?.configured),
  })

  const products = useMemo(
    () => extractOlcListRows(productsPayload) as OlcProduct[],
    [productsPayload],
  )

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
  const catalog = getOlcCatalogSendLines(olcConfig, products)

  return (
    <>
      <Paper sx={{ p: 2, mb: 2 }} data-testid="mail-batch-summary">
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            gap: 2,
            mb: 1.5,
          }}
        >
          <Typography variant="h6">{title}</Typography>
          <Box textAlign="right">
            <Typography
              variant="subtitle1"
              component="p"
              fontWeight={700}
              lineHeight={1.2}
              data-testid="mail-batch-staged-count"
            >
              {queuedCount} of {batchMinimum}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              leads staged
            </Typography>
          </Box>
        </Box>
        {isLoading && !queueData ? (
          <Skeleton variant="rounded" height={112} data-testid="mail-batch-skeleton" />
        ) : (
          <>
            {(catalog.productLine || catalog.templateLine) && (
              <Typography variant="body2" sx={{ mb: 0.5 }} data-testid="mail-batch-olc-catalog">
                Open Letter product:{' '}
                <strong>{catalog.productLine || '—'}</strong>
                {catalog.templateLine ? (
                  <>
                    {' · Template: '}
                    <strong>{catalog.templateLine}</strong>
                  </>
                ) : null}
              </Typography>
            )}
            {catalog.senderLine && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Sender / creative: <strong>{catalog.senderLine}</strong>
              </Typography>
            )}
            <LinearProgress variant="determinate" value={progress} sx={{ mb: 2, height: 8, borderRadius: 1 }} />
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 2,
                flexWrap: 'wrap',
              }}
            >
              <Button
                variant="contained"
                startIcon={<SendIcon />}
                disabled={!canSend || !readyToSend || sendMutation.isPending}
                onClick={() => setSendDialogOpen(true)}
                data-testid="send-batch-button"
              >
                Send Batch
              </Button>
              {queueData?.estimated_cost_per_piece != null
                && queueData.estimated_cost_per_piece > 0 ? (
                <Box sx={{ ml: 'auto', textAlign: 'right', maxWidth: 420 }}>
                  <Typography variant="body2" data-testid="mail-batch-estimated-total">
                    Estimated total: ~${(queueData.estimated_total ?? 0).toFixed(2)}
                    {' '}(${queueData.estimated_cost_per_piece.toFixed(2)}/piece)
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {queueData.estimated_cost_source_sent_at
                      ? `Based on mailer cost from the batch sent on ${formatLastMailedDate(queueData.estimated_cost_source_sent_at)}.`
                      : 'Based on your last recorded mailer cost per piece.'}
                  </Typography>
                </Box>
              ) : (
                <Typography
                  variant="body2"
                  color="text.secondary"
                  textAlign="right"
                  sx={{ ml: 'auto' }}
                  data-testid="mail-batch-estimate-pending"
                >
                  Estimated total will appear after your first mail batch is sent.
                </Typography>
              )}
            </Box>
            {!readyToSend && (
              <Box
                component={RouterLink}
                to="/marketing/direct-mail"
                aria-label="Open Direct Mail Setup"
                sx={{
                  mt: 2,
                  display: 'block',
                  textDecoration: 'none',
                  color: 'inherit',
                }}
                data-testid="mail-batch-setup-required"
              >
                <Alert
                  severity="warning"
                  sx={{
                    cursor: 'pointer',
                    alignItems: 'center',
                    py: 0.75,
                    transition: 'background-color 0.15s ease, box-shadow 0.15s ease',
                    '&:hover': {
                      bgcolor: 'warning.light',
                      boxShadow: (theme) => `inset 0 0 0 1px ${theme.palette.warning.dark}`,
                    },
                    '& .MuiAlert-icon': {
                      py: 0,
                      marginRight: 1.25,
                      alignItems: 'center',
                    },
                    '& .MuiAlert-message': {
                      py: 0,
                      display: 'flex',
                      alignItems: 'center',
                    },
                  }}
                >
                  <Typography
                    variant="body2"
                    sx={{
                      color: 'warning.dark',
                      fontWeight: 600,
                      textDecoration: 'underline',
                      textUnderlineOffset: 3,
                      textDecorationThickness: '1.5px',
                      lineHeight: 1.4,
                    }}
                  >
                    Finish Open Letter setup before sending (product, template, sender name/phone,
                    and return street) →
                  </Typography>
                </Alert>
              </Box>
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
            {catalog.productLine
              ? ` as “${catalog.productLine}”`
              : activeCreative
                ? ` using creative “${activeCreative.label || activeCreative.sender_display_name}”`
                : ''}
            {catalog.templateLine ? ` (template ${catalog.templateLine})` : ''}
            .
            {queueData?.estimated_total != null
              && queueData.estimated_cost_per_piece != null
              && queueData.estimated_cost_per_piece > 0 && (
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
