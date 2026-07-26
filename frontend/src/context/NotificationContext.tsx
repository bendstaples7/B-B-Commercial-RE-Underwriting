/**
 * Global notification context — bottom-center Fade toasts (same as Ready to Mail).
 *
 * MutationCache.onError and any component can push messages via useNotification()
 * or globalNotify. Success/info toasts auto-dismiss with Fade; error/warning
 * toasts persist until the user dismisses them.
 */
import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import { AppSnackbar } from '@/components/AppSnackbar'
import type { AlertColor } from '@mui/material'


type Severity = AlertColor

interface BannerState {
  open: boolean
  message: string
  severity: Severity
}

interface NotificationContextValue {
  showError: (message: string) => void
  showWarning: (message: string) => void
  showSuccess: (message: string) => void
  showInfo: (message: string) => void
}

const NotificationContext = createContext<NotificationContextValue>({
  showError: () => {},
  showWarning: () => {},
  showSuccess: () => {},
  showInfo: () => {},
})

export function useNotification(): NotificationContextValue {
  return useContext(NotificationContext)
}

interface NotificationProviderProps {
  children: ReactNode
}

export function NotificationProvider({ children }: NotificationProviderProps) {
  const [state, setState] = useState<BannerState>({
    open: false,
    message: '',
    severity: 'error',
  })

  const show = useCallback((message: string, severity: Severity) => {
    setState({ open: true, message, severity })
  }, [])

  const showError = useCallback((message: string) => show(message, 'error'), [show])
  const showWarning = useCallback((message: string) => show(message, 'warning'), [show])
  const showSuccess = useCallback((message: string) => show(message, 'success'), [show])
  const showInfo = useCallback((message: string) => show(message, 'info'), [show])

  // Wire the singleton so MutationCache.onError (outside React) can call it
  globalNotify.showError = showError
  globalNotify.showWarning = showWarning
  globalNotify.showSuccess = showSuccess
  globalNotify.showInfo = showInfo

  const handleClose = () => setState((s) => ({ ...s, open: false }))

  return (
    <NotificationContext.Provider value={{ showError, showWarning, showSuccess, showInfo }}>
      {children}
      <AppSnackbar
        open={state.open}
        onClose={handleClose}
        message={state.message}
        severity={state.severity}
        data-testid="global-notification-snackbar"
      />
    </NotificationContext.Provider>
  )
}

/**
 * Singleton ref used by the MutationCache.onError handler in main.tsx.
 * The NotificationProvider sets this on mount so the global handler can
 * call it without needing React context.
 */
export const globalNotify = {
  showError: (_message: string) => {},
  showWarning: (_message: string) => {},
  showSuccess: (_message: string) => {},
  showInfo: (_message: string) => {},
}
