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
import { extractUnitToken, formatUnitSuffix } from '@/utils/placesAddress'

export type PropertyAddressFields = {
  id?: number
  property_street?: string | null
  address_2?: string | null
  property_city?: string | null
  property_state?: string | null
  property_zip?: string | null
}

export interface PropertyAddressEditDialogProps {
  open: boolean
  /** Lead / queue row with current situs fields (id optional for tests). */
  row: PropertyAddressFields | null
  onClose: () => void
  onSave: (data: {
    property_street: string
    address_2: string | null
    property_city: string
    property_state: string
    property_zip: string
  }) => Promise<void>
  /** Primary button label — queue flow previews a match; CC just saves. */
  saveLabel?: string
}

/** Peel a trailing apt/unit off street into address line 2 when line 2 is empty. */
export function splitStreetAndAddress2(
  street: string | null | undefined,
  address2: string | null | undefined,
): { street: string; address2: string } {
  const line2 = (address2 || '').trim()
  const raw = (street || '').trim()
  if (!raw) return { street: '', address2: line2 }
  if (line2) return { street: raw, address2: line2 }

  const token = extractUnitToken(raw)
  if (!token) return { street: raw, address2: '' }

  // Strip the matched unit suffix from the street for the line-1 field.
  const stripped = raw
    .replace(
      /(?:\s+(?:unit|apt|apartment|suite|ste|fl|floor)\s*[#.]?\s*[a-z0-9-]+|\s+#[\s]*[a-z0-9-]+|\s+(?:[a-z]\d+[a-z0-9-]*|\d+[a-z][a-z0-9-]*))\s*$/i,
      '',
    )
    .trim()
  if (!stripped || stripped === raw) {
    return { street: raw, address2: formatUnitSuffix(token) }
  }
  return { street: stripped, address2: formatUnitSuffix(token) }
}

export function PropertyAddressEditDialog({
  open,
  row,
  onClose,
  onSave,
  saveLabel = 'Save and preview',
}: PropertyAddressEditDialogProps) {
  const [street, setStreet] = useState('')
  const [address2, setAddress2] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [zip, setZip] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || !row) return
    const split = splitStreetAndAddress2(row.property_street, row.address_2)
    setStreet(split.street)
    setAddress2(split.address2)
    setCity(row.property_city ?? '')
    setState(row.property_state ?? 'IL')
    setZip(row.property_zip ?? '')
    setError(null)
    setSaving(false)
  }, [
    open,
    row?.id,
    row?.property_street,
    row?.address_2,
    row?.property_city,
    row?.property_state,
    row?.property_zip,
  ])

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
        address_2: address2.trim() || null,
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
          inputProps={{ 'data-testid': 'property-address-street-input' }}
        />
        <TextField
          label="Address line 2"
          value={address2}
          onChange={(e) => setAddress2(e.target.value)}
          fullWidth
          margin="dense"
          placeholder="Apt / Unit / Suite"
          helperText="Apartment or condo unit (e.g. Unit L2, Apt 3)."
          inputProps={{ 'data-testid': 'property-address-line2-input' }}
        />
        <TextField
          label="City"
          value={city}
          onChange={(e) => setCity(e.target.value)}
          fullWidth
          margin="dense"
          inputProps={{ 'data-testid': 'property-address-city-input' }}
        />
        <TextField
          label="State"
          value={state}
          onChange={(e) => setState(e.target.value.toUpperCase())}
          fullWidth
          margin="dense"
          inputProps={{ maxLength: 2, 'data-testid': 'property-address-state-input' }}
        />
        <TextField
          label="ZIP"
          value={zip}
          onChange={(e) => setZip(e.target.value.replace(/[^\d-]/g, ''))}
          fullWidth
          margin="dense"
          inputProps={{ maxLength: 10, 'data-testid': 'property-address-zip-input' }}
        />
        {error && <Alert severity="error" sx={{ mt: 1 }}>{error}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>Cancel</Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={saving}
          data-testid="property-address-save"
        >
          {saving ? 'Saving…' : saveLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default PropertyAddressEditDialog
