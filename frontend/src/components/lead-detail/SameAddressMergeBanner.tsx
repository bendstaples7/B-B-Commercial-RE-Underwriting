/**
 * Same-address duplicate banner + pick-who-stays merge dialog.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  FormLabel,
  Radio,
  RadioGroup,
  TextField,
  Typography,
} from '@mui/material'
import { commandCenterService } from '@/services/api'
import type { SameAddressLeadSummary } from '@/types'

export type SameAddressMergedPayload = {
  winnerId: number
  loserId: number
}

export interface SameAddressMergeBannerProps {
  leadId: number
  twins: SameAddressLeadSummary[]
  currentOwnerLabel: string
  currentPeopleNames: string[]
  /**
   * Required: refresh Command Center after merge (same-URL navigate alone is a
   * no-op). Prefer afterCommandCenterMutation via UnifiedLeadCommandCenter.
   */
  onMerged: (payload: SameAddressMergedPayload) => void | Promise<void>
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
  onMerged,
}: SameAddressMergeBannerProps) {
  const [open, setOpen] = useState(false)
  const [winnerId, setWinnerId] = useState<number>(leadId)
  const [removeId, setRemoveId] = useState<number | null>(null)
  const [pasteId, setPasteId] = useState('')
  const [pastePreview, setPastePreview] = useState<SameAddressLeadSummary | null>(null)
  const [pasteError, setPasteError] = useState<string | null>(null)
  const [pasteLookupPending, setPasteLookupPending] = useState(false)
  const [validatedPasteId, setValidatedPasteId] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const removeIdRef = useRef<number | null>(null)
  const pasteIdRef = useRef('')
  const pasteLookupPromise = useRef<Promise<boolean> | null>(null)

  const selectRemoveId = useCallback((nextRemoveId: number | null) => {
    removeIdRef.current = nextRemoveId
    setRemoveId(nextRemoveId)
  }, [])

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

  const resetDialogState = useCallback(() => {
    setWinnerId(leadId)
    setError(null)
    setPasteId('')
    pasteIdRef.current = ''
    setPastePreview(null)
    setPasteError(null)
    setValidatedPasteId('')
    setPasteLookupPending(false)
    pasteLookupPromise.current = null
    selectRemoveId(first?.id ?? null)
  }, [first?.id, leadId, selectRemoveId])

  useEffect(() => {
    if (!open) return
    resetDialogState()
  }, [open, resetDialogState])

  const closeDialog = useCallback(() => {
    if (saving) return
    setOpen(false)
    // Clear paste/manual twin state on close so cancel + reopen cannot keep
    // a stale lead id if open→true is coalesced before open flips false.
    resetDialogState()
  }, [resetDialogState, saving])

  useEffect(() => {
    if (removeId != null && removable.some((row) => row.id === removeId)) return
    selectRemoveId(removable[0]?.id ?? null)
  }, [removable, removeId, selectRemoveId])

  const validatePasteId = async (): Promise<boolean> => {
    if (pasteLookupPromise.current) return pasteLookupPromise.current
    const raw = pasteId.trim()
    if (!raw) {
      setPastePreview(null)
      setPasteError(null)
      setValidatedPasteId('')
      return true
    }
    const parsed = Number(raw)
    if (!Number.isInteger(parsed) || parsed <= 0 || parsed === leadId) {
      setPasteError('Enter a different lead number.')
      setPastePreview(null)
      setValidatedPasteId('')
      return false
    }
    const lookup = (async () => {
      setPasteLookupPending(true)
      try {
        const preview = await commandCenterService.getMergePreview(leadId, parsed)
        if (pasteIdRef.current.trim() !== raw) {
          setValidatedPasteId('')
          return false
        }
        if (!preview.same_building) {
          setPasteError('That record is not the same address.')
          setPastePreview(null)
          setValidatedPasteId('')
          return false
        }
        setPasteError(null)
        setPastePreview(preview.other)
        setValidatedPasteId(raw)
        selectRemoveId(preview.other.id)
        return true
      } catch (err) {
        if (pasteIdRef.current.trim() !== raw) {
          setValidatedPasteId('')
          return false
        }
        setPasteError(err instanceof Error ? err.message : 'Could not look up that lead.')
        setPastePreview(null)
        setValidatedPasteId('')
        return false
      } finally {
        setPasteLookupPending(false)
        pasteLookupPromise.current = null
      }
    })()
    pasteLookupPromise.current = lookup
    return lookup
  }

  const handleWinnerChange = (nextWinnerId: number) => {
    setWinnerId(nextWinnerId)
    if (removeId === nextWinnerId) {
      selectRemoveId(options.find((row) => row.id !== nextWinnerId)?.id ?? null)
    }
  }

  const handleMerge = async () => {
    const rawPasteId = pasteId.trim()
    if (rawPasteId && rawPasteId !== validatedPasteId) {
      const validPaste = await validatePasteId()
      if (!validPaste) return
    } else if (pasteLookupPromise.current) {
      const validPaste = await pasteLookupPromise.current
      if (!validPaste) return
    }
    const stayId = winnerId
    const otherId = removeIdRef.current
    if (!otherId || otherId === stayId) {
      setError('Pick which record stays, and which one to remove.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const result = await commandCenterService.mergeInto(otherId, stayId)
      const mergedLoserId =
        typeof result.loser_id === 'number' && result.loser_id > 0
          ? result.loser_id
          : otherId
      // Merge already committed — refresh is best-effort so a failed invalidate
      // does not look like a failed combine.
      try {
        await onMerged({
          winnerId: result.winner_id,
          loserId: mergedLoserId,
        })
      } catch {
        // Swallow: merge already committed; parent-owned feedback reports success.
      }
      setOpen(false)
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
        onClose={closeDialog}
        aria-labelledby="same-address-merge-title"
        fullWidth
        maxWidth="sm"
        data-testid="same-address-merge-dialog"
        PaperProps={{ sx: { cursor: 'auto' } }}
      >
        <DialogTitle id="same-address-merge-title">Combine these records</DialogTitle>
        <DialogContent sx={{ cursor: 'auto' }}>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            Pick which lead stays. The other one is removed. Every person is kept;
            if two rows are the same person they become one person with all phone numbers.
          </Typography>
          <FormControl component="fieldset">
            <FormLabel id="same-address-merge-stay-label" sx={{ mb: 0.5 }}>
              Stay
            </FormLabel>
            <RadioGroup
              aria-labelledby="same-address-merge-stay-label"
              value={String(winnerId)}
              onChange={(event) => handleWinnerChange(Number(event.target.value))}
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
            <FormControl component="fieldset" sx={{ mt: 1.5, display: 'block' }}>
              <FormLabel id="same-address-merge-remove-label" sx={{ mb: 0.5 }}>
                Remove
              </FormLabel>
              <RadioGroup
                aria-labelledby="same-address-merge-remove-label"
                value={removeId != null ? String(removeId) : ''}
                onChange={(event) => selectRemoveId(Number(event.target.value))}
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
            onChange={(event) => {
              pasteIdRef.current = event.target.value
              setPasteId(event.target.value)
              setPastePreview(null)
              setPasteError(null)
              setValidatedPasteId('')
            }}
            onBlur={() => {
              void validatePasteId()
            }}
            error={Boolean(pasteError)}
            helperText={pasteLookupPending ? 'Checking lead...' : (pasteError ?? undefined)}
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
          <Button onClick={closeDialog} disabled={saving} sx={{ cursor: 'pointer' }}>
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
    </>
  )
}

export default SameAddressMergeBanner
