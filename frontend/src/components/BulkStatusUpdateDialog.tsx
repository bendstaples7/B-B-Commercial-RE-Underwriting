import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
} from '@mui/material'
import type { LeadStatus } from '@/types'
import { LEAD_STATUS_LABELS } from '@/components/LeadStatusChip'

export interface BulkStatusUpdateDialogProps {
  open: boolean
  selectedCount: number
  allStatuses: LeadStatus[]
  defaultStatus?: LeadStatus | null
  onClose: () => void
  onConfirm: (status: LeadStatus, reason: string) => Promise<void>
}

export function BulkStatusUpdateDialog({
  open,
  selectedCount,
  allStatuses,
  defaultStatus = null,
  onClose,
  onConfirm,
}: BulkStatusUpdateDialogProps) {
  const [status, setStatus] = useState<LeadStatus>(defaultStatus ?? allStatuses[0])
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setStatus(defaultStatus ?? allStatuses[0])
    setReason('')
    setError(null)
    setSubmitting(false)
  }, [open, defaultStatus, allStatuses])

  const handleConfirm = async () => {
    setSubmitting(true)
    setError(null)
    try {
      await onConfirm(status, reason.trim())
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk status update failed')
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} data-testid="bulk-status-dialog">
      <DialogTitle>Update status for {selectedCount} lead{selectedCount === 1 ? '' : 's'}</DialogTitle>
      <DialogContent>
        <DialogContentText sx={{ mb: 2 }}>
          Choose a new pipeline status. Each lead will get a timeline entry and updated recommended action.
        </DialogContentText>
        <FormControl fullWidth size="small" sx={{ mb: 2 }}>
          <InputLabel>New status</InputLabel>
          <Select
            value={status}
            label="New status"
            onChange={(e) => setStatus(e.target.value as LeadStatus)}
          >
            {allStatuses.map((s) => (
              <MenuItem key={s} value={s}>{LEAD_STATUS_LABELS[s] ?? s}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <TextField
          label="Reason (optional)"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          fullWidth
          size="small"
          multiline
          minRows={2}
        />
        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>Cancel</Button>
        <Button onClick={handleConfirm} variant="contained" disabled={submitting}>
          {submitting ? 'Updating…' : 'Update status'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default BulkStatusUpdateDialog
