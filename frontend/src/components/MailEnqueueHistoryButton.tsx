import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
} from '@mui/material'
import openLetterService, {
  type MailEnqueueAttempt,
  type MailEnqueueAttemptSummary,
} from '@/services/openLetterApi'
import { MailEnqueueResultDialog } from './MailEnqueueResultDialog'

export function MailEnqueueHistoryButton() {
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<MailEnqueueAttempt | null>(null)
  const [detailLoadingId, setDetailLoadingId] = useState<number | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const detailRequestId = useRef(0)
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['mail-enqueue-attempts'],
    queryFn: () => openLetterService.listEnqueueAttempts(),
    enabled: open,
  })

  const openAttempt = async (attempt: MailEnqueueAttemptSummary) => {
    const requestId = ++detailRequestId.current
    setDetailError(null)
    setDetailLoadingId(attempt.id)
    try {
      const detail = await openLetterService.getEnqueueAttempt(attempt.id)
      if (requestId !== detailRequestId.current) return
      setSelected(detail)
      setOpen(false)
    } catch {
      if (requestId !== detailRequestId.current) return
      setDetailError('Could not load that mail attempt.')
    } finally {
      if (requestId === detailRequestId.current) {
        setDetailLoadingId(null)
      }
    }
  }

  const closeHistory = () => {
    detailRequestId.current += 1
    setDetailLoadingId(null)
    setOpen(false)
  }

  return (
    <>
      <Button size="small" variant="text" onClick={() => setOpen(true)}>
        Recent mail attempts
      </Button>
      <Dialog open={open} onClose={closeHistory} fullWidth maxWidth="sm">
        <DialogTitle>Recent direct mail attempts</DialogTitle>
        <DialogContent dividers>
          {isLoading ? (
            <CircularProgress
              size={24}
              aria-label="Loading recent mail attempts"
            />
          ) : isError ? (
            <Alert
              severity="error"
              action={<Button onClick={() => void refetch()}>Retry</Button>}
            >
              Could not load recent mail attempts.
            </Alert>
          ) : (data?.attempts.length ?? 0) === 0 ? (
            <Typography color="text.secondary">No direct mail attempts yet.</Typography>
          ) : (
            <>
              {detailError && <Alert severity="error">{detailError}</Alert>}
              <List disablePadding>
                {data?.attempts.map((attempt) => (
                  <ListItem key={attempt.id} disablePadding divider>
                    <ListItemButton
                      disabled={detailLoadingId !== null}
                      onClick={() => void openAttempt(attempt)}
                    >
                      <ListItemText
                        primary={`${attempt.added} staged · ${
                          attempt.invalid + attempt.skipped
                        } need attention`}
                        secondary={[
                          attempt.created_at
                            ? new Date(attempt.created_at).toLocaleString()
                            : null,
                          attempt.source_queue,
                        ].filter(Boolean).join(' · ')}
                      />
                      {detailLoadingId === attempt.id && (
                        <CircularProgress
                          size={18}
                          aria-label="Loading mail attempt details"
                        />
                      )}
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={closeHistory}>Close</Button>
        </DialogActions>
      </Dialog>
      <MailEnqueueResultDialog
        open={selected !== null}
        onClose={() => setSelected(null)}
        result={selected}
        title="Direct mail attempt"
      />
    </>
  )
}

export default MailEnqueueHistoryButton
