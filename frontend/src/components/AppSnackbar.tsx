/**
 * Canonical app toast — bottom-center, Fade, quick auto-dismiss for success/info.
 * Errors/warnings stay until dismissed (or clickaway is ignored for errors).
 */
import type { ReactNode, SyntheticEvent } from 'react'
import {
  Alert,
  Fade,
  Snackbar,
  type AlertColor,
  type AlertProps,
  type SnackbarCloseReason,
} from '@mui/material'

export const APP_TOAST_DURATION_MS = {
  default: 3000,
  error: 5000,
} as const

export const APP_TOAST_ANCHOR = {
  vertical: 'bottom' as const,
  horizontal: 'center' as const,
}

export function appToastDuration(severity?: AlertColor | null): number | null {
  if (severity === 'error' || severity === 'warning') {
    return null
  }
  return APP_TOAST_DURATION_MS.default
}

export type AppSnackbarProps = {
  open: boolean
  onClose: () => void
  message?: ReactNode
  severity?: AlertColor
  /** Plain message bar without Alert chrome (legacy sidebar-style). */
  plain?: boolean
  /** Override default duration; null = sticky until dismiss. */
  autoHideDuration?: number | null
  'data-testid'?: string
  action?: AlertProps['action']
  alertTestId?: string
}

export function AppSnackbar({
  open,
  onClose,
  message,
  severity = 'success',
  plain = false,
  autoHideDuration,
  'data-testid': dataTestId,
  action,
  alertTestId,
}: AppSnackbarProps) {
  const duration =
    autoHideDuration === undefined
      ? appToastDuration(severity)
      : autoHideDuration

  const handleClose = (
    _event?: Event | SyntheticEvent,
    reason?: SnackbarCloseReason,
  ) => {
    if (reason === 'clickaway' && (severity === 'error' || severity === 'warning')) {
      return
    }
    onClose()
  }

  return (
    <Snackbar
      open={open}
      autoHideDuration={duration}
      onClose={handleClose}
      anchorOrigin={APP_TOAST_ANCHOR}
      TransitionComponent={Fade}
      data-testid={dataTestId}
      {...(plain ? { message: message ?? '' } : {})}
    >
      {plain ? undefined : (
        <Alert
          severity={severity}
          onClose={onClose}
          action={action}
          sx={{ width: '100%' }}
          data-testid={alertTestId}
        >
          {message}
        </Alert>
      )}
    </Snackbar>
  )
}
