/**
 * Banner shown when /api/health reports source_stale (backend code changed
 * after the process started — common with use_reloader=False).
 */
import { Alert, AlertTitle } from '@mui/material'
import { useBackendRuntimeGuard } from '@/hooks/useBackendRuntimeGuard'

export function BackendRestartRequiredBanner() {
  const { sourceStale } = useBackendRuntimeGuard()

  if (!sourceStale) return null

  return (
    <Alert
      severity="warning"
      sx={{ mb: 2 }}
      data-testid="backend-restart-required-banner"
    >
      <AlertTitle>Backend restart required</AlertTitle>
      Backend Python files changed after this server process started, so you may
      be seeing stale API data. Stop the server and restart with{' '}
      <strong>python dev.py</strong> (preferred) or{' '}
      <strong>python run.py</strong> from <code>backend/</code>, then hard-refresh
      this page.
    </Alert>
  )
}
