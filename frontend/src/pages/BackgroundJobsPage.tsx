/**
 * Admin Background Jobs — live Celery queue + HubSpot pipeline stage + mail in-flight.
 */
import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  LinearProgress,
  Link as MuiLink,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  adminService,
  type CeleryTaskSummary,
} from '@/services/adminApi'
import openLetterService from '@/services/openLetterApi'

function TaskTable({ title, tasks }: { title: string; tasks: CeleryTaskSummary[] }) {
  if (tasks.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {title}: none
      </Typography>
    )
  }
  return (
    <Paper variant="outlined" sx={{ mb: 2 }} data-testid={`bg-jobs-${title.toLowerCase().replace(/\s+/g, '-')}`}>
      <Box sx={{ px: 2, pt: 1.5, pb: 1 }}>
        <Typography variant="subtitle1" fontWeight={600}>
          {title} ({tasks.length})
        </Typography>
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Task</TableCell>
            <TableCell>State</TableCell>
            <TableCell>Worker</TableCell>
            <TableCell>Id</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {tasks.map((t, idx) => (
            <TableRow
              key={`${t.id ?? t.name}-${idx}`}
              sx={{
                bgcolor: t.is_mail_submit
                  ? 'action.selected'
                  : t.is_hubspot_pipeline
                    ? 'action.hover'
                    : undefined,
              }}
            >
              <TableCell>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="body2" fontFamily="monospace">
                    {t.name}
                  </Typography>
                  {t.is_mail_submit && <Chip size="small" color="primary" label="Direct mail" />}
                  {t.is_hubspot_pipeline && <Chip size="small" color="secondary" label="HubSpot pipeline" />}
                </Stack>
              </TableCell>
              <TableCell>{t.state}</TableCell>
              <TableCell>{t.worker ?? '—'}</TableCell>
              <TableCell>
                <Typography variant="caption" fontFamily="monospace">
                  {t.id ?? '—'}
                </Typography>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Paper>
  )
}

export default function BackgroundJobsPage() {
  const queryClient = useQueryClient()
  const [redispatchError, setRedispatchError] = useState<string | null>(null)
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ['admin', 'background-jobs'],
    queryFn: () => adminService.getBackgroundJobs(),
    refetchInterval: (query) => (query.state.data?.busy ? 5_000 : 30_000),
  })

  const redispatchMutation = useMutation({
    mutationFn: (campaignId: number) => openLetterService.redispatchCampaign(campaignId),
    onSuccess: () => {
      setRedispatchError(null)
      void queryClient.invalidateQueries({ queryKey: ['admin', 'background-jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['mail-campaigns'] })
    },
    onError: (err: Error) => setRedispatchError(err.message),
  })

  const upNext = useMemo(() => {
    if (!data) return []
    return [...data.reserved, ...data.scheduled, ...data.queued]
  }, [data])

  const pipeline = data?.hubspot_pipeline
  const stagePct =
    pipeline && pipeline.stage_total > 0 && pipeline.stage_index > 0
      ? Math.min(100, (pipeline.stage_index / pipeline.stage_total) * 100)
      : 0
  const orphanCampaigns = (data?.mail_campaigns_in_flight ?? []).filter(
    (c) => c.orphan && c.status === 'pending',
  )

  return (
    <Box sx={{ p: { xs: 2, md: 3 }, maxWidth: 1100 }} data-testid="background-jobs-page">
      <Typography variant="h5" gutterBottom>
        Background Jobs
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Live Celery worker queue — what is running, HubSpot post-import stage, and where direct-mail
        submit sits in line.
        {isFetching && !isLoading ? ' Refreshing…' : null}
      </Typography>

      {isLoading && <LinearProgress sx={{ mb: 2 }} />}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(error as Error).message || 'Failed to load background jobs'}
        </Alert>
      )}

      {data && !data.celery_inspect_ok && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Celery inspect did not respond — showing broker queue peek only. Worker may be busy or
          unreachable.
        </Alert>
      )}

      {data && !data.busy && (
        <Alert severity="success" sx={{ mb: 2 }} data-testid="bg-jobs-idle">
          No background jobs — Celery is idle.
        </Alert>
      )}

      {pipeline?.pipeline_running && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }} data-testid="bg-jobs-hubspot-stage">
          <Typography variant="subtitle1" fontWeight={600} gutterBottom>
            HubSpot post-import pipeline
          </Typography>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {pipeline.label}
            {pipeline.stage_index > 0
              ? ` (step ${pipeline.stage_index} of ${pipeline.stage_total})`
              : null}
          </Typography>
          <LinearProgress variant="determinate" value={stagePct} sx={{ height: 8, borderRadius: 1 }} />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            Also visible on{' '}
            <MuiLink component={RouterLink} to="/import/hubspot">
              HubSpot Import
            </MuiLink>
            .
          </Typography>
        </Paper>
      )}

      {data && (
        <>
          <TaskTable title="Now running" tasks={data.active} />
          <TaskTable title="Up next" tasks={upNext} />
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Broker queue depth: {data.queue_depth}
          </Typography>

          <Paper variant="outlined" sx={{ p: 2 }} data-testid="bg-jobs-mail-campaigns">
            <Typography variant="subtitle1" fontWeight={600} gutterBottom>
              Mail batches waiting
            </Typography>
            {orphanCampaigns.length > 0 && (
              <Alert severity="warning" sx={{ mb: 2 }} data-testid="bg-jobs-mail-orphan">
                {orphanCampaigns.length} campaign
                {orphanCampaigns.length === 1 ? '' : 's'} marked pending in the database but not
                found in the Celery queue (stale / orphaned). Re-queue to submit again.
              </Alert>
            )}
            {redispatchError && (
              <Alert severity="error" sx={{ mb: 2 }} onClose={() => setRedispatchError(null)}>
                {redispatchError}
              </Alert>
            )}
            {data.mail_campaigns_in_flight.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No pending/processing campaigns.
              </Typography>
            ) : (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Campaign</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Leads</TableCell>
                    <TableCell>Created</TableCell>
                    <TableCell align="right">Action</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data.mail_campaigns_in_flight.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <MuiLink component={RouterLink} to="/queues/ready-to-mail">
                          #{c.id}
                        </MuiLink>
                        {c.orphan && (
                          <Chip size="small" color="warning" label="Orphaned" sx={{ ml: 1 }} />
                        )}
                      </TableCell>
                      <TableCell>{c.status}</TableCell>
                      <TableCell>{c.lead_count}</TableCell>
                      <TableCell>{c.created_at ?? '—'}</TableCell>
                      <TableCell align="right">
                        {c.orphan && c.status === 'pending' && data.celery_inspect_ok && (
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={redispatchMutation.isPending}
                            onClick={() => redispatchMutation.mutate(c.id)}
                          >
                            Re-queue
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Paper>
        </>
      )}
    </Box>
  )
}
