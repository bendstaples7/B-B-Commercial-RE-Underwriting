/**
 * WebhookSyncPanel — HubSpot webhook sync configuration and monitoring panel.
 *
 * Sections:
 *  1. Client Secret Input (write-only; "Configured ✓" badge when saved)
 *  2. Webhook URL (read-only copyable field)
 *  3. Setup Instructions (step-by-step HubSpot UI guide)
 *  4. Last Synced timestamp + stale warning banner
 *  5. 24-Hour Summary (processed / failed / deduplicated counts)
 *  6. Webhook Log Table (paginated, with Retry button for failed rows)
 */
import React, { useState } from 'react'
import {
  Box,
  Typography,
  TextField,
  Button,
  Chip,
  Paper,
  Alert,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Tooltip,
  IconButton,
  InputAdornment,
  Divider,
  List,
  ListItem,
  ListItemText,
} from '@mui/material'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import RefreshIcon from '@mui/icons-material/Refresh'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { hubSpotService } from '@/services/api'
import type { WebhookLog, WebhookLogStatus } from '@/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface WebhookSyncPanelProps {
  hasClientSecret: boolean
  onClientSecretSaved: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const WEBHOOK_URL = `${window.location.origin}/api/hubspot/webhook`

const EVENT_TYPES = [
  'deal.creation',
  'deal.deletion',
  'deal.propertyChange',
  'contact.creation',
  'contact.deletion',
  'contact.propertyChange',
  'company.creation',
  'company.deletion',
  'company.propertyChange',
  'contact.associationChange',
]

function statusColor(
  status: WebhookLogStatus
): 'default' | 'success' | 'error' | 'warning' | 'info' | 'primary' {
  switch (status) {
    case 'processed':
      return 'success'
    case 'failed':
      return 'error'
    case 'processing':
      return 'info'
    case 'pending':
      return 'warning'
    case 'deduplicated':
    case 'loop_suppressed':
      return 'default'
    default:
      return 'default'
  }
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function isStale(lastSyncedAt: string | null): boolean {
  if (!lastSyncedAt) return true
  const diff = Date.now() - new Date(lastSyncedAt).getTime()
  return diff > 24 * 60 * 60 * 1000
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const WebhookSyncPanel: React.FC<WebhookSyncPanelProps> = ({
  hasClientSecret,
  onClientSecretSaved,
}) => {
  const queryClient = useQueryClient()

  // ── Local state ──────────────────────────────────────────────────────────
  const [clientSecretInput, setClientSecretInput] = useState('')
  const [copySuccess, setCopySuccess] = useState(false)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(10)

  // ── Queries ──────────────────────────────────────────────────────────────

  const {
    data: logData,
    isLoading: logLoading,
    error: logError,
  } = useQuery({
    queryKey: ['hubspot', 'webhook-log', page, rowsPerPage],
    queryFn: () =>
      hubSpotService.getWebhookLog({ page: page + 1, per_page: rowsPerPage }),
    refetchInterval: 30_000,
  })

  const {
    data: summary,
    isLoading: summaryLoading,
  } = useQuery({
    queryKey: ['hubspot', 'webhook-summary'],
    queryFn: () => hubSpotService.getWebhookLogSummary(),
    refetchInterval: 30_000,
  })

  // ── Mutations ────────────────────────────────────────────────────────────

  const saveSecretMutation = useMutation({
    mutationFn: () =>
      hubSpotService.saveHubSpotConfigWithSecret('', undefined, clientSecretInput),
    onSuccess: () => {
      setClientSecretInput('')
      onClientSecretSaved()
      queryClient.invalidateQueries({ queryKey: ['hubspot', 'config'] })
    },
  })

  const retryMutation = useMutation({
    mutationFn: (logId: number) => hubSpotService.retryWebhookEvent(logId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hubspot', 'webhook-log'] })
      queryClient.invalidateQueries({ queryKey: ['hubspot', 'webhook-summary'] })
    },
  })

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleCopyUrl = async () => {
    try {
      await navigator.clipboard.writeText(WEBHOOK_URL)
      setCopySuccess(true)
      setTimeout(() => setCopySuccess(false), 2000)
    } catch {
      // fallback: select the text
    }
  }

  const handleChangePage = (_: unknown, newPage: number) => {
    setPage(newPage)
  }

  const handleChangeRowsPerPage = (event: React.ChangeEvent<HTMLInputElement>) => {
    setRowsPerPage(parseInt(event.target.value, 10))
    setPage(0)
  }

  // ── Render ───────────────────────────────────────────────────────────────

  const stale = isStale(summary?.last_synced_at ?? null)

  return (
    <Box aria-label="Webhook sync panel">
      {/* ── Section 1: Client Secret ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="webhook-secret-heading">
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <Typography variant="h6" id="webhook-secret-heading">
            Webhook Client Secret
          </Typography>
          {hasClientSecret && (
            <Chip
              icon={<CheckCircleOutlineIcon fontSize="small" />}
              label="Configured ✓"
              color="success"
              size="small"
              aria-label="Client secret is configured"
            />
          )}
        </Box>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Enter your HubSpot app's client secret to enable webhook signature verification.
          The secret is stored encrypted and never returned in API responses.
        </Typography>

        <Box
          component="form"
          onSubmit={(e) => {
            e.preventDefault()
            saveSecretMutation.mutate()
          }}
          sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}
        >
          <TextField
            label="Client Secret"
            type="password"
            value={clientSecretInput}
            onChange={(e) => setClientSecretInput(e.target.value)}
            placeholder={hasClientSecret ? '••••••••••••••••' : 'Enter client secret'}
            size="small"
            sx={{ minWidth: 320 }}
            autoComplete="new-password"
            inputProps={{ 'aria-label': 'HubSpot client secret' }}
          />
          <Button
            type="submit"
            variant="contained"
            disabled={!clientSecretInput || saveSecretMutation.isPending}
            startIcon={
              saveSecretMutation.isPending ? (
                <CircularProgress size={16} color="inherit" />
              ) : undefined
            }
          >
            {saveSecretMutation.isPending ? 'Saving…' : 'Save Secret'}
          </Button>
        </Box>

        {saveSecretMutation.isSuccess && (
          <Alert severity="success" sx={{ mt: 2 }} icon={<CheckCircleOutlineIcon />}>
            Client secret saved successfully.
          </Alert>
        )}
        {saveSecretMutation.isError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {(saveSecretMutation.error as Error).message}
          </Alert>
        )}
      </Paper>

      {/* ── Section 2: Webhook URL ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="webhook-url-heading">
        <Typography variant="h6" id="webhook-url-heading" gutterBottom>
          Webhook URL
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Copy this URL and paste it into your HubSpot app's webhook settings.
        </Typography>
        <TextField
          value={WEBHOOK_URL}
          size="small"
          fullWidth
          InputProps={{
            readOnly: true,
            endAdornment: (
              <InputAdornment position="end">
                <Tooltip title={copySuccess ? 'Copied!' : 'Copy URL'}>
                  <IconButton
                    onClick={handleCopyUrl}
                    size="small"
                    aria-label="Copy webhook URL"
                    color={copySuccess ? 'success' : 'default'}
                  >
                    <ContentCopyIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </InputAdornment>
            ),
          }}
          inputProps={{ 'aria-label': 'Webhook URL', 'data-testid': 'webhook-url-field' }}
        />
      </Paper>

      {/* ── Section 3: Setup Instructions ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="webhook-setup-heading">
        <Typography variant="h6" id="webhook-setup-heading" gutterBottom>
          Setup Instructions
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Follow these steps to configure webhook delivery in HubSpot:
        </Typography>
        <List dense disablePadding>
          {[
            'In HubSpot, go to Settings → Integrations → Private Apps.',
            'Select your private app and click the "Webhooks" tab.',
            'Set the Target URL to the webhook URL shown above.',
            'Under "Subscriptions", click "Add subscription" and enable the following event types:',
            'Copy the "Client secret" from the app settings and save it in the field above.',
            'Click "Save" in HubSpot to activate the webhook.',
          ].map((step, i) => (
            <ListItem key={i} sx={{ py: 0.25, pl: 0 }}>
              <ListItemText
                primary={
                  <Typography variant="body2">
                    <strong>{i + 1}.</strong> {step}
                  </Typography>
                }
              />
            </ListItem>
          ))}
        </List>
        <Box sx={{ mt: 1, pl: 2 }}>
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 0.5 }}>
            Required event types:
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
            {EVENT_TYPES.map((et) => (
              <Chip key={et} label={et} size="small" variant="outlined" />
            ))}
          </Box>
        </Box>
      </Paper>

      {/* ── Section 4 & 5: Last Synced + 24-Hour Summary ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="webhook-status-heading">
        <Typography variant="h6" id="webhook-status-heading" gutterBottom>
          Sync Status
        </Typography>

        {summaryLoading && <CircularProgress size={20} sx={{ mb: 2 }} />}

        {/* Stale warning */}
        {!summaryLoading && stale && (
          <Alert
            severity="warning"
            icon={<WarningAmberIcon />}
            sx={{ mb: 2 }}
            aria-label="No webhook events received in the last 24 hours"
          >
            {summary?.last_synced_at
              ? `No webhook events received since ${formatDateTime(summary.last_synced_at)}. Check your HubSpot webhook configuration.`
              : 'No webhook events have been received yet. Verify the webhook URL is configured in HubSpot.'}
          </Alert>
        )}

        {/* Last synced */}
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Last synced:{' '}
            <strong>{formatDateTime(summary?.last_synced_at ?? null)}</strong>
          </Typography>
        </Box>

        <Divider sx={{ mb: 2 }} />

        {/* 24-hour summary counts */}
        <Typography variant="subtitle2" gutterBottom>
          Last 24 Hours
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          <Chip
            label={`${summary?.processed_count ?? 0} processed`}
            color={(summary?.processed_count ?? 0) > 0 ? 'success' : 'default'}
            size="small"
            aria-label={`${summary?.processed_count ?? 0} processed events`}
          />
          <Chip
            label={`${summary?.failed_count ?? 0} failed`}
            color={(summary?.failed_count ?? 0) > 0 ? 'error' : 'default'}
            size="small"
            aria-label={`${summary?.failed_count ?? 0} failed events`}
          />
          <Chip
            label={`${summary?.deduplicated_count ?? 0} deduplicated`}
            color="default"
            size="small"
            aria-label={`${summary?.deduplicated_count ?? 0} deduplicated events`}
          />
        </Box>
      </Paper>

      {/* ── Section 6: Webhook Log Table ── */}
      <Paper sx={{ p: 3 }} aria-labelledby="webhook-log-heading">
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6" id="webhook-log-heading">
            Webhook Log
          </Typography>
          <Tooltip title="Refresh log">
            <IconButton
              size="small"
              onClick={() => {
                queryClient.invalidateQueries({ queryKey: ['hubspot', 'webhook-log'] })
                queryClient.invalidateQueries({ queryKey: ['hubspot', 'webhook-summary'] })
              }}
              aria-label="Refresh webhook log"
            >
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>

        {logLoading && <CircularProgress size={20} />}
        {logError && (
          <Alert severity="error">Failed to load webhook log.</Alert>
        )}

        {logData && logData.logs.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No webhook events yet.
          </Typography>
        )}

        {logData && logData.logs.length > 0 && (
          <>
            <TableContainer>
              <Table size="small" aria-label="Webhook log table">
                <TableHead>
                  <TableRow>
                    <TableCell>ID</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Object Type</TableCell>
                    <TableCell>Object ID</TableCell>
                    <TableCell>Event Type</TableCell>
                    <TableCell>Received</TableCell>
                    <TableCell>Processed</TableCell>
                    <TableCell>Action</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {logData.logs.map((log: WebhookLog) => (
                    <TableRow key={log.id} hover>
                      <TableCell>{log.id}</TableCell>
                      <TableCell>
                        <Tooltip title={log.error_message || ''} disableHoverListener={!log.error_message}>
                          <Chip
                            label={log.status}
                            color={statusColor(log.status)}
                            size="small"
                            aria-label={`Status: ${log.status}`}
                          />
                        </Tooltip>
                      </TableCell>
                      <TableCell>{log.hubspot_object_type}</TableCell>
                      <TableCell sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>
                        {log.hubspot_object_id}
                      </TableCell>
                      <TableCell sx={{ fontSize: '0.75rem' }}>{log.event_type}</TableCell>
                      <TableCell sx={{ whiteSpace: 'nowrap', fontSize: '0.75rem' }}>
                        {formatDateTime(log.received_at)}
                      </TableCell>
                      <TableCell sx={{ whiteSpace: 'nowrap', fontSize: '0.75rem' }}>
                        {formatDateTime(log.processed_at)}
                      </TableCell>
                      <TableCell>
                        {log.status === 'failed' && (
                          <Button
                            size="small"
                            variant="outlined"
                            color="warning"
                            onClick={() => retryMutation.mutate(log.id)}
                            disabled={retryMutation.isPending}
                            aria-label={`Retry webhook event ${log.id}`}
                            data-testid={`retry-btn-${log.id}`}
                          >
                            {retryMutation.isPending ? (
                              <CircularProgress size={14} color="inherit" />
                            ) : (
                              'Retry'
                            )}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
            <TablePagination
              component="div"
              count={logData.total}
              page={page}
              onPageChange={handleChangePage}
              rowsPerPage={rowsPerPage}
              onRowsPerPageChange={handleChangeRowsPerPage}
              rowsPerPageOptions={[10, 25, 50]}
              aria-label="Webhook log pagination"
            />
          </>
        )}
      </Paper>
    </Box>
  )
}

export default WebhookSyncPanel
