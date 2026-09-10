/**
 * Soft prompt when a newer SPA build is live (post-deploy). Uses AppSnackbar —
 * not a yellow “restart required” strip.
 */
import { Button } from '@mui/material'
import { AppSnackbar } from '@/components/AppSnackbar'
import { useSpaVersionGuard } from '@/hooks/useSpaVersionGuard'

export function SpaUpdateSnackbar() {
  const { stale, reload, dismiss } = useSpaVersionGuard()

  return (
    <AppSnackbar
      open={stale}
      onClose={dismiss}
      severity="info"
      autoHideDuration={null}
      data-testid="spa-update-snackbar"
      alertTestId="spa-update-alert"
      message="A newer version of the app is available."
      action={
        <Button
          color="inherit"
          size="small"
          onClick={reload}
          data-testid="spa-update-reload"
        >
          Reload
        </Button>
      }
    />
  )
}
