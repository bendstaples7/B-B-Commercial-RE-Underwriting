import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItemButton,
  ListItemText,
} from '@mui/material'

export interface PropertyMatchRejectDialogProps {
  open: boolean
  onClose: () => void
  onSkipTrace: () => void
  onEditAddress: () => void
  onResearchPin: () => void
}

export function PropertyMatchRejectDialog({
  open,
  onClose,
  onSkipTrace,
  onEditAddress,
  onResearchPin,
}: PropertyMatchRejectDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} data-testid="property-match-reject-dialog">
      <DialogTitle>Reject property match</DialogTitle>
      <DialogContent sx={{ pt: 0 }}>
        <List>
          <ListItemButton onClick={onSkipTrace} data-testid="reject-skip-trace">
            <ListItemText
              primary="Send to skip trace"
              secondary="Mark lead for skip tracing when the address does not match assessor records"
            />
          </ListItemButton>
          <ListItemButton onClick={onEditAddress} data-testid="reject-edit-address">
            <ListItemText
              primary="Edit address"
              secondary="Correct the entered address and preview a new match"
            />
          </ListItemButton>
          <ListItemButton onClick={onResearchPin} data-testid="reject-research-pin">
            <ListItemText
              primary="Research PIN"
              secondary="Create a task to research the missing PIN manually"
            />
          </ListItemButton>
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </Dialog>
  )
}

export default PropertyMatchRejectDialog
