import { useQuery } from '@tanstack/react-query'
import {
  Box,
  Typography,
  Paper,
  CircularProgress,
  Alert,
  Grid,
} from '@mui/material'
import { hubSpotService } from '@/services/api'
import { TodaysActionQueue } from '@/components/TodaysActionQueue'

type PipelineStatus = {
  matches: { total: number };
  interactions: number;
  tasks: number;
  signals: number;
  pipeline_running: boolean;
};

function SocialMediaSummaryStats() {
  const { data: pipelineStatus, isLoading, isError, error } = useQuery<PipelineStatus>({
    queryKey: ['hubspot', 'pipeline-status'],
    queryFn: () => hubSpotService.getPipelineStatus(),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress size={24} aria-label='Loading social media summary' />
      </Box>
    )
  }

  if (isError) {
    return (
      <Alert severity='error' sx={{ mb: 2 }}>
        {(error as Error)?.message ?? 'Failed to load social media summary.'}
      </Alert>
    )
  }

  if (!pipelineStatus) {
    return (
      <Alert severity='info' sx={{ mb: 2 }}>
        No social media pipeline status available.
      </Alert>
    )
  }

  const { matches, interactions, tasks, signals } = pipelineStatus

  return (
    <Grid container spacing={2}>
      <Grid item xs={12}>
        <Typography variant='h6' gutterBottom>
          HubSpot Pipeline Status
        </Typography>
      </Grid>
      <Grid item xs={12} sm={6} md={3}>
        <Paper elevation={1} sx={{ p: 2, textAlign: 'center' }}>
          <Typography variant='h5' fontWeight={600}>{matches.total}</Typography>
          <Typography variant='body2' color='text.secondary'>Total Matches</Typography>
        </Paper>
      </Grid>
      <Grid item xs={12} sm={6} md={3}>
        <Paper elevation={1} sx={{ p: 2, textAlign: 'center' }}>
          <Typography variant='h5' fontWeight={600}>{interactions}</Typography>
          <Typography variant='body2' color='text.secondary'>Interactions</Typography>
        </Paper>
      </Grid>
      <Grid item xs={12} sm={6} md={3}>
        <Paper elevation={1} sx={{ p: 2, textAlign: 'center' }}>
          <Typography variant='h5' fontWeight={600}>{tasks}</Typography>
          <Typography variant='body2' color='text.secondary'>Tasks</Typography>
        </Paper>
      </Grid>
      <Grid item xs={12} sm={6} md={3}>
        <Paper elevation={1} sx={{ p: 2, textAlign: 'center' }}>
          <Typography variant='h5' fontWeight={600}>{signals}</Typography>
          <Typography variant='body2' color='text.secondary'>Signals</Typography>
        </Paper>
      </Grid>
      {pipelineStatus.pipeline_running && (
        <Grid item xs={12}>
          <Alert severity='info' icon={<CircularProgress size={18} />} sx={{ mt: 2 }}>
            HubSpot pipeline is currently running...
          </Alert>
        </Grid>
      )}
    </Grid>
  )
}

export function HomePage() {
  return (
    <Box sx={{ px: { xs: 1, sm: 2 } }}>
      <Typography variant='h4' component='h1' fontWeight={700} mb={4}>
        Deathclock Dashboard
      </Typography>

      <Grid container spacing={4}>
        <Grid item xs={12} md={8}>
          <Paper elevation={1} sx={{ p: 3 }}>
            <TodaysActionQueue extraQueryKeys={['queue-counts']} />
          </Paper>
        </Grid>
        <Grid item xs={12} md={4}>
          <Paper elevation={1} sx={{ p: 3 }}>
            <SocialMediaSummaryStats />
          </Paper>
        </Grid>
      </Grid>
    </Box>
  )
}

export default HomePage
