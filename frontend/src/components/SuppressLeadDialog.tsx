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
  return (
    <Dialog open={open} onClose={onClose} data-testid="suppress-confirm-dialog">
      <DialogTitle>Suppress Lead?</DialogTitle>
      <DialogContent>
        <DialogContentText>
          This will suppress the lead and remove it from active queues. Are you sure?
        </DialogContentText>
        {error && (
          <DialogContentText color="error" sx={{ mt: 1 }} data-testid="suppress-error">
            {error}
          </DialogContentText>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          onClick={onConfirm}
          color="error"
          variant="contained"
          data-testid="suppress-confirm-btn"
        >
          Suppress
        </Button>
      </DialogActions>
    </Dialog>
  )
}
