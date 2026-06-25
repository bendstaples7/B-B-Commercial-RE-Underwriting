import { useEffect, useState } from 'react'
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from '@mui/material'

export interface SuppressLeadDialogProps {
  open: boolean
  error?: string | null
  onClose: () => void
  onConfirm: () => void | Promise<void>
}

export function SuppressLeadDialog({
  open,
  error = null,
  onClose,
  onConfirm,
}: SuppressLeadDialogProps) {
  const [confirming, setConfirming] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setConfirming(false)
      setLocalError(null)
    }
  }, [open])

  const displayError = error ?? localError

  const handleConfirm = async () => {
    setConfirming(true)
    setLocalError(null)
    try {
      await onConfirm()
    } catch (err) {
      console.error('[SuppressLeadDialog] Suppress failed:', err)
      setLocalError(err instanceof Error ? err.message : 'Suppress failed. Please try again.')
      setConfirming(false)
    }
  }

  return (
    <Dialog open={open} onClose={confirming ? undefined : onClose} data-testid="suppress-confirm-dialog">
      <DialogTitle>Suppress Lead?</DialogTitle>
      <DialogContent>
        <DialogContentText>
          This will suppress the lead and remove it from active queues. Are you sure?
        </DialogContentText>
        {displayError && (
          <DialogContentText color="error" sx={{ mt: 1 }} data-testid="suppress-error">
            {displayError}
          </DialogContentText>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={confirming}>
          Cancel
        </Button>
        <Button
          onClick={handleConfirm}
          color="error"
          variant="contained"
          disabled={confirming}
          data-testid="suppress-confirm-btn"
        >
          {confirming ? 'Suppressing…' : 'Suppress'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
