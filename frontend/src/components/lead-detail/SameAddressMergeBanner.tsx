/**
 * Same-address duplicate banner + pick-who-stays merge dialog.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Radio,
  RadioGroup,
  TextField,
  Typography,
} from '@mui/material'
import { useNavigate } from 'react-router-dom'
import { commandCenterService } from '@/services/api'
import type { SameAddressLeadSummary } from '@/types'
import { AppSnackbar } from '@/components/AppSnackbar'

export interface SameAddressMergeBannerProps {
  leadId: number
  twins: SameAddressLeadSummary[]
  currentOwnerLabel: string
  currentPeopleNames: string[]
}

function peopleLine(names: string[]): string {
  if (!names.length) return 'No people listed'
  return names.join(', ')
}

export function SameAddressMergeBanner({
  leadId,
  twins,
  currentOwnerLabel,
  currentPeopleNames,
}: SameAddressMergeBannerProps) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [winnerId, setWinnerId] = useState<number>(leadId)
  const [removeId, setRemoveId] = useState<number | null>(null)
  const [pasteId, setPasteId] = useState('')
  const [pastePreview, setPastePreview] = useState<SameAddressLeadSummary | null>(null)
  const [pasteError, setPasteError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [snack, setSnack] = useState<string | null>(null)

  const first = twins[0]
  const extra = Math.max(0, twins.length - 1)
  const hasTwins = twins.length > 0

  const options = useMemo(() => {
    const rows: Array<{
      id: number
      owner_display_name: string
      people_names: string[]
    }> = [
      {
        id: leadId,
        owner_display_name: currentOwnerLabel || `Lead #${leadId}`,
        people_names: currentPeopleNames,
      },
      ...twins,
    ]
    if (pastePreview && !rows.some((row) => row.id === pastePreview.id)) {
      rows.push(pastePreview)
    }
    return rows
  }, [currentOwnerLabel, currentPeopleNames, leadId, pastePreview, twins])

  const removable = useMemo(
    () => options.filter((row) => row.id !== winnerId),
    [options, winnerId],
  )

  useEffect(() => {
    if (!open) return
    setWinnerId(leadId)
    setError(null)
    const defaultRemove = first?.id ?? pastePreview?.id ?? null
    setRemoveId(defaultRemove)
  }, [leadId, open, first?.id, pastePreview?.id])

  useEffect(() => {
    if (removeId != null && removable.some((row) => row.id === removeId)) return
    setRemoveId(removable[0]?.id ?? null)
  }, [removable, removeId])

  const handlePasteBlur = async () => {
    const raw = pasteId.trim()
    if (!raw) {
      setPastePreview(null)
      setPasteError(null)
      return
    }
    const parsed = Number(raw)
    if (!Number.isInteger(parsed) || parsed <= 0 || parsed === leadId) {
      setPasteError('Enter a different lead number.')
      setPastePreview(null)
      return
    }
    try {
      const preview = await commandCenterService.getMergePreview(leadId, parsed)
      if (!preview.same_building) {
        setPasteError('That record is not the same address.')
        setPastePreview(null)
        return
      }
      setPasteError(null)
      setPastePreview(preview.other)
      setRemoveId(preview.other.id)
    } catch (err) {
      setPasteError(err instanceof Error ? err.message : 'Could not look up that lead.')
      setPastePreview(null)
    }
  }

  const handleMerge = async () => {
    const stayId = winnerId
    const otherId =
      stayId === leadId
        ? removeId
        : leadId
    if (!otherId || otherId === stayId) {
      setError('Pick which record stays, and which one to remove.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const result = await commandCenterService.mergeInto(otherId, stayId)
      setOpen(false)
      setSnack('Records combined.')
      navigate(`/leads/${result.winner_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not combine those records.')
    } finally {
      setSaving(false)
    }
  }

  if (!hasTwins) return null

  const bannerDetail = extra
    ? `${first.owner_display_name} (#${first.id}) and ${extra} more`
    : `${first.owner_display_name} (#${first.id})`

  return (
    <>
      <Alert
        severity="info"
        data-testid="same-address-merge-banner"
        sx={{
          cursor: 'auto',
          py: 0.5,
          alignItems: 'center',
          '& .MuiAlert-message': { width: '100%', py: 0.25 },
        }}
      >
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 1,
            flexWrap: 'wrap',
          }}
        >
          <Typography variant="body2" sx={{ minWidth: 0 }}>
            Another record for this address: {bannerDetail}
          </Typography>
          <Button
            size="small"
            variant="contained"
            data-testid="same-address-merge-open"
            onClick={() => setOpen(true)}
            sx={{ cursor: 'pointer', flexShrink: 0 }}
          >
            Merge
          </Button>
        </Box>
      </Alert>

      <Dialog
        open={open}
        onClose={() => !saving && setOpen(false)}
        fullWidth
        maxWidth="sm"
        data-testid="same-address-merge-dialog"
        PaperProps={{ sx: { cursor: 'auto' } }}
      >
        <DialogTitle>Combine these records</DialogTitle>
        <DialogContent sx={{ cursor: 'auto' }}>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            Pick which lead stays. The other one is removed. Every person is kept;
            if two rows are the same person they become one person with all phone numbers.
          </Typography>
          <FormControl>
            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5 }}>
              Stay
            </Typography>
            <RadioGroup
              value={String(winnerId)}
              onChange={(event) => setWinnerId(Number(event.target.value))}
            >
              {options.map((row) => (
                <FormControlLabel
                  key={row.id}
                  value={String(row.id)}
                  control={<Radio data-testid={`same-address-merge-stay-${row.id}`} />}
                  label={
                    <Box>
                      <Typography variant="body2" fontWeight={600}>
                        {row.owner_display_name} (#{row.id})
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {peopleLine(row.people_names)}
                      </Typography>
                    </Box>
                  }
                />
              ))}
            </RadioGroup>
          </FormControl>
          {removable.length > 1 ? (
            <FormControl sx={{ mt: 1.5, display: 'block' }}>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5 }}>
                Remove
              </Typography>
              <RadioGroup
                value={removeId != null ? String(removeId) : ''}
                onChange={(event) => setRemoveId(Number(event.target.value))}
              >
                {removable.map((row) => (
                  <FormControlLabel
                    key={row.id}
                    value={String(row.id)}
                    control={<Radio data-testid={`same-address-merge-remove-${row.id}`} />}
                    label={
                      <Typography variant="body2">
                        {row.owner_display_name} (#{row.id})
                      </Typography>
                    }
                  />
                ))}
              </RadioGroup>
            </FormControl>
          ) : null}
          <TextField
            size="small"
            fullWidth
            label="Or paste another lead number"
            value={pasteId}
            onChange={(event) => setPasteId(event.target.value)}
            onBlur={() => {
              void handlePasteBlur()
            }}
            error={Boolean(pasteError)}
            helperText={pasteError ?? undefined}
            inputProps={{
              'data-testid': 'same-address-merge-paste-id',
              style: { cursor: 'text' },
            }}
            sx={{ mt: 1.5, caretColor: 'text.primary' }}
          />
          {error ? (
            <Typography color="error" variant="body2" sx={{ mt: 1 }} data-testid="same-address-merge-error">
              {error}
            </Typography>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)} disabled={saving} sx={{ cursor: 'pointer' }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={() => {
              void handleMerge()
            }}
            disabled={saving}
            data-testid="same-address-merge-confirm"
            sx={{ cursor: 'pointer' }}
          >
            Combine
          </Button>
        </DialogActions>
      </Dialog>
      <AppSnackbar
        open={Boolean(snack)}
        onClose={() => setSnack(null)}
        message={snack ?? ''}
      />
    </>
  )
}

export default SameAddressMergeBanner
