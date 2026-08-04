/**
 * DEV-only floating capture controls for live-UI visibility.
 * Writes session + Playwright screenshots under artifacts/live-ui/ via Vite middleware.
 */
import { useEffect, useState } from 'react'
import { Box, Button, Portal, Stack, Typography } from '@mui/material'
import { useAuth } from '@/context/AuthContext'
import { installBbLiveUiApi } from './liveUiCapture'

export function LiveUiCaptureHost() {
  const { user, isLoading } = useAuth()
  const [status, setStatus] = useState<string>('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    installBbLiveUiApi()
  }, [])

  if (isLoading || !user) return null

  const run = async (fn: () => Promise<{ ok: boolean; error?: string; report?: unknown }>, label: string) => {
    setBusy(true)
    setStatus(`${label}…`)
    try {
      const result = await fn()
      if (!result.ok) {
        setStatus(`${label} failed: ${result.error || 'unknown'}`)
      } else {
        const png =
          result.report && typeof result.report === 'object' && 'png' in result.report
            ? String((result.report as { png?: string }).png || '')
            : ''
        setStatus(png ? `${label} ok → ${png}` : `${label} ok`)
      }
    } catch (err) {
      setStatus(`${label} failed: ${String((err as Error)?.message || err)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Portal>
      <Box
        data-testid="live-ui-capture-fab"
        sx={{
          position: 'fixed',
          right: 16,
          bottom: 88,
          zIndex: 10000,
          cursor: 'auto',
          pointerEvents: 'auto',
          maxWidth: 360,
          p: 1,
          borderRadius: 1,
          bgcolor: 'rgba(15, 23, 42, 0.92)',
          color: '#F8FAFC',
          boxShadow: 3,
        }}
      >
        <Typography variant="caption" sx={{ display: 'block', mb: 0.5, fontWeight: 600 }}>
          Live-UI (dev)
        </Typography>
        <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
          <Button
            size="small"
            variant="contained"
            disabled={busy}
            onClick={() =>
              run(() => window.__bbLiveUi!.exportSession(), 'Export session')
            }
            sx={{ textTransform: 'none', cursor: 'pointer' }}
          >
            Export session
          </Button>
          <Button
            size="small"
            variant="outlined"
            disabled={busy}
            onClick={() =>
              run(
                () =>
                  window.__bbLiveUi!.capture({
                    selector: '[data-testid="property-overview-header"]',
                    label: 'cc-header',
                  }),
                'Capture header',
              )
            }
            sx={{
              textTransform: 'none',
              cursor: 'pointer',
              color: '#E2E8F0',
              borderColor: '#64748B',
            }}
          >
            Capture header
          </Button>
          <Button
            size="small"
            variant="outlined"
            disabled={busy}
            onClick={() =>
              run(
                () =>
                  window.__bbLiveUi!.capture({
                    selector: '[data-live-ui-surface], main, #root',
                    label: 'surface',
                  }),
                'Capture surface',
              )
            }
            sx={{
              textTransform: 'none',
              cursor: 'pointer',
              color: '#E2E8F0',
              borderColor: '#64748B',
            }}
          >
            Capture surface
          </Button>
        </Stack>
        {status ? (
          <Typography
            variant="caption"
            sx={{ display: 'block', mt: 0.75, wordBreak: 'break-word', opacity: 0.9 }}
          >
            {status}
          </Typography>
        ) : null}
      </Box>
    </Portal>
  )
}
