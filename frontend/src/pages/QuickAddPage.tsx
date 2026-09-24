/**
 * QuickAddPage — mobile-first field capture for walk-by leads.
 * Creates a Skip Trace lead and queues HubSpot deal push.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControl,
  FormHelperText,
  IconButton,
  InputLabel,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import { FollowUpHorizonControls } from '@/components/FollowUpHorizonControls'
import {
  CREATE_TASK_PRESETS,
  getCreateTaskPreset,
  resolveCreateTaskPayload,
  type CreateTaskPresetId,
} from '@/utils/createTaskPresets'
import {
  resolveFollowUpDueDate,
  type FollowUpPreset,
} from '@/utils/followUpPresets'
import {
  LeadUnitsEditor,
  serializeLeadUnitDrafts,
  type LeadSubtype,
  type LeadUnitDraft,
} from '@/components/LeadUnitsEditor'
import CloseIcon from '@mui/icons-material/Close'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import MyLocationIcon from '@mui/icons-material/MyLocation'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import usePlacesAutocomplete from 'use-places-autocomplete'
import { useGoogleMapsAvailability, useGoogleMapsLoaded } from '@/context/GoogleMapsContext'
import { leadService } from '@/services/leadApi'
import { commandCenterService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import type { ContactRole, LeadStatus, QuickAddPayload, QuickAddResponse } from '@/types'
import { QUICK_ADD_DEAL_SOURCES } from '@/types'
import { LEAD_STATUS_LABELS } from '@/components/LeadStatusChip'
import { ALL_LEAD_STATUSES } from '@/constants/leadStatuses'
import { formatDateOnly } from '@/utils/formatters'
import { CaptureSourceFields } from '@/components/CaptureSourceFields'
import { CONTACT_ROLE_OPTIONS } from '@/components/ContactFormModal'
import { contactService } from '@/services/contactApi'

type Priority = 'high' | 'medium' | 'low'

type CapturePerson = {
  key: string
  firstName: string
  lastName: string
  role: ContactRole
  phone: string
  email: string
}

type SavedQuickAdd = QuickAddResponse & {
  peopleSaved: number
  peopleWarning: string | null
}

const PRIORITY_OPTIONS: { value: Priority; label: string }[] = [
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]

function todayIsoDate(): string {
  const d = new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs)
    return () => window.clearTimeout(id)
  }, [value, delayMs])
  return debounced
}

function reverseGeocodeLabel(lat: number, lng: number): Promise<string | null> {
  return new Promise((resolve) => {
    try {
      const geocoder = new (window as any).google.maps.Geocoder()
      geocoder.geocode({ location: { lat, lng } }, (results: any[], status: string) => {
        if (status === 'OK' && results?.[0]?.formatted_address) {
          resolve(results[0].formatted_address)
        } else {
          resolve(null)
        }
      })
    } catch {
      resolve(null)
    }
  })
}

function hubspotSuccessMessage(result: QuickAddResponse): string | null {
  if (result.hubspot_push_status === 'disabled') {
    return null
  }
  if (result.hubspot_push_status === 'queue_failed') {
    return 'HubSpot sync could not be queued. The lead was saved on the platform.'
  }
  return 'HubSpot deal sync has been queued.'
}

export function QuickAddPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const mapsLoaded = useGoogleMapsLoaded()
  const mapsAvailability = useGoogleMapsAvailability()
  const suggestionsRef = useRef<HTMLUListElement>(null)
  const coordSourceRef = useRef<'gps' | 'place-pending' | 'place' | null>(null)

  const [note, setNote] = useState('')
  const [context, setContext] = useState('')
  const [priority, setPriority] = useState<Priority | null>(null)
  const [dealSource, setDealSource] = useState<string>(QUICK_ADD_DEAL_SOURCES[0])
  const [pipelineStatus, setPipelineStatus] = useState<LeadStatus>('skip_trace')
  const [dateIdentified, setDateIdentified] = useState(todayIsoDate)
  const [addressError, setAddressError] = useState('')
  const [gpsStatus, setGpsStatus] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [gpsLabel, setGpsLabel] = useState<string | null>(null)
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null)
  const [parsedAddress, setParsedAddress] = useState<{
    city: string | null
    state: string | null
    zip: string | null
  }>({ city: null, state: null, zip: null })
  // Bumped on every Places selection so older getDetails callbacks are ignored.
  const placesRequestIdRef = useRef(0)
  const personSeq = useRef(0)
  const [people, setPeople] = useState<CapturePerson[]>([])
  const [peopleError, setPeopleError] = useState('')
  const [unitsCount, setUnitsCount] = useState('')
  const [askingPrice, setAskingPrice] = useState('')
  const [bedrooms, setBedrooms] = useState('')
  const [bathrooms, setBathrooms] = useState('')
  const [leadSubtype, setLeadSubtype] = useState<LeadSubtype | ''>('')
  const [leadUnitDrafts, setLeadUnitDrafts] = useState<LeadUnitDraft[]>([])
  const [nextTaskEnabled, setNextTaskEnabled] = useState(false)
  const [nextTaskPreset, setNextTaskPreset] = useState<CreateTaskPresetId>('custom')
  const [nextTaskTitle, setNextTaskTitle] = useState('')
  const [nextTaskDuePreset, setNextTaskDuePreset] = useState<FollowUpPreset>('3')
  const [nextTaskDueDate, setNextTaskDueDate] = useState('')
  const [nextTaskNotes, setNextTaskNotes] = useState('')
  const [successResult, setSuccessResult] = useState<SavedQuickAdd | null>(null)
  const [existingActionFeedback, setExistingActionFeedback] = useState<{
    severity: 'success' | 'warning' | 'error'
    message: string
  } | null>(null)

  const {
    ready,
    value: address,
    suggestions: { status, data },
    setValue: setAddress,
    clearSuggestions,
    init,
  } = usePlacesAutocomplete({
    requestOptions: { componentRestrictions: { country: 'us' } },
    debounce: 300,
    initOnMount: false,
  })

  const debouncedAddress = useDebouncedValue(address.trim(), 400)

  const { data: propertyLookup, isFetching: propertySearchLoading } = useQuery({
    queryKey: ['quick-add-property-lookup', debouncedAddress],
    queryFn: ({ signal }) => leadService.lookupQuickAdd(debouncedAddress, signal),
    enabled: debouncedAddress.length >= 2,
    staleTime: 30_000,
  })

  const existingMatches = useMemo(
    () => propertyLookup?.matches ?? [],
    [propertyLookup?.matches],
  )

  useEffect(() => {
    if (mapsLoaded) init()
  }, [mapsLoaded, init])

  const addressHelperText = addressError
    ? addressError
    : !mapsLoaded || !ready
      ? 'Street optional if you have city, state, or ZIP — suggestions load when Maps is ready'
      : 'Street optional if you know city / state / ZIP. Start typing for Google suggestions'

  useEffect(() => {
    if (!navigator.geolocation) {
      setGpsStatus('error')
      return
    }
    if (coords) {
      // Places selection (or a prior GPS fix) already provided coordinates.
      setGpsStatus((prev) => (prev === 'loading' || prev === 'idle' ? 'ok' : prev))
      return
    }

    setGpsStatus('loading')
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (coordSourceRef.current === 'place-pending' || coordSourceRef.current === 'place') {
          return
        }
        coordSourceRef.current = 'gps'
        setCoords({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        })
        setGpsStatus('ok')
      },
      () => setGpsStatus('error'),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 },
    )
  }, [coords])

  useEffect(() => {
    if (!mapsLoaded || !coords) return

    let cancelled = false
    reverseGeocodeLabel(coords.lat, coords.lng).then((label) => {
      if (!cancelled && label) setGpsLabel(label)
    })
    return () => {
      cancelled = true
    }
  }, [mapsLoaded, coords])

  const quickAddMutation = useMutation({
    mutationFn: async ({
      quickAdd,
      people: peopleToSave,
    }: {
      quickAdd: QuickAddPayload
      people: CapturePerson[]
    }): Promise<SavedQuickAdd> => {
      const result = await leadService.quickAdd(quickAdd)
      let peopleSaved = 0
      const failures: string[] = []
      // A repeat capture must not demote whoever is already primary. If we
      // cannot tell, fail closed and leave every new person non-primary.
      let existingHasPrimary = false
      if (!result.created) {
        try {
          const existing = await contactService.getPropertyContacts(result.lead_id)
          existingHasPrimary = existing.some((row) => row.is_primary)
        } catch {
          existingHasPrimary = true
        }
      }
      for (const person of peopleToSave) {
        const label = [person.firstName, person.lastName].filter(Boolean).join(' ') || 'Contact'
        let createdId: number | null = null
        try {
          const created = await contactService.createContact({
            first_name: person.firstName.trim() || null,
            last_name: person.lastName.trim() || null,
            role: person.role,
            source: quickAdd.deal_source ?? null,
            capture_context: quickAdd.context ?? null,
            phones: person.phone.trim()
              ? [{ value: person.phone.trim(), label: 'mobile' }]
              : [],
            emails: person.email.trim()
              ? [{ value: person.email.trim(), label: 'personal' }]
              : [],
          })
          createdId = created.id
          const makePrimary = !existingHasPrimary && peopleSaved === 0
          await contactService.linkContactToProperty(result.lead_id, {
            contact_id: created.id,
            role: person.role,
            is_primary: makePrimary,
          })
          if (makePrimary) existingHasPrimary = true
          peopleSaved += 1
        } catch (error) {
          if (createdId != null) {
            try {
              await contactService.deleteContact(createdId)
            } catch {
              // Still surface the link failure if cleanup also fails.
            }
          }
          const message = error instanceof Error ? error.message : 'Could not save contact'
          failures.push(`${label}: ${message}`)
        }
      }
      return {
        ...result,
        peopleSaved,
        peopleWarning: failures.length ? failures.join(' ') : null,
      }
    },
    onSuccess: (result) => {
      setSuccessResult(result)
    },
  })

  const existingLeadActionMutation = useMutation({
    mutationFn: async ({
      leadId,
      action,
    }: {
      leadId: number
      action: 'outreach' | 'mail'
    }) => {
      await commandCenterService.updateStatus(leadId, 'mailing_no_contact_made')
      if (action === 'outreach') {
        return {
          severity: 'success' as const,
          message: 'Lead reactivated. Scoring will place it in the appropriate outreach flow.',
        }
      }

      const result = await openLetterService.enqueue([leadId], 'quick-add')
      if (result.added > 0) {
        return { severity: 'success' as const, message: 'Lead reactivated and added to the mail queue.' }
      }
      const outcome = result.results?.find((item) => item.lead_id === leadId)
      if (outcome?.status === 'already_queued') {
        return {
          severity: 'success' as const,
          message: 'Lead reactivated and was already in the mail queue.',
        }
      }
      if (outcome?.status === 'recently_sold') {
        const eligible = outcome.rescheduled_to
          ? formatDateOnly(outcome.rescheduled_to)
          : 'the end of the two-year hold'
        return {
          severity: 'warning' as const,
          message: `Lead was reactivated, but a recent sale was detected. Direct mail is deferred until ${eligible}.`,
        }
      }
      if (outcome?.status === 'mail_cadence') {
        const eligible = outcome.mail_eligible_date
          ? formatDateOnly(outcome.mail_eligible_date)
          : 'the quarterly rematch date'
        return {
          severity: 'warning' as const,
          message: `Lead was reactivated, but was mailed recently. Next mail on ${eligible}.`,
        }
      }
      throw new Error(outcome?.error || 'Lead was reactivated, but could not be added to mail.')
    },
    onSuccess: (feedback) => {
      setExistingActionFeedback(feedback)
    },
    onError: (error: Error) => {
      setExistingActionFeedback({
        severity: 'error',
        message: error.message || 'Could not reactivate this lead.',
      })
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['quick-add-property-lookup'] })
    },
  })

  const handleSelect = (description: string, placeId: string) => {
    // Show the suggestion immediately; replace with street-line once details load
    // so we never submit the full Places description (city/state/ZIP duplicated).
    const requestId = ++placesRequestIdRef.current
    const streetGuess = description.split(',')[0]?.trim() || description
    setAddress(streetGuess, false)
    setParsedAddress({ city: null, state: null, zip: null })
    coordSourceRef.current = 'place-pending'
    setCoords(null)
    clearSuggestions()
    setAddressError('')
    try {
      const service = new (window as any).google.maps.places.PlacesService(
        document.createElement('div'),
      )
      service.getDetails(
        { placeId, fields: ['geometry', 'address_components'] },
        (result: any, placeStatus: any) => {
          if (requestId !== placesRequestIdRef.current) return
          if (
            placeStatus === (window as any).google.maps.places.PlacesServiceStatus.OK &&
            result?.geometry?.location
          ) {
            coordSourceRef.current = 'place'
            setCoords({
              lat: result.geometry.location.lat(),
              lng: result.geometry.location.lng(),
            })
            // Places coords supersede an in-flight GPS probe — settle the
            // indicator so it does not stay on "Getting your location…".
            setGpsStatus('ok')
          }
          const components: Array<{ long_name: string; short_name: string; types: string[] }> =
            result?.address_components ?? []
          const find = (type: string) =>
            components.find((c) => c.types.includes(type))
          const streetNumber = find('street_number')?.long_name
          const route = find('route')?.long_name
          const streetLine = [streetNumber, route].filter(Boolean).join(' ').trim()
          if (streetLine) {
            setAddress(streetLine, false)
          }
          const city =
            find('locality')?.long_name ??
            find('sublocality')?.long_name ??
            find('neighborhood')?.long_name ??
            null
          const state = find('administrative_area_level_1')?.short_name ?? null
          const zip = find('postal_code')?.long_name ?? null
          setParsedAddress({ city, state, zip })
        },
      )
    } catch {
      // Address still valid without coords
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // Places selections carry structured city/state/ZIP — persist street-only.
    // Manual free-form entries keep the raw input so city/state/ZIP embedded in
    // the one-liner are not silently dropped when parsedAddress is empty.
    const hasStructured =
      Boolean(parsedAddress.city)
      || Boolean(parsedAddress.state)
      || Boolean(parsedAddress.zip)
    const street = (
      hasStructured
        ? (address.split(',')[0] || address)
        : address
    ).trim()
    const city = (parsedAddress.city || '').trim()
    const state = (parsedAddress.state || '').trim()
    const zip = (parsedAddress.zip || '').trim()
    if (!street && !(city || state || zip)) {
      setAddressError('Enter a property address, or at least a city, state, or ZIP')
      return
    }
    const incompletePerson = people.some(
      (person) => !person.firstName.trim() && !person.lastName.trim(),
    )
    if (incompletePerson) {
      setPeopleError('Each person needs a first or last name, or remove them.')
      return
    }
    setAddressError('')
    setPeopleError('')
    const namedPeople = people.filter(
      (person) => person.firstName.trim() || person.lastName.trim(),
    )
    const parseOptionalNumber = (raw: string): number | null => {
      const trimmed = raw.trim()
      if (!trimmed) return null
      const n = Number(trimmed)
      return Number.isFinite(n) ? n : null
    }
    let next_task: QuickAddPayload['next_task'] = null
    if (pipelineStatus !== 'skip_trace' && nextTaskEnabled) {
      const preset = getCreateTaskPreset(nextTaskPreset)
      const titleForValidation = nextTaskTitle.trim() || preset.defaultTitle || ''
      if (!titleForValidation) {
        setAddressError('Next task needs a title')
        return
      }
      const { title: resolvedTitle, task_type: taskType } = resolveCreateTaskPayload(
        nextTaskPreset,
        titleForValidation,
      )
      next_task = {
        title: resolvedTitle,
        task_type: taskType,
        due_date: resolveFollowUpDueDate(nextTaskDuePreset, nextTaskDueDate),
        notes: nextTaskNotes.trim() || null,
      }
    }
    const serializedUnits = leadUnitDrafts.length
      ? serializeLeadUnitDrafts(leadUnitDrafts)
      : null
    quickAddMutation.mutate({
      quickAdd: {
        property_street: street || null,
        note: note.trim() || null,
        context: context.trim() || null,
        capture_kind: namedPeople.length ? 'lead' : null,
        priority,
        deal_source: dealSource,
        lead_status: pipelineStatus,
        date_identified: dateIdentified || todayIsoDate(),
        capture_latitude: coords?.lat ?? null,
        capture_longitude: coords?.lng ?? null,
        capture_location_label: gpsLabel,
        property_city: city || null,
        property_state: state || null,
        property_zip: zip || null,
        units: parseOptionalNumber(unitsCount),
        asking_price: parseOptionalNumber(askingPrice),
        bedrooms: parseOptionalNumber(bedrooms),
        bathrooms: parseOptionalNumber(bathrooms),
        lead_subtype: leadSubtype || null,
        lead_units: serializedUnits,
        next_task,
      },
      people: namedPeople,
    })
  }

  const handleReset = () => {
    setAddress('')
    setNote('')
    setContext('')
    setPriority(null)
    setDealSource(QUICK_ADD_DEAL_SOURCES[0])
    setPipelineStatus('skip_trace')
    setDateIdentified(todayIsoDate())
    setPeople([])
    setPeopleError('')
    setUnitsCount('')
    setAskingPrice('')
    setBedrooms('')
    setBathrooms('')
    setLeadSubtype('')
    setLeadUnitDrafts([])
    setNextTaskEnabled(false)
    setNextTaskPreset('custom')
    setNextTaskTitle('')
    setNextTaskDuePreset('3')
    setNextTaskDueDate('')
    setNextTaskNotes('')
    setSuccessResult(null)
    setExistingActionFeedback(null)
    setAddressError('')
    setParsedAddress({ city: null, state: null, zip: null })
    quickAddMutation.reset()
    clearSuggestions()
  }

  const handleClose = () => {
    const ref = typeof document !== 'undefined' ? document.referrer : ''
    let sameOriginRef = false
    if (ref) {
      try {
        sameOriginRef = new URL(ref).origin === window.location.origin
      } catch {
        sameOriginRef = false
      }
    }
    if (sameOriginRef && window.history.length > 1) {
      navigate(-1)
      return
    }
    navigate('/kanban')
  }

  const addPerson = () => {
    const key = `person-${personSeq.current}`
    personSeq.current += 1
    setPeople((current) => [
      ...current,
      { key, firstName: '', lastName: '', role: 'owner', phone: '', email: '' },
    ])
    setPeopleError('')
  }

  const intro = 'Save a lead even when the full street is unknown — city, state, or ZIP is enough. Add people, source, property facts, and a follow-up when you already know the pipeline stage.'

  const dialogTitle = 'Quick Add'

  const formBody =
    successResult !== null ? (
      (() => {
        const hubspotMessage = hubspotSuccessMessage(successResult)
        return (
          <Box sx={{ maxWidth: 480, mx: 'auto' }}>
            <Paper sx={{ p: 3, textAlign: 'center' }}>
              <CheckCircleOutlineIcon color="success" sx={{ fontSize: 48, mb: 1 }} />
              <Typography variant="h6" gutterBottom>
                {successResult.created ? 'Lead saved' : 'Existing lead updated'}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                {successResult.created
                  ? (successResult.lead_status || 'skip_trace') === 'skip_trace'
                    ? 'Added to Skip Trace.'
                    : `Saved as ${LEAD_STATUS_LABELS[successResult.lead_status as LeadStatus] ?? successResult.lead_status}.`
                  : 'This address was already in the system. Walk-by notes were appended without changing the pipeline stage.'}
                {successResult.peopleSaved > 0
                  ? ` ${successResult.peopleSaved === 1 ? '1 person' : `${successResult.peopleSaved} people`} saved on this property.`
                  : ''}
                {hubspotMessage ? ` ${hubspotMessage}` : ' HubSpot write-back is disabled in this environment.'}
              </Typography>
              {successResult.peopleWarning && (
                <Alert severity="warning" sx={{ mb: 2, textAlign: 'left' }}>
                  {successResult.peopleWarning}
                </Alert>
              )}
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <Button variant="contained" component={RouterLink} to={`/leads/${successResult.lead_id}`}>
                  View lead
                </Button>
                <Button variant="outlined" component={RouterLink} to="/kanban">
                  Open Kanban
                </Button>
                <Button variant="text" onClick={handleReset}>
                  Add another
                </Button>
              </Box>
            </Paper>
          </Box>
        )
      })()
    ) : (
    <Box
      component="form"
      onSubmit={handleSubmit}
      sx={{ width: '100%', pb: 4, cursor: 'auto' }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: 720 }}>
        {intro}
      </Typography>

      {peopleError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {peopleError}
        </Alert>
      )}

      {quickAddMutation.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(quickAddMutation.error as Error)?.message || 'Failed to save lead'}
        </Alert>
      )}

      <Box
        data-testid="quick-add-layout"
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1.15fr) minmax(320px, 0.85fr)' },
          columnGap: { md: 5 },
          rowGap: 3,
          alignItems: 'start',
        }}
      >
      <Box data-testid="quick-add-property-fields" sx={{ minWidth: 0, cursor: 'auto' }}>
      <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1.5 }}>
        Property
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <MyLocationIcon
          fontSize="small"
          color={gpsStatus === 'ok' ? 'success' : gpsStatus === 'error' ? 'disabled' : 'action'}
        />
        <Typography variant="body2" color="text.secondary">
          {gpsStatus === 'loading' && 'Getting your location…'}
          {gpsStatus === 'ok' && (gpsLabel ? `Near: ${gpsLabel}` : 'Location captured')}
          {gpsStatus === 'error' && 'Location unavailable — address only'}
          {gpsStatus === 'idle' && 'Waiting for location…'}
        </Typography>
      </Box>

      <Box sx={{ position: 'relative', mb: 1 }}>
        <TextField
          label="Property street (optional)"
          value={address}
          onChange={(e) => {
            placesRequestIdRef.current += 1
            coordSourceRef.current = null
            setAddress(e.target.value)
            setExistingActionFeedback(null)
            // Keep locality fields — user may clear street while keeping city/ZIP.
            if (e.target.value.trim() || parsedAddress.city || parsedAddress.state || parsedAddress.zip) {
              setAddressError('')
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') clearSuggestions()
          }}
          error={!!addressError}
          helperText={addressHelperText}
          fullWidth
          autoComplete="off"
          placeholder="123 Main St — or leave blank and use city / ZIP below"
          disabled={quickAddMutation.isPending}
          inputProps={{
            'aria-label': 'Property street',
            'aria-autocomplete': 'list',
            'aria-controls': status === 'OK' ? 'quick-add-suggestions' : undefined,
            'aria-expanded': status === 'OK',
            'data-testid': 'quick-add-street',
          }}
        />
        {mapsAvailability === 'unavailable' && (
          <Alert severity="warning" sx={{ mt: 1 }} data-testid="quick-add-maps-unavailable">
            Google address suggestions are unavailable (Maps API key not loaded). You can still
            enter a full street address and save.
          </Alert>
        )}
        {status === 'OK' && data.length > 0 && (
          <List
            id="quick-add-suggestions"
            ref={suggestionsRef}
            role="listbox"
            aria-label="Address suggestions"
            sx={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              zIndex: 1400,
              bgcolor: 'background.paper',
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 1,
              boxShadow: 3,
              mt: 0.5,
              maxHeight: 240,
              overflowY: 'auto',
              p: 0,
            }}
          >
            {data.map(({ place_id, description }) => (
              <ListItem key={place_id} disablePadding>
                <ListItemButton
                  role="option"
                  onClick={() => handleSelect(description, place_id)}
                  aria-label={description}
                  sx={{ py: 1 }}
                >
                  <ListItemText
                    primary={description}
                    primaryTypographyProps={{ variant: 'body2' }}
                  />
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        )}
      </Box>

      <Box
        sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2, mt: 1 }}
        data-testid="quick-add-locality"
      >
        <TextField
          label="City"
          value={parsedAddress.city ?? ''}
          onChange={(e) => {
            setParsedAddress((prev) => ({ ...prev, city: e.target.value || null }))
            setAddressError('')
          }}
          size="small"
          sx={{ flex: '1 1 140px', caretColor: 'text.primary' }}
          inputProps={{ 'data-testid': 'quick-add-city', 'aria-label': 'City' }}
          disabled={quickAddMutation.isPending}
        />
        <TextField
          label="State"
          value={parsedAddress.state ?? ''}
          onChange={(e) => {
            setParsedAddress((prev) => ({ ...prev, state: e.target.value || null }))
            setAddressError('')
          }}
          size="small"
          sx={{ width: 88, caretColor: 'text.primary' }}
          inputProps={{ 'data-testid': 'quick-add-state', 'aria-label': 'State', maxLength: 2 }}
          disabled={quickAddMutation.isPending}
        />
        <TextField
          label="ZIP"
          value={parsedAddress.zip ?? ''}
          onChange={(e) => {
            setParsedAddress((prev) => ({ ...prev, zip: e.target.value || null }))
            setAddressError('')
          }}
          size="small"
          sx={{ width: 110, caretColor: 'text.primary' }}
          inputProps={{ 'data-testid': 'quick-add-zip', 'aria-label': 'ZIP' }}
          disabled={quickAddMutation.isPending}
        />
      </Box>

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Property facts
      </Typography>
      <Box
        sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}
        data-testid="quick-add-property-facts"
      >
        <TextField
          label="Units"
          type="number"
          size="small"
          value={unitsCount}
          onChange={(e) => setUnitsCount(e.target.value)}
          sx={{ width: 100, caretColor: 'text.primary' }}
          inputProps={{ min: 0, 'data-testid': 'quick-add-units' }}
          disabled={quickAddMutation.isPending}
        />
        <TextField
          label="Asking price"
          type="number"
          size="small"
          value={askingPrice}
          onChange={(e) => setAskingPrice(e.target.value)}
          sx={{ width: 140, caretColor: 'text.primary' }}
          inputProps={{ min: 0, 'data-testid': 'quick-add-asking-price' }}
          disabled={quickAddMutation.isPending}
        />
        <TextField
          label="Beds"
          type="number"
          size="small"
          value={bedrooms}
          onChange={(e) => setBedrooms(e.target.value)}
          sx={{ width: 90, caretColor: 'text.primary' }}
          inputProps={{ min: 0, 'data-testid': 'quick-add-bedrooms' }}
          disabled={quickAddMutation.isPending}
        />
        <TextField
          label="Baths"
          type="number"
          size="small"
          value={bathrooms}
          onChange={(e) => setBathrooms(e.target.value)}
          sx={{ width: 90, caretColor: 'text.primary' }}
          inputProps={{ min: 0, step: 0.5, 'data-testid': 'quick-add-bathrooms' }}
          disabled={quickAddMutation.isPending}
        />
      </Box>

      <Box sx={{ mb: 2 }}>
        <LeadUnitsEditor
          units={leadUnitDrafts}
          onChange={setLeadUnitDrafts}
          subtype={leadSubtype}
          onSubtypeChange={setLeadSubtype}
          disabled={quickAddMutation.isPending}
          testIdPrefix="quick-add-units-editor"
        />
      </Box>

      {debouncedAddress.length >= 2 && (
        <Box sx={{ mb: 2 }}>
          {propertySearchLoading && (
            <Typography variant="caption" color="text.secondary">
              Searching existing properties…
            </Typography>
          )}
          {!propertySearchLoading && existingMatches.length > 0 && (
            <Alert
              severity="warning"
              icon={<WarningAmberIcon fontSize="inherit" />}
              sx={{ mb: 1 }}
            >
              {existingMatches.length === 1
                ? '1 matching property already in the system.'
                : `${existingMatches.length} matching properties already in the system.`}
              {' '}Saving will update the existing lead if the address matches.
            </Alert>
          )}
          {!propertySearchLoading && existingMatches.length > 0 && (
            <Paper variant="outlined" sx={{ maxHeight: 200, overflowY: 'auto' }}>
              <List dense disablePadding>
                {existingMatches.map((match) => (
                  <ListItem
                    key={match.lead_id}
                    disablePadding
                    divider
                    sx={{ display: 'block' }}
                  >
                    <ListItemButton
                      component={RouterLink}
                      to={`/leads/${match.lead_id}`}
                      sx={{ py: 1 }}
                    >
                      <ListItemText
                        primary={match.property_street ?? `Lead #${match.lead_id}`}
                        secondary={
                          match.lead_status
                            ? `Status: ${match.lead_status.replace(/_/g, ' ')}`
                            : undefined
                        }
                        primaryTypographyProps={{ variant: 'body2' }}
                        secondaryTypographyProps={{ variant: 'caption' }}
                      />
                    </ListItemButton>
                    {match.lead_status === 'deprioritize' &&
                      address.trim() === debouncedAddress && (
                      <Box
                        sx={{ display: 'flex', gap: 1, px: 2, pb: 1, flexWrap: 'wrap' }}
                        data-testid={`quick-add-reactivation-actions-${match.lead_id}`}
                      >
                        <Button
                          aria-label={`Reactivate ${match.property_street || `lead ${match.lead_id}`} for outreach`}
                          size="small"
                          variant="outlined"
                          disabled={existingLeadActionMutation.isPending}
                          onClick={() => {
                            setExistingActionFeedback(null)
                            existingLeadActionMutation.mutate({
                              leadId: match.lead_id,
                              action: 'outreach',
                            })
                          }}
                        >
                          Reactivate for outreach
                        </Button>
                        <Button
                          aria-label={`Reactivate ${match.property_street || `lead ${match.lead_id}`} and add to mail`}
                          size="small"
                          variant="contained"
                          disabled={existingLeadActionMutation.isPending}
                          onClick={() => {
                            setExistingActionFeedback(null)
                            existingLeadActionMutation.mutate({
                              leadId: match.lead_id,
                              action: 'mail',
                            })
                          }}
                        >
                          Reactivate + add to mail
                        </Button>
                      </Box>
                    )}
                  </ListItem>
                ))}
              </List>
            </Paper>
          )}
          {existingActionFeedback && (
            <Alert severity={existingActionFeedback.severity} sx={{ mt: 1 }}>
              {existingActionFeedback.message}
            </Alert>
          )}
        </Box>
      )}

      <CaptureSourceFields
        source={dealSource}
        onSourceChange={setDealSource}
        context={context}
        onContextChange={setContext}
        sourceLabelId="quick-add-deal-source-label"
        contextPlaceholder="Why this property stood out…"
      />

      <TextField
        label="Date identified"
        type="date"
        value={dateIdentified}
        onChange={(e) => setDateIdentified(e.target.value)}
        fullWidth
        required
        sx={{ mb: 2 }}
        InputLabelProps={{ shrink: true }}
        helperText="When you found this property (defaults to today)"
        inputProps={{ 'aria-label': 'Date identified' }}
      />

      <TextField
        label="Notes"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        fullWidth
        multiline
        minRows={4}
        sx={{ mb: 2, caretColor: 'text.primary' }}
        placeholder="Anything else to remember"
        inputProps={{ 'aria-label': 'Notes' }}
      />

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Priority
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        {PRIORITY_OPTIONS.map((opt) => (
          <Chip
            key={opt.value}
            label={opt.label}
            clickable
            color={priority === opt.value ? 'primary' : 'default'}
            variant={priority === opt.value ? 'filled' : 'outlined'}
            onClick={() => setPriority(priority === opt.value ? null : opt.value)}
            sx={{ cursor: 'pointer' }}
          />
        ))}
      </Box>
      </Box>

      <Box data-testid="quick-add-people" sx={{ minWidth: 0, cursor: 'auto' }}>
        <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>
          People
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Add everyone you know for this address. Leave this empty if you only have the property.
        </Typography>
        {people.map((person, index) => (
          <Paper
            key={person.key}
            variant="outlined"
            data-testid={`quick-add-person-${index}`}
            sx={{ p: 1.5, mb: 1.5, cursor: 'auto' }}
          >
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="body2" fontWeight={600}>
                Person {index + 1}
              </Typography>
              <IconButton
                aria-label={`Remove person ${index + 1}`}
                data-testid={`quick-add-remove-person-${index}`}
                onClick={() => {
                  setPeople((current) => current.filter((row) => row.key !== person.key))
                  setPeopleError('')
                }}
                size="small"
                sx={{ cursor: 'pointer' }}
              >
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
              <TextField
                label="First name"
                value={person.firstName}
                onChange={(event) => {
                  const value = event.target.value
                  setPeople((current) => current.map((row) => (
                    row.key === person.key ? { ...row, firstName: value } : row
                  )))
                }}
                fullWidth
                size="small"
                inputProps={{ 'aria-label': `First name ${index + 1}` }}
                sx={{ caretColor: 'text.primary' }}
              />
              <TextField
                label="Last name"
                value={person.lastName}
                onChange={(event) => {
                  const value = event.target.value
                  setPeople((current) => current.map((row) => (
                    row.key === person.key ? { ...row, lastName: value } : row
                  )))
                }}
                fullWidth
                size="small"
                inputProps={{ 'aria-label': `Last name ${index + 1}` }}
                sx={{ caretColor: 'text.primary' }}
              />
            </Box>
            <Box sx={{ display: 'flex', gap: 1, mb: 1.5, flexWrap: 'wrap' }}>
              <FormControl size="small" sx={{ minWidth: 160, flex: '1 1 160px' }}>
                <InputLabel id={`quick-add-person-role-${index}`}>Role</InputLabel>
                <Select
                  labelId={`quick-add-person-role-${index}`}
                  label="Role"
                  value={person.role}
                  onChange={(event) => {
                    const value = event.target.value as ContactRole
                    setPeople((current) => current.map((row) => (
                      row.key === person.key ? { ...row, role: value } : row
                    )))
                  }}
                >
                  {CONTACT_ROLE_OPTIONS.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                label="Phone"
                value={person.phone}
                onChange={(event) => {
                  const value = event.target.value
                  setPeople((current) => current.map((row) => (
                    row.key === person.key ? { ...row, phone: value } : row
                  )))
                }}
                size="small"
                sx={{ flex: '1 1 180px', caretColor: 'text.primary' }}
                inputProps={{ 'aria-label': `Phone ${index + 1}` }}
              />
              <TextField
                label="Email"
                value={person.email}
                onChange={(event) => {
                  const value = event.target.value
                  setPeople((current) => current.map((row) => (
                    row.key === person.key ? { ...row, email: value } : row
                  )))
                }}
                size="small"
                sx={{ flex: '1 1 180px', caretColor: 'text.primary' }}
                inputProps={{ 'aria-label': `Email ${index + 1}` }}
              />
            </Box>
          </Paper>
        ))}
        <Button
          type="button"
          variant="outlined"
          onClick={addPerson}
          data-testid="quick-add-add-person"
          sx={{ cursor: 'pointer' }}
        >
          Add a person
        </Button>
      </Box>
      </Box>

      <FormControl fullWidth required sx={{ mt: 3 }}>
        <InputLabel id="quick-add-pipeline-status-label">Pipeline status</InputLabel>
        <Select
          labelId="quick-add-pipeline-status-label"
          label="Pipeline status"
          value={pipelineStatus}
          onChange={(event) => setPipelineStatus(event.target.value as LeadStatus)}
          disabled={quickAddMutation.isPending}
          inputProps={{ 'aria-label': 'Pipeline status' }}
        >
          {ALL_LEAD_STATUSES.map((status) => (
            <MenuItem key={status} value={status}>
              {LEAD_STATUS_LABELS[status]}
            </MenuItem>
          ))}
        </Select>
        <FormHelperText>
          New properties are saved in this stage. An address already in the system keeps its current stage.
        </FormHelperText>
      </FormControl>

      {pipelineStatus !== 'skip_trace' && (
        <Box
          sx={{ mt: 3, p: 2, border: 1, borderColor: 'divider', borderRadius: 1, cursor: 'auto' }}
          data-testid="quick-add-next-task"
        >
          <Typography variant="subtitle2" gutterBottom>
            Next task
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Optional. Same create flow as Open Tasks on the lead — skip-trace stage queues skip work automatically instead.
          </Typography>
          <Chip
            label={nextTaskEnabled ? 'Include next task' : 'No next task'}
            clickable
            color={nextTaskEnabled ? 'primary' : 'default'}
            variant={nextTaskEnabled ? 'filled' : 'outlined'}
            onClick={() => setNextTaskEnabled((v) => !v)}
            sx={{ mb: 2, cursor: 'pointer' }}
            data-testid="quick-add-next-task-toggle"
          />
          {nextTaskEnabled && (
            <>
              <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                <InputLabel id="quick-add-next-task-type-label">Type</InputLabel>
                <Select
                  labelId="quick-add-next-task-type-label"
                  label="Type"
                  value={nextTaskPreset}
                  onChange={(e) => {
                    const next = e.target.value as CreateTaskPresetId
                    const prevDefault = getCreateTaskPreset(nextTaskPreset).defaultTitle
                    const nextDefault = getCreateTaskPreset(next).defaultTitle
                    setNextTaskPreset(next)
                    if (nextDefault && (!nextTaskTitle.trim() || nextTaskTitle.trim() === prevDefault)) {
                      setNextTaskTitle(nextDefault)
                    } else if (!nextDefault && nextTaskTitle.trim() === prevDefault) {
                      setNextTaskTitle('')
                    }
                  }}
                  inputProps={{ 'data-testid': 'quick-add-next-task-type' }}
                >
                  {CREATE_TASK_PRESETS.map((opt) => (
                    <MenuItem key={opt.id} value={opt.id}>
                      {opt.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                label="Title"
                value={nextTaskTitle}
                onChange={(e) => setNextTaskTitle(e.target.value)}
                fullWidth
                size="small"
                sx={{ mb: 2, caretColor: 'text.primary' }}
                inputProps={{ maxLength: 255, 'data-testid': 'quick-add-next-task-title' }}
              />
              <Box sx={{ mb: 2 }}>
                <FollowUpHorizonControls
                  variant="list"
                  preset={nextTaskDuePreset}
                  customDueDate={nextTaskDueDate}
                  onPresetChange={setNextTaskDuePreset}
                  onCustomDueDateChange={setNextTaskDueDate}
                  testIdPrefix="quick-add-next-task-due"
                  dateLabel="Due date"
                />
              </Box>
              <TextField
                label="Task notes"
                value={nextTaskNotes}
                onChange={(e) => setNextTaskNotes(e.target.value)}
                fullWidth
                size="small"
                multiline
                minRows={2}
                sx={{ mb: 1, caretColor: 'text.primary' }}
                placeholder="Conversation goal or what to cover"
                inputProps={{ 'data-testid': 'quick-add-next-task-notes' }}
              />
            </>
          )}
        </Box>
      )}

      <Button
        type="submit"
        variant="contained"
        size="large"
        disabled={quickAddMutation.isPending}
        startIcon={quickAddMutation.isPending ? <CircularProgress size={18} color="inherit" /> : undefined}
        sx={{ mt: 2, minWidth: { md: 280 }, cursor: 'pointer' }}
      >
        {quickAddMutation.isPending
          ? 'Saving…'
          : pipelineStatus === 'skip_trace'
            ? 'Save to Skip Trace'
            : `Save as ${LEAD_STATUS_LABELS[pipelineStatus]}`}
      </Button>
    </Box>
    )

  return (
    <Dialog
      open
      fullScreen
      onClose={handleClose}
      aria-labelledby="quick-add-dialog-title"
      data-testid="quick-add-dialog"
    >
      <DialogTitle
        id="quick-add-dialog-title"
        component="div"
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1,
          py: 1.5,
        }}
      >
        <Typography component="h1" variant="h6" fontWeight={700}>
          {dialogTitle}
        </Typography>
        <IconButton
          aria-label="Close quick add"
          onClick={handleClose}
          data-testid="quick-add-close"
          edge="end"
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers sx={{ pt: 2.5, px: { xs: 2, md: 4 }, cursor: 'auto' }}>
        {formBody}
      </DialogContent>
    </Dialog>
  )
}

export default QuickAddPage
