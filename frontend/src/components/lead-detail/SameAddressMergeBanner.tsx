/**
 * Same-address duplicate banner + choose-primary merge dialog.
 *
 * Auto-detects same-building twins when the API returns them (blue banner).
 * Manual entry lives on Command Center header overflow (⋯ → Merge duplicate…);
 * open the dialog via controlled `open` / `onOpenChange` from that menu.
 * Dialog search supports name / address / lead #. Opening the dialog loads
 * property, source, portfolio, and activity context for each candidate.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  CircularProgress,
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
import { LEAD_STATUS_LABELS } from '@/components/LeadStatusChip'
import { commandCenterService, searchService } from '@/services/api'
import type { LeadStatus, SameAddressLeadSummary, SearchResultItem } from '@/types'
import { formatDate, formatPropertyTypeLabel, humanize } from '@/utils/formatters'

const SEARCH_DEBOUNCE_MS = 300

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
  /** Controlled dialog open (header ⋯ → Merge duplicate…). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Hide the auto-detect banner when a richer duplicate callout is already showing. */
  hideBanner?: boolean
}

function peopleLine(names: string[]): string {
  if (!names.length) return 'No people listed'
  return names.join(', ')
}

function statusLabel(status: string | null | undefined): string {
  if (!status) return ''
  if (Object.hasOwn(LEAD_STATUS_LABELS, status)) {
    return LEAD_STATUS_LABELS[status as LeadStatus]
  }
  return humanize(status)
}

function addressLine(row: SameAddressLeadSummary): string {
  const street = (row.property_street || '').trim()
  const locality = [row.property_city, row.property_state, row.property_zip]
    .map((part) => (part || '').trim())
    .filter(Boolean)
    .join(' ')
  if (street && locality) return `${street}, ${locality}`
  return street || locality || 'No address on file'
}

function sourceToken(raw: string): string {
  const key = raw.trim().toLowerCase()
  if (key === 'hubspot') return 'HubSpot'
  return humanize(raw)
}

function sourceLine(row: SameAddressLeadSummary): string {
  const bits: string[] = []
  const source = (row.source || '').trim()
  const deal = (row.deal_source || '').trim()
  const channel = (row.data_source || '').trim()
  const kind = (row.source_type || '').trim()
  if (source) bits.push(sourceToken(source))
  if (deal && deal.toLowerCase() !== source.toLowerCase()) bits.push(sourceToken(deal))
  if (channel) bits.push(sourceToken(channel))
  if (kind && kind.toLowerCase() !== channel.toLowerCase()) bits.push(sourceToken(kind))
  if (row.hubspot_confirmed) bits.push('HubSpot linked')
  else if (row.date_added_to_hubspot) bits.push('In HubSpot')
  return bits.length ? bits.join(' · ') : 'No source on file'
}

function propertyFactsLine(row: SameAddressLeadSummary): string {
  const bits: string[] = []
  const pin = (row.county_assessor_pin || '').trim()
  if (pin) bits.push(`PIN ${pin}`)
  const type = formatPropertyTypeLabel(row.property_type)
  if (type) bits.push(type)
  if (row.units != null && Number(row.units) > 0) {
    const units = Number(row.units)
    bits.push(`${units} unit${units === 1 ? '' : 's'}`)
  }
  const status = statusLabel(row.lead_status)
  if (status) bits.push(status)
  if (row.lead_score != null && !Number.isNaN(Number(row.lead_score))) {
    bits.push(`Score ${Math.round(Number(row.lead_score))}`)
  }
  return bits.join(' · ')
}

function activityLine(row: SameAddressLeadSummary): string {
  const activity = row.activity
  if (!activity) return ''
  const parts: string[] = []
  if (activity.total > 0) {
    parts.push(`${activity.total} total`)
    if (activity.calls) parts.push(`${activity.calls} call${activity.calls === 1 ? '' : 's'}`)
    if (activity.notes) parts.push(`${activity.notes} note${activity.notes === 1 ? '' : 's'}`)
    if (activity.emails) parts.push(`${activity.emails} email${activity.emails === 1 ? '' : 's'}`)
    if (activity.mail) parts.push(`${activity.mail} mail`)
  }
  const openTasks = row.open_task_count ?? 0
  if (openTasks) parts.push(`${openTasks} open task${openTasks === 1 ? '' : 's'}`)
  if (!parts.length) return 'Activities: none'
  let line = `Activities: ${parts.join(' · ')}`
  const last = (activity.last_summary || '').trim()
  if (last) {
    const when = activity.last_occurred_at ? formatDate(activity.last_occurred_at) : ''
    line += when && when !== '—' ? `. Last ${when}: ${last}` : `. Last: ${last}`
  }
  return line
}

function relatedLine(row: SameAddressLeadSummary): string {
  const related = row.related_properties
  if (!related) return ''
  if (!related.length) return 'Other properties: none'
  const labels = related.map((prop) => {
    const street = (prop.property_street || `Lead #${prop.id}`).trim()
    const status = statusLabel(prop.lead_status)
    return status ? `${street} (${status})` : street
  })
  return `Other properties (${related.length}): ${labels.join('; ')}`
}

function companiesLine(row: SameAddressLeadSummary): string {
  const names = (row.organizations ?? []).map((name) => name.trim()).filter(Boolean)
  if (!names.length) return ''
  return `Companies: ${names.join(', ')}`
}

function datesLine(row: SameAddressLeadSummary): string {
  const bits: string[] = []
  if (row.created_at) bits.push(`Added ${formatDate(row.created_at)}`)
  if (row.last_contact_date) bits.push(`Last contact ${formatDate(row.last_contact_date)}`)
  return bits.join(' · ')
}

function contactBits(row: SameAddressLeadSummary): string {
  const bits: string[] = []
  if (row.has_phone) bits.push('phone')
  if (row.has_email) bits.push('email')
  return bits.length ? `Contact on file: ${bits.join(' · ')}` : ''
}

function FactLine({ children }: { children: string }) {
  if (!children) return null
  return (
    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
      {children}
    </Typography>
  )
}

function searchHitLabel(item: SearchResultItem): string {
  const owner = (item.owner_display_name || item.label || `Lead #${item.id}`).trim()
  const street = (item.property_street || '').trim()
  return street ? `${owner} — ${street} (#${item.id})` : `${owner} (#${item.id})`
}

export function SameAddressMergeBanner({
  leadId,
  twins,
  currentOwnerLabel,
  currentPeopleNames,
  onMerged,
  open: openProp,
  onOpenChange,
  hideBanner = false,
}: SameAddressMergeBannerProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false)
  const isControlled = openProp !== undefined
  const open = isControlled ? Boolean(openProp) : uncontrolledOpen
  const setOpen = useCallback(
    (next: boolean) => {
      if (!isControlled) setUncontrolledOpen(next)
      onOpenChange?.(next)
    },
    [isControlled, onOpenChange],
  )
  const [winnerId, setWinnerId] = useState<number>(leadId)
  const [removeId, setRemoveId] = useState<number | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [searchHits, setSearchHits] = useState<SearchResultItem[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [selectedHit, setSelectedHit] = useState<SearchResultItem | null>(null)
  const [pastePreview, setPastePreview] = useState<SameAddressLeadSummary | null>(null)
  const [pasteError, setPasteError] = useState<string | null>(null)
  const [pasteLookupPending, setPasteLookupPending] = useState(false)
  const [validatedOtherId, setValidatedOtherId] = useState<number | null>(null)
  const [decisionById, setDecisionById] = useState<Record<number, SameAddressLeadSummary>>({})
  const [contextLoading, setContextLoading] = useState(false)
  const [contextError, setContextError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const removeIdRef = useRef<number | null>(null)
  const searchInputRef = useRef('')
  const pasteLookupPromise = useRef<Promise<boolean> | null>(null)
  const pasteLookupRequestId = useRef(0)
  const searchRequestId = useRef(0)
  const contextRequestId = useRef(0)

  const rememberDecision = useCallback((rows: SameAddressLeadSummary[]) => {
    setDecisionById((prev) => {
      const next = { ...prev }
      for (const row of rows) {
        if (!row?.id) continue
        const prior = next[row.id]
        next[row.id] = {
          ...prior,
          ...row,
          owner_display_name: row.owner_display_name || prior?.owner_display_name || `Lead #${row.id}`,
          people_names: row.people_names?.length ? row.people_names : (prior?.people_names ?? []),
          property_street: row.property_street || prior?.property_street || null,
        }
      }
      return next
    })
  }, [])

  const selectRemoveId = useCallback((nextRemoveId: number | null) => {
    removeIdRef.current = nextRemoveId
    setRemoveId(nextRemoveId)
  }, [])

  const first = twins[0]
  const extra = Math.max(0, twins.length - 1)
  const hasTwins = twins.length > 0

  const invalidatePasteLookup = useCallback(() => {
    pasteLookupRequestId.current += 1
    pasteLookupPromise.current = null
    setPasteLookupPending(false)
  }, [])

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

  const contextKey = useMemo(() => {
    const ids = new Set<number>([leadId])
    for (const twin of twins) ids.add(twin.id)
    if (validatedOtherId != null) ids.add(validatedOtherId)
    if (pastePreview?.id) ids.add(pastePreview.id)
    return [...ids]
      .filter((id) => Number.isInteger(id) && id > 0)
      .sort((a, b) => a - b)
      .join(',')
  }, [leadId, pastePreview?.id, twins, validatedOtherId])

  const resetDialogState = useCallback(() => {
    setWinnerId(leadId)
    setError(null)
    setSearchInput('')
    searchInputRef.current = ''
    setSearchHits([])
    setSearchLoading(false)
    setSearchError(null)
    setSelectedHit(null)
    invalidatePasteLookup()
    setPastePreview(null)
    setPasteError(null)
    setValidatedOtherId(null)
    setDecisionById({})
    setContextLoading(false)
    setContextError(null)
    contextRequestId.current += 1
    selectRemoveId(first?.id ?? null)
  }, [first?.id, invalidatePasteLookup, leadId, selectRemoveId])

  useEffect(() => {
    if (!open) return
    resetDialogState()
  }, [open, resetDialogState])

  useEffect(() => {
    if (!open) return
    const requestId = contextRequestId.current + 1
    contextRequestId.current = requestId
    const ids = contextKey
      .split(',')
      .map((part) => Number(part))
      .filter((id) => Number.isInteger(id) && id > 0)
    setContextLoading(true)
    setContextError(null)
    let pending: Promise<{ leads: SameAddressLeadSummary[] }>
    try {
      pending = Promise.resolve(commandCenterService.getMergeContext(leadId, ids))
    } catch {
      if (contextRequestId.current !== requestId) return
      setContextError('Could not load properties, source, and activities.')
      setContextLoading(false)
      return
    }
    void pending
      .then((res) => {
        if (contextRequestId.current !== requestId) return
        rememberDecision(res?.leads ?? [])
        setContextLoading(false)
      })
      .catch(() => {
        if (contextRequestId.current !== requestId) return
        setContextError('Could not load properties, source, and activities.')
        setContextLoading(false)
      })
  }, [contextKey, leadId, open, rememberDecision])

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

  // Debounced lead search for the manual picker.
  useEffect(() => {
    if (!open) return
    const trimmed = searchInput.trim()
    if (trimmed.length < 2) {
      setSearchHits([])
      setSearchLoading(false)
      setSearchError(null)
      return
    }
    // Pure lead numbers skip typeahead search — validated via merge-preview.
    if (/^\d+$/.test(trimmed)) {
      setSearchHits([])
      setSearchLoading(false)
      setSearchError(null)
      return
    }
    const requestId = searchRequestId.current + 1
    searchRequestId.current = requestId
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => {
      setSearchLoading(true)
      setSearchError(null)
      void searchService
        .search({ q: trimmed, page: 1, per_page: 10, signal: controller.signal })
        .then((response) => {
          if (searchRequestId.current !== requestId) return
          setSearchHits(
            (response.leads ?? []).filter(
              (hit) => hit.type === 'lead' && hit.id !== leadId,
            ),
          )
        })
        .catch(() => {
          if (controller.signal.aborted) return
          if (searchRequestId.current !== requestId) return
          setSearchHits([])
          setSearchError('Search failed. Try again or enter a lead number.')
        })
        .finally(() => {
          if (searchRequestId.current === requestId) setSearchLoading(false)
        })
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timeoutId)
      controller.abort()
    }
  }, [leadId, open, searchInput])

  const validateOtherLeadId = async (rawId: string): Promise<boolean> => {
    if (pasteLookupPromise.current) return pasteLookupPromise.current
    const raw = rawId.trim()
    if (!raw) {
      invalidatePasteLookup()
      setPastePreview(null)
      setPasteError(null)
      setValidatedOtherId(null)
      return hasTwins
    }
    const parsed = Number(raw)
    if (!Number.isInteger(parsed) || parsed <= 0 || parsed === leadId) {
      invalidatePasteLookup()
      setPasteError('Enter a different lead number.')
      setPastePreview(null)
      setValidatedOtherId(null)
      return false
    }
    const requestId = pasteLookupRequestId.current + 1
    pasteLookupRequestId.current = requestId
    const isCurrentLookup = () => pasteLookupRequestId.current === requestId
    const lookup = (async () => {
      setPasteLookupPending(true)
      try {
        const preview = await commandCenterService.getMergePreview(leadId, parsed)
        if (!isCurrentLookup()) {
          return false
        }
        if (!preview.same_building && !preview.mergeable) {
          setPasteError('That record is not the same address.')
          setPastePreview(null)
          setValidatedOtherId(null)
          return false
        }
        setPasteError(null)
        setPastePreview(preview.other)
        rememberDecision([preview.current, preview.other].filter(Boolean))
        setValidatedOtherId(parsed)
        selectRemoveId(preview.other.id)
        return true
      } catch (err) {
        if (!isCurrentLookup()) {
          return false
        }
        setPasteError(err instanceof Error ? err.message : 'Could not look up that lead.')
        setPastePreview(null)
        setValidatedOtherId(null)
        return false
      } finally {
        if (pasteLookupRequestId.current === requestId) {
          setPasteLookupPending(false)
          pasteLookupPromise.current = null
        }
      }
    })()
    pasteLookupPromise.current = lookup
    return lookup
  }

  const handleSelectSearchHit = async (hit: SearchResultItem | null) => {
    setSelectedHit(hit)
    invalidatePasteLookup()
    setPastePreview(null)
    setPasteError(null)
    setValidatedOtherId(null)
    setError(null)
    if (!hit) return
    const label = searchHitLabel(hit)
    setSearchInput(label)
    searchInputRef.current = label
    await validateOtherLeadId(String(hit.id))
  }

  const handleWinnerChange = (nextWinnerId: number) => {
    setWinnerId(nextWinnerId)
    if (removeId === nextWinnerId) {
      selectRemoveId(options.find((row) => row.id !== nextWinnerId)?.id ?? null)
    }
  }

  const handleMerge = async () => {
    const rawSearch = searchInput.trim()
    const numericOnly = /^\d+$/.test(rawSearch) ? rawSearch : null
    const needsManualOther = !hasTwins && validatedOtherId == null
    if (needsManualOther && !numericOnly && !selectedHit) {
      setPasteError('Search for the other lead, or type its lead number.')
      setError('Find the other lead to combine.')
      return
    }
    if (validatedOtherId == null && (numericOnly || selectedHit)) {
      const idToValidate = selectedHit ? String(selectedHit.id) : (numericOnly as string)
      const valid = await validateOtherLeadId(idToValidate)
      if (!valid) return
    } else if (pasteLookupPromise.current) {
      const valid = await pasteLookupPromise.current
      if (!valid) return
    } else if (needsManualOther) {
      setPasteError('Search for the other lead, or type its lead number.')
      return
    }

    const stayId = winnerId
    const otherId = removeIdRef.current
    if (!otherId || otherId === stayId) {
      setError('Choose a primary record, and which one to remove.')
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

  const bannerDetail = hasTwins
    ? extra
      ? `${first.owner_display_name} (#${first.id}) and ${extra} more`
      : `${first.owner_display_name} (#${first.id})`
    : null

  const searchHelper = pasteLookupPending
    ? 'Checking lead...'
    : (pasteError
      ?? searchError
      ?? (hasTwins
        ? 'Optional — search name, address, or lead # to merge a different twin.'
        : 'Search by name, address, or lead number.'))

  return (
    <>
      {hasTwins && !hideBanner ? (
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
              Review merge
            </Button>
          </Box>
        </Alert>
      ) : null}

      <Dialog
        open={open}
        onClose={closeDialog}
        aria-labelledby="same-address-merge-title"
        fullWidth
        maxWidth="md"
        data-testid="same-address-merge-dialog"
        PaperProps={{ sx: { cursor: 'auto' } }}
      >
        <DialogTitle id="same-address-merge-title">Combine these records</DialogTitle>
        <DialogContent sx={{ cursor: 'auto' }}>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            {hasTwins
              ? 'Choose which record is primary. The other one is removed. People, phones, activities, and tasks move onto the primary. If two rows are the same person they become one person with all phone numbers.'
              : 'Find the other lead for this same building (search or lead number). Choose which record is primary; the other is removed. People, phones, activities, and tasks move onto the primary. If two rows are the same person they become one person with all phone numbers.'}
          </Typography>

          <Autocomplete
            freeSolo
            options={searchHits}
            loading={searchLoading}
            value={selectedHit}
            inputValue={searchInput}
            filterOptions={(opts) => opts}
            getOptionLabel={(option) =>
              typeof option === 'string' ? option : searchHitLabel(option)
            }
            isOptionEqualToValue={(option, value) => option.id === value.id}
            onInputChange={(_event, value, reason) => {
              if (reason === 'reset') return
              searchInputRef.current = value
              setSearchInput(value)
              setSelectedHit(null)
              invalidatePasteLookup()
              setPastePreview(null)
              setPasteError(null)
              setValidatedOtherId(null)
            }}
            onChange={(_event, value) => {
              if (typeof value === 'string') {
                setSelectedHit(null)
                searchInputRef.current = value
                setSearchInput(value)
                if (/^\d+$/.test(value.trim())) {
                  void validateOtherLeadId(value.trim())
                }
                return
              }
              void handleSelectSearchHit(value)
            }}
            onBlur={() => {
              const raw = searchInputRef.current.trim()
              if (/^\d+$/.test(raw) && validatedOtherId == null) {
                void validateOtherLeadId(raw)
              }
            }}
            renderOption={(props, option) => (
              <li
                {...props}
                key={option.id}
                data-testid={`same-address-merge-search-hit-${option.id}`}
              >
                <Box sx={{ py: 0.25 }}>
                  <Typography variant="body2" fontWeight={600}>
                    {option.owner_display_name || option.label} (#{option.id})
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {option.property_street || 'No street on file'}
                  </Typography>
                </Box>
              </li>
            )}
            renderInput={(params) => (
              <TextField
                {...params}
                size="small"
                label="Find the other lead"
                placeholder="Name, address, or lead #"
                error={Boolean(pasteError || searchError)}
                helperText={searchHelper}
                inputProps={{
                  ...params.inputProps,
                  // Keep paste-id test id so numeric-entry tests stay stable.
                  'data-testid': 'same-address-merge-paste-id',
                  style: { ...(params.inputProps.style || {}), cursor: 'text' },
                }}
                InputProps={{
                  ...params.InputProps,
                  endAdornment: (
                    <>
                      {searchLoading || pasteLookupPending ? (
                        <CircularProgress color="inherit" size={16} />
                      ) : null}
                      {params.InputProps.endAdornment}
                    </>
                  ),
                }}
                sx={{ caretColor: 'text.primary' }}
              />
            )}
            sx={{ mt: 0.5 }}
          />

          {pastePreview ? (
            <Typography
              variant="body2"
              color="text.secondary"
              sx={{ mt: 1 }}
              data-testid="same-address-merge-search-selected"
            >
              Selected: {pastePreview.owner_display_name} (#{pastePreview.id})
              {pastePreview.property_street ? ` — ${pastePreview.property_street}` : ''}
            </Typography>
          ) : null}

          <FormControl component="fieldset" sx={{ mt: 1.5, display: 'block' }}>
            <FormLabel id="same-address-merge-stay-label" sx={{ mb: 0.5 }}>
              Choose primary
            </FormLabel>
            <RadioGroup
              aria-labelledby="same-address-merge-stay-label"
              value={String(winnerId)}
              onChange={(event) => handleWinnerChange(Number(event.target.value))}
            >
              {options.map((row) => {
                const detail = decisionById[row.id]
                const view: SameAddressLeadSummary = detail
                  ? {
                      ...row,
                      ...detail,
                      owner_display_name: detail.owner_display_name || row.owner_display_name,
                      people_names: detail.people_names?.length
                        ? detail.people_names
                        : row.people_names,
                      property_street: detail.property_street || row.property_street,
                    }
                  : row
                const ready = view.activity != null
                return (
                  <FormControlLabel
                    key={row.id}
                    value={String(row.id)}
                    sx={{ alignItems: 'flex-start', mr: 0, mb: 1 }}
                    control={<Radio data-testid={`same-address-merge-stay-${row.id}`} sx={{ pt: 0.25 }} />}
                    label={
                      <Box data-testid={`same-address-merge-facts-${row.id}`} sx={{ py: 0.25 }}>
                        <Typography variant="body2" fontWeight={600}>
                          {view.owner_display_name} (#{view.id})
                          {view.id === leadId ? ' · this lead' : ''}
                        </Typography>
                        <FactLine>{`This property: ${addressLine(view)}`}</FactLine>
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          {peopleLine(view.people_names)}
                        </Typography>
                        {ready ? (
                          <>
                            <FactLine>{propertyFactsLine(view)}</FactLine>
                            <FactLine>{`Source: ${sourceLine(view)}`}</FactLine>
                            <FactLine>{datesLine(view)}</FactLine>
                            <FactLine>{companiesLine(view)}</FactLine>
                            <FactLine>{relatedLine(view)}</FactLine>
                            <FactLine>{activityLine(view)}</FactLine>
                            <FactLine>{contactBits(view)}</FactLine>
                          </>
                        ) : (
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                            {contextLoading
                              ? 'Loading properties, source, and activities…'
                              : (contextError || 'Details unavailable.')}
                          </Typography>
                        )}
                      </Box>
                    }
                  />
                )
              })}
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
          {error ? (
            <Typography
              color="error"
              variant="body2"
              sx={{ mt: 1 }}
              data-testid="same-address-merge-error"
            >
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
