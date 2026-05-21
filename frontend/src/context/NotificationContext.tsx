/**
 * Global notification context.
 *
 * Provides a fixed inline banner at the top of the viewport that any
 * component or the global MutationCache.onError handler can push messages to.
 *
 * Unlike a Snackbar, this banner:
 *   - Stays visible until the user dismisses it (no auto-hide)
 *   - Is spatially anchored to the top of the page, not floating over content
 *   - Is impossible to miss regardless of where the user is looking
 *
 * Usage:
 *   const { showError, showWarning, showSuccess } = useNotification()
 *   showError('Something went wrong')
 */
import { createContext, useContext, useState, useCallback, ReactNode } from 'react'
import { Alert, Box, Collapse, IconButton } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'

type Severity = 'error' | 'warning' | 'success' | 'info'

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

  const handleClose = () => setState((s) => ({ ...s, open: false }))

  return (
    <NotificationContext.Provider value={{ showError, showWarning, showSuccess, showInfo }}>
      {/* Fixed inline banner — sits below the AppBar, above all page content */}
      <Collapse in={state.open}>
        <Box
          sx={{
            position: 'sticky',
            top: 64, // AppBar height
            zIndex: 1200,
            width: '100%',
          }}
        >
          <Alert
            severity={state.severity}
            variant="filled"
            sx={{ borderRadius: 0 }}
            action={
              <IconButton
                size="small"
                color="inherit"
                onClick={handleClose}
                aria-label="Dismiss notification"
              >
                <CloseIcon fontSize="small" />
              </IconButton>
            }
          >
            {state.message}
          </Alert>
        </Box>
      </Collapse>
      {children}
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
}
