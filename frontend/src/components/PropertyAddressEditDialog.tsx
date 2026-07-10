import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
} from '@mui/material'
import type { QueueRow } from '@/types'

export interface PropertyAddressEditDialogProps {
  open: boolean
  row: QueueRow | null
  onClose: () => void
  onSave: (data: {
    property_street: string
    property_city: string
    property_state: string
    property_zip: string
  }) => Promise<void>
}

export function PropertyAddressEditDialog({
  open,
  row,
  onClose,
  onSave,
}: PropertyAddressEditDialogProps) {
  const [street, setStreet] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [zip, setZip] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !row) return
    setStreet(row.property_street ?? '')
    setCity(row.property_city ?? '')
    setState(row.property_state ?? 'IL')
    setZip(row.property_zip ?? '')
    setError(null)
    setSaving(false)
  }, [open, row?.id])

  const handleSave = async () => {
    if (!street.trim()) {
      setError('Street address is required.')
      return
    }
    const normalizedState = state.trim().toUpperCase()
    if (!/^[A-Z]{2}$/.test(normalizedState)) {
      setError('State must be a two-letter code (e.g. IL).')
      return
    }
    let normalizedZip = zip.trim()
    if (/^\d{9}$/.test(normalizedZip)) {
      normalizedZip = `${normalizedZip.slice(0, 5)}-${normalizedZip.slice(5)}`
    }
    if (normalizedZip && !/^\d{5}(-\d{4})?$/.test(normalizedZip)) {
      setError('ZIP must be 5 digits or ZIP+4 (12345 or 12345-6789).')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSave({
        property_street: street.trim(),
        property_city: city.trim(),
        property_state: normalizedState,
        property_zip: normalizedZip,
      })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update address')
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} data-testid="property-address-edit-dialog">
      <DialogTitle>Edit property address</DialogTitle>
      <DialogContent>
        <TextField
          label="Street"
          value={street}
          onChange={(e) => setStreet(e.target.value)}
          fullWidth
          margin="dense"
          required
        />
        <TextField
          label="City"
          value={city}
          onChange={(e) => setCity(e.target.value)}
          fullWidth
          margin="dense"
        />
        <TextField
          label="State"
          value={state}
          onChange={(e) => setState(e.target.value.toUpperCase())}
          fullWidth
          margin="dense"
          inputProps={{ maxLength: 2 }}
        />
        <TextField
          label="ZIP"
          value={zip}
          onChange={(e) => setZip(e.target.value.replace(/[^\d-]/g, ''))}
          fullWidth
          margin="dense"
          inputProps={{ maxLength: 10 }}
        />
        {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>Cancel</Button>
        <Button onClick={handleSave} variant="contained" disabled={saving}>
          {saving ? 'Saving…' : 'Save and preview'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default PropertyAddressEditDialog
