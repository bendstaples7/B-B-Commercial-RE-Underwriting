/**
 * HubSpotImportArea — Admin panel for HubSpot CRM migration.
 *
 * Sections:
 *  1. Connection config form (masked token, save, test connection)
 *  2. "Read-Only Mode" badge (always visible when configured)
 *  3. Import trigger panel (object-type checkboxes + Start Import)
 *  4. SSE-driven progress per object type
 *  5. Import history table
 *  6. Backup export section
 *  7. Review Queue badge (pending count)
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 7.7, 7.8, 9.1, 9.4, 9.5,
 *               13.6, 19.4, 20.1
 */
import React, { useState, useEffect, useRef, useCallback } from 'react'
import {
  Box,
  Typography,
  TextField,
  Button,
  Chip,
  Paper,
  Alert,
  CircularProgress,
  FormGroup,
  FormControlLabel,
  Checkbox,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  LinearProgress,
  Tooltip,
  Badge,
  Link as MuiLink,
} from '@mui/material'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import LockIcon from '@mui/icons-material/Lock'
import SyncIcon from '@mui/icons-material/Sync'
import CloudDownloadIcon from '@mui/icons-material/CloudDownload'
import BackupIcon from '@mui/icons-material/Backup'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RateReviewIcon from '@mui/icons-material/RateReview'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link as RouterLink } from 'react-router-dom'
import { hubSpotService } from '@/services/api'
import type { HubSpotConfig, HubSpotImportRun } from '@/types'
import { WebhookSyncPanel } from '@/components/WebhookSyncPanel'
import { usePipelineStatus } from '@/context/PipelineStatusContext'
import { useAuth } from '@/context/AuthContext'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SseProgressEvent {
  object_type: string
  total_fetched: number
  created_count: number
  updated_count: number
  error_count: number
  status: string
  /** 0–100 */
  percent?: number
}

interface ProgressState {
  [objectType: string]: SseProgressEvent
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const OBJECT_TYPES = ['deals', 'contacts', 'companies', 'engagements'] as const
type ObjectType = (typeof OBJECT_TYPES)[number]

function statusColor(
  status: string
): 'default' | 'success' | 'error' | 'warning' | 'info' | 'primary' {
  switch (status) {
    case 'success':
      return 'success'
    case 'failed':
      return 'error'
    case 'partial':
      return 'warning'
    case 'running':
      return 'info'
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const HubSpotImportArea: React.FC = () => {
  const queryClient = useQueryClient()
  const { user } = useAuth()

  // ── Config form state ────────────────────────────────────────────────────
  const [tokenInput, setTokenInput] = useState('')
  const [portalIdInput, setPortalIdInput] = useState('')
  const [testResult, setTestResult] = useState<{
    success: boolean
    account_name?: string
    portal_id?: string
    error?: string
  } | null>(null)

  // ── Import trigger state ─────────────────────────────────────────────────
  const [selectedTypes, setSelectedTypes] = useState<Record<ObjectType, boolean>>({
    deals: true,
    contacts: true,
    companies: true,
    engagements: true,
  })
  const [activeRunId, setActiveRunId] = useState<number | null>(null)
  const [progress, setProgress] = useState<ProgressState>({})
  const [importError, setImportError] = useState<string | null>(null)
  const sseRef = useRef<EventSource | null>(null)

  // ── Backup state ─────────────────────────────────────────────────────────
  const [backupTaskId, setBackupTaskId] = useState<string | null>(null)
  const [backupError, setBackupError] = useState<string | null>(null)

  // ── Queries ──────────────────────────────────────────────────────────────

  const {
    data: config,
    isLoading: configLoading,
    error: configError,
  } = useQuery<HubSpotConfig>({
    queryKey: ['hubspot', 'config'],
    queryFn: () => hubSpotService.getHubSpotConfig(),
    retry: false,
  })

  const {
    data: runsData,
    isLoading: runsLoading,
    error: runsError,
  } = useQuery({
    queryKey: ['hubspot', 'runs'],
    queryFn: () => hubSpotService.listImportRuns(1, 20),
    refetchInterval: activeRunId ? 5000 : false,
  })

  const {
    data: reviewQueueData,
  } = useQuery({
    queryKey: ['hubspot', 'reviewQueue', 'pending'],
    queryFn: () => hubSpotService.getReviewQueue({ page: 1, per_page: 1 }),
    retry: false,
  })

  const pipelineStatus = usePipelineStatus()

  const pendingCount = reviewQueueData?.total ?? 0

  // ── Mutations ────────────────────────────────────────────────────────────

  const saveConfigMutation = useMutation({
    mutationFn: () => hubSpotService.saveHubSpotConfig(tokenInput, portalIdInput || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hubspot', 'config'] })
      setTokenInput('')
    },
  })

  const testConnectionMutation = useMutation({
    mutationFn: () => hubSpotService.testHubSpotConnection(),
    onSuccess: (data) => setTestResult(data),
    onError: (err: Error) =>
      setTestResult({ success: false, error: err.message }),
  })

  const triggerImportMutation = useMutation({
    mutationFn: () => {
      const types = OBJECT_TYPES.filter((t) => selectedTypes[t])
      return hubSpotService.triggerHubSpotImport(types)
    },
    onSuccess: (data) => {
      // Backend returns run_ids array (one per object type). Track the first
      // run ID for SSE progress — all runs share the same import session.
      setActiveRunId(data.run_ids?.[0] ?? null)
      setProgress({})
      setImportError(null)
      queryClient.invalidateQueries({ queryKey: ['hubspot', 'runs'] })
    },
    onError: (err: Error) => setImportError(err.message),
  })

  const runPipelineMutation = useMutation({
    mutationFn: () =>
      fetch('/api/hubspot/pipeline/run', { method: 'POST' }).then((r) => r.json()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hubspot', 'pipeline', 'status'] })
    },
  })

  const backupMutation = useMutation({
    mutationFn: () => hubSpotService.triggerBackupExport(),
    onSuccess: (data) => {
      setBackupTaskId(data.task_id)
      setBackupError(null)
    },
    onError: (err: Error) => setBackupError(err.message),
  })

  // ── SSE progress stream ──────────────────────────────────────────────────

  const closeSse = useCallback(() => {
    if (sseRef.current) {
      sseRef.current.close()
      sseRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!activeRunId) return

    closeSse()

    const es = new EventSource(`/api/hubspot/import/${activeRunId}/progress`)
    sseRef.current = es

    es.onmessage = (event) => {
      try {
        const data: SseProgressEvent = JSON.parse(event.data)
        setProgress((prev) => ({ ...prev, [data.object_type]: data }))

        // When all active types report a terminal status, stop polling
        if (data.status === 'success' || data.status === 'failed' || data.status === 'partial') {
          queryClient.invalidateQueries({ queryKey: ['hubspot', 'runs'] })
        }
      } catch {
        // ignore malformed events
      }
    }

    es.onerror = () => {
      // SSE connection closed (run finished or network error)
      closeSse()
      setActiveRunId(null)
      queryClient.invalidateQueries({ queryKey: ['hubspot', 'runs'] })
    }

    return () => closeSse()
  }, [activeRunId, closeSse, queryClient])

  // ── Backup download ──────────────────────────────────────────────────────

  const handleDownloadBackup = async () => {
    try {
      const blob = await hubSpotService.downloadBackupExport()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `hubspot_backup_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      setBackupError(err.message || 'Download failed')
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────

  const isConfigured = Boolean(config && config.configured !== false)
  const writeBackEnabled = Boolean(config?.write_back_enabled)

  return (
    <Box sx={{ maxWidth: 900, mx: 'auto', p: { xs: 2, sm: 3 } }}>
      {/* ── Page header ── */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
        <Typography variant="h5" component="h1">
          HubSpot CRM Import
        </Typography>

        {isConfigured && writeBackEnabled && (
          <Chip
            icon={<SyncIcon fontSize="small" />}
            label="Write-back enabled"
            color="info"
            size="small"
            aria-label="HubSpot write-back is enabled"
          />
        )}

        {isConfigured && !writeBackEnabled && (
          <Chip
            icon={<LockIcon fontSize="small" />}
            label="Read-Only Mode"
            color="success"
            size="small"
            aria-label="HubSpot connection is read-only"
          />
        )}

        {/* Review Queue badge (Req 9.1, 13.6) */}
        {pendingCount > 0 && (
          <Tooltip title={`${pendingCount} pending review queue items`}>
            <Badge badgeContent={pendingCount} color="warning" max={999}>
              <Chip
                icon={<RateReviewIcon fontSize="small" />}
                label="Review Queue"
                variant="outlined"
                size="small"
                aria-label={`Review queue has ${pendingCount} pending items`}
              />
            </Badge>
          </Tooltip>
        )}
      </Box>

      {/* ── Section 1: Connection Config ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="config-section-heading">
        <Typography variant="h6" id="config-section-heading" gutterBottom>
          Connection Configuration
        </Typography>

        {configLoading && <CircularProgress size={20} sx={{ mb: 2 }} />}
        {configError && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Could not load existing config. You can still save a new token.
          </Alert>
        )}

        {isConfigured && (
          <Box sx={{ mb: 2, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {config?.account_name && (
              <Chip label={`Account: ${config.account_name}`} size="small" />
            )}
            {config?.portal_id && (
              <Chip label={`Portal ID: ${config.portal_id}`} size="small" />
            )}
          </Box>
        )}

        {writeBackEnabled && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Quick Add pushes new leads to HubSpot as deals at Skip Trace. Your Private App
            token must include the <strong>crm.objects.deals.write</strong> scope. Set{' '}
            <code>HUBSPOT_WRITE_BACK_ENABLED=true</code> in the server environment.
          </Alert>
        )}

        <Box
          component="form"
          onSubmit={(e) => {
            e.preventDefault()
            saveConfigMutation.mutate()
          }}
          sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
          aria-label="HubSpot connection configuration form"
        >
          <TextField
            label="HubSpot Private App Token"
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            size="small"
            fullWidth
            autoComplete="new-password"
            inputProps={{ 'aria-label': 'HubSpot private app token' }}
          />
          <TextField
            label="Portal ID (optional)"
            value={portalIdInput}
            onChange={(e) => setPortalIdInput(e.target.value)}
            size="small"
            sx={{ maxWidth: 240 }}
            inputProps={{ 'aria-label': 'HubSpot portal ID' }}
          />

          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Button
              type="submit"
              variant="contained"
              disabled={!tokenInput || saveConfigMutation.isPending}
              startIcon={
                saveConfigMutation.isPending ? (
                  <CircularProgress size={16} color="inherit" />
                ) : undefined
              }
            >
              {saveConfigMutation.isPending ? 'Saving…' : 'Save Token'}
            </Button>

            <Button
              variant="outlined"
              onClick={() => testConnectionMutation.mutate()}
              disabled={testConnectionMutation.isPending || !isConfigured}
              startIcon={
                testConnectionMutation.isPending ? (
                  <CircularProgress size={16} color="inherit" />
                ) : undefined
              }
            >
              {testConnectionMutation.isPending ? 'Testing…' : 'Test Connection'}
            </Button>
          </Box>

          {saveConfigMutation.isSuccess && (
            <Alert severity="success" icon={<CheckCircleOutlineIcon />}>
              Token saved successfully.
            </Alert>
          )}
          {saveConfigMutation.isError && (
            <Alert severity="error" icon={<ErrorOutlineIcon />}>
              {(saveConfigMutation.error as Error).message}
            </Alert>
          )}

          {/* Test connection result (Req 6.3, 6.4) */}
          {testResult && (
            <Alert
              severity={testResult.success ? 'success' : 'error'}
              icon={
                testResult.success ? (
                  <CheckCircleOutlineIcon />
                ) : (
                  <ErrorOutlineIcon />
                )
              }
            >
              {testResult.success ? (
                <>
                  Connected — <strong>{testResult.account_name}</strong>
                  {testResult.portal_id && ` (Portal ${testResult.portal_id})`}
                </>
              ) : (
                testResult.error || 'Connection failed'
              )}
            </Alert>
          )}
        </Box>
      </Paper>

      {/* ── Section 2: Import Trigger ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="import-trigger-heading">
        <Typography variant="h6" id="import-trigger-heading" gutterBottom>
          Start Import
        </Typography>

        <FormGroup row sx={{ mb: 2 }} aria-label="Object types to import">
          {OBJECT_TYPES.map((type) => (
            <FormControlLabel
              key={type}
              control={
                <Checkbox
                  checked={selectedTypes[type]}
                  onChange={(e) =>
                    setSelectedTypes((prev) => ({ ...prev, [type]: e.target.checked }))
                  }
                  disabled={triggerImportMutation.isPending || !!activeRunId}
                />
              }
              label={type.charAt(0).toUpperCase() + type.slice(1)}
            />
          ))}
        </FormGroup>

        <Button
          variant="contained"
          color="primary"
          startIcon={
            triggerImportMutation.isPending ? (
              <CircularProgress size={16} color="inherit" />
            ) : (
              <PlayArrowIcon />
            )
          }
          onClick={() => triggerImportMutation.mutate()}
          disabled={
            triggerImportMutation.isPending ||
            !!activeRunId ||
            !isConfigured ||
            !OBJECT_TYPES.some((t) => selectedTypes[t])
          }
          aria-label="Start HubSpot import"
        >
          {triggerImportMutation.isPending ? 'Starting…' : 'Start Import'}
        </Button>

        {!isConfigured && (
          <Typography variant="caption" color="text.secondary" sx={{ ml: 2 }}>
            Save a token first to enable import.
          </Typography>
        )}

        {importError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {importError}
          </Alert>
        )}

        {/* SSE-driven progress (Req 7.7, 7.8) */}
        {Object.keys(progress).length > 0 && (
          <Box sx={{ mt: 3 }}>
            <Typography variant="subtitle2" gutterBottom>
              Import Progress
            </Typography>
            {Object.entries(progress).map(([type, evt]) => {
              const pct =
                evt.percent ??
                (evt.total_fetched > 0
                  ? Math.min(
                      100,
                      Math.round(
                        ((evt.created_count + evt.updated_count + evt.error_count) /
                          evt.total_fetched) *
                          100
                      )
                    )
                  : 0)
              return (
                <Box key={type} sx={{ mb: 1.5 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                    <Typography variant="body2">
                      {type.charAt(0).toUpperCase() + type.slice(1)}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <Chip
                        label={evt.status}
                        color={statusColor(evt.status)}
                        size="small"
                      />
                      <Typography variant="caption" color="text.secondary">
                        {evt.created_count} new · {evt.updated_count} updated
                        {evt.error_count > 0 && ` · ${evt.error_count} errors`}
                      </Typography>
                    </Box>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={pct}
                    color={evt.status === 'failed' ? 'error' : 'primary'}
                    aria-label={`${type} import progress ${pct}%`}
                  />
                </Box>
              )
            })}
          </Box>
        )}
      </Paper>

      {/* ── Section 3: Import History ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="import-history-heading">
        <Typography variant="h6" id="import-history-heading" gutterBottom>
          Import History
        </Typography>

        {runsLoading && <CircularProgress size={20} />}
        {runsError && (
          <Alert severity="error">Failed to load import history.</Alert>
        )}

        {runsData && runsData.runs.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No import runs yet.
          </Typography>
        )}

        {runsData && runsData.runs.length > 0 && (
          <TableContainer>
            <Table size="small" aria-label="Import history table">
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>Object Type</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">Fetched</TableCell>
                  <TableCell align="right">Created</TableCell>
                  <TableCell align="right">Updated</TableCell>
                  <TableCell align="right">Errors</TableCell>
                  <TableCell>Started</TableCell>
                  <TableCell>Finished</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {runsData.runs.map((run: HubSpotImportRun) => (
                  <TableRow key={run.id} hover>
                    <TableCell>{run.id}</TableCell>
                    <TableCell>{run.object_type}</TableCell>
                    <TableCell>
                      <Chip
                        label={run.status}
                        color={statusColor(run.status)}
                        size="small"
                        aria-label={`Status: ${run.status}`}
                      />
                    </TableCell>
                    <TableCell align="right">{run.total_fetched.toLocaleString()}</TableCell>
                    <TableCell align="right">{run.created_count.toLocaleString()}</TableCell>
                    <TableCell align="right">{run.updated_count.toLocaleString()}</TableCell>
                    <TableCell align="right">
                      {run.error_count > 0 ? (
                        <Tooltip title={run.error_message || 'Errors occurred'}>
                          <Typography
                            variant="body2"
                            color="error"
                            component="span"
                          >
                            {run.error_count.toLocaleString()}
                          </Typography>
                        </Tooltip>
                      ) : (
                        run.error_count
                      )}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      {formatDateTime(run.start_time)}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>
                      {formatDateTime(run.end_time)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>

      {/* ── Section 4: Pipeline Status ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="pipeline-status-heading">
        <Typography variant="h6" id="pipeline-status-heading" gutterBottom>
          Post-Import Pipeline
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          After each import, matching, activity conversion, signal extraction, and lead rescoring run automatically.
          If the pipeline did not run after a previous import, use the button below to run it now.
        </Typography>

        <Button
          variant="outlined"
          size="small"
          sx={{ mb: 2 }}
          onClick={() => runPipelineMutation.mutate()}
          disabled={runPipelineMutation.isPending || pipelineStatus?.pipeline_running}
          startIcon={runPipelineMutation.isPending ? <CircularProgress size={14} color="inherit" /> : <PlayArrowIcon />}
          aria-label="Run post-import pipeline now"
        >
          {runPipelineMutation.isPending ? 'Queuing…' : 'Run Pipeline Now'}
        </Button>
        {runPipelineMutation.isSuccess && (
          <Alert severity="success" sx={{ mb: 2 }}>
            Pipeline queued — matching, signal extraction, and rescoring will run shortly.
          </Alert>
        )}

        {pipelineStatus && (
          <Box>
            {pipelineStatus.pipeline_running && (
              <Alert severity="info" sx={{ mb: 2 }} icon={<CircularProgress size={16} />}>
                Pipeline is running
                {pipelineStatus.pipeline_stage_label
                  ? ` — ${pipelineStatus.pipeline_stage_label}`
                  : ' — matching and enrichment in progress'}
                {pipelineStatus.pipeline_stage_index != null && pipelineStatus.pipeline_stage_total != null
                  ? ` (${pipelineStatus.pipeline_stage_index}/${pipelineStatus.pipeline_stage_total})`
                  : ''}
                .{' '}
                {user?.is_admin ? (
                  <MuiLink component={RouterLink} to="/admin/background-jobs" underline="hover">
                    View queue
                  </MuiLink>
                ) : (
                  'Background work is in progress.'
                )}
              </Alert>
            )}
            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
              <Chip
                label={`${pipelineStatus.matches.high} HIGH matches`}
                color={pipelineStatus.matches.high > 0 ? 'success' : 'default'}
                size="small"
              />
              <Chip
                label={`${pipelineStatus.matches.medium} MEDIUM matches`}
                color={pipelineStatus.matches.medium > 0 ? 'warning' : 'default'}
                size="small"
              />
              <Chip
                label={`${pipelineStatus.matches.unmatched} unmatched`}
                color={pipelineStatus.matches.unmatched > 0 ? 'error' : 'default'}
                size="small"
              />
              <Chip label={`${pipelineStatus.interactions} interactions`} size="small" />
              <Chip label={`${pipelineStatus.tasks} tasks`} size="small" />
              <Chip
                label={`${pipelineStatus.signals} signals`}
                color={pipelineStatus.signals > 0 ? 'primary' : 'default'}
                size="small"
              />
            </Box>
          </Box>
        )}
      </Paper>

      {/* ── Section 5: Backup Export ── */}
      <Paper sx={{ p: 3, mb: 3 }} aria-labelledby="backup-section-heading">
        <Typography variant="h6" id="backup-section-heading" gutterBottom>
          Backup Export
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Generate a full JSON backup of all imported HubSpot raw data. The
          download button becomes active once a backup has been generated.
        </Typography>

        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
          <Button
            variant="outlined"
            startIcon={
              backupMutation.isPending ? (
                <CircularProgress size={16} color="inherit" />
              ) : (
                <BackupIcon />
              )
            }
            onClick={() => backupMutation.mutate()}
            disabled={backupMutation.isPending || !isConfigured}
            aria-label="Generate backup export"
          >
            {backupMutation.isPending ? 'Generating…' : 'Generate Backup'}
          </Button>

          <Button
            variant="contained"
            startIcon={<CloudDownloadIcon />}
            onClick={handleDownloadBackup}
            disabled={!backupTaskId}
            aria-label="Download backup export"
          >
            Download Backup
          </Button>
        </Box>

        {backupMutation.isSuccess && (
          <Alert severity="success" sx={{ mt: 2 }}>
            Backup generation started. Task ID: {backupTaskId}
          </Alert>
        )}
        {backupError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {backupError}
          </Alert>
        )}
        {backupMutation.isError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {(backupMutation.error as Error).message}
          </Alert>
        )}
      </Paper>

      {/* ── Section 6: Webhook Sync ── */}
      <Box aria-labelledby="webhook-sync-section-heading">
        <Typography variant="h6" id="webhook-sync-section-heading" sx={{ mb: 2 }}>
          Webhook Sync
        </Typography>
        <WebhookSyncPanel
          hasClientSecret={config?.has_client_secret ?? false}
          onClientSecretSaved={() =>
            queryClient.invalidateQueries({ queryKey: ['hubspot', 'config'] })
          }
        />
      </Box>

      {/* Bottom spacer */}
      <Box sx={{ height: 32 }} />
    </Box>
  )
}

export default HubSpotImportArea
