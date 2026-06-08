import React from "react";
import { useQuery } from '@tanstack/react-query'
import {
  Box,
  Typography,
  Paper,
  CircularProgress,
  Alert,
  List,
  ListItem,
  ListItemText,
  Divider,
  Chip,
} from '@mui/material'
import { hubSpotService } from '@/services/api'
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const formatDate = (dateStr: string | null | undefined): string => {
  if (!dateStr) return 'N/A'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return 'N/A'
  }
}
const ImportRunStatusChip: React.FC<{ status: string | null | undefined }> = ({ status }) => {
  let color: 'default' | 'primary' | 'success' | 'warning' | 'error' = 'default'
  switch ((status || '').toLowerCase()) {
    case 'completed':
      color = 'success'
      break
    case 'running':
    case 'processing':
      color = 'primary'
      break
    case 'failed':
      color = 'error'
      break
    case 'pending':
      color = 'warning'
      break
    default:
      color = 'default'
  }
  return <Chip label={status ?? 'unknown'} size='small' color={color} />
}
// ---------------------------------------------------------------------------
// SocialMediaPage Component
// ---------------------------------------------------------------------------
export function SocialMediaPage() {
  // Fetch HubSpot Import Runs
  const { data: importRuns, isLoading: isLoadingImports, isError: isErrorImports, error: errorImports } = useQuery({
    queryKey: ['hubspot', 'import-runs'],
    queryFn: () => hubSpotService.listImportRuns(1, 5), // Get last 5 import runs
  })
  // Marketing Lists — no real API available yet, show empty/coming-soon state
  return (
    <Box sx={{ px: { xs: 1, sm: 2 } }}>
      <Typography variant='h5' component='h1' fontWeight={600} mb={3}>
        Social Media & Engagement Summary
      </Typography>
      {/* HubSpot Import Activity */}
      <Paper elevation={1} sx={{ p: 3, mb: 4 }}>
        <Typography variant='h6' component='h2' fontWeight={500} mb={2}>
          HubSpot Import Activity
        </Typography>
        {isLoadingImports && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} aria-label='Loading HubSpot import activity' />
          </Box>
        )}
        {isErrorImports && (
          <Alert severity='error' sx={{ mb: 2 }}>
            {(errorImports as Error)?.message ?? 'Failed to load HubSpot import activity.'}
          </Alert>
        )}
        {!isLoadingImports && !isErrorImports && importRuns?.runs.length === 0 && (
          <Typography variant='body2' color='text.secondary'>
            No recent HubSpot import runs found.
          </Typography>
        )}
        {!isLoadingImports && !isErrorImports && importRuns && importRuns.runs.length > 0 && (
          <List dense>
            {importRuns.runs.map((run: any) => (
              <React.Fragment key={run.id}>
                <ListItem disablePadding>
                  <ListItemText
                    primary={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant='body2' fontWeight={500}>Import Run #{run.id}</Typography>
                        <ImportRunStatusChip status={run.status} />
                      </Box>
                    }
                    secondary={
                      <>
                        <Typography variant='caption' color='text.secondary' display='block'>
                          Started: {formatDate(run.started_at)}
                        </Typography>
                        {run.completed_at && (
                          <Typography variant='caption' color='text.secondary' display='block'>
                            Completed: {formatDate(run.completed_at)}
                          </Typography>
                        )}
                        {run.total_records_processed != null && (
                          <Typography variant='caption' color='text.secondary' display='block'>
                            Processed: {run.total_records_processed} records
                          </Typography>
                        )}
                        {run.successful_matches != null && (
                          <Typography variant='caption' color='text.secondary' display='block'>
                            Matches: {run.successful_matches}
                          </Typography>
                        )}
                        {run.errors && run.errors.length > 0 && (
                          <Typography variant='caption' color='error' display='block'>
                            Errors: {run.errors.length}
                          </Typography>
                        )}
                      </>
                    }
                  />
                </ListItem>
                <Divider component='li' light />
              </React.Fragment>
            ))}
          </List>
        )}
      </Paper>
      {/* Marketing Lists Summary — coming soon */}
      <Paper elevation={1} sx={{ p: 3 }}>
        <Typography variant='h6' component='h2' fontWeight={500} mb={2}>
          Marketing Lists
        </Typography>
        <Typography variant='body2' color='text.secondary'>
          Marketing lists integration coming soon.
        </Typography>
      </Paper>
    </Box>
  )
}
export default SocialMediaPage
