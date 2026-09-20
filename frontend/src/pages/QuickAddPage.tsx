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
import CloseIcon from '@mui/icons-material/Close'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import MyLocationIcon from '@mui/icons-material/MyLocation'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import usePlacesAutocomplete from 'use-places-autocomplete'
import { useGoogleMapsLoaded } from '@/context/GoogleMapsContext'
import { leadService } from '@/services/leadApi'
import { commandCenterService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import type { ContactRole, QuickAddPayload, QuickAddResponse } from '@/types'
import { QUICK_ADD_DEAL_SOURCES } from '@/types'
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
  const suggestionsRef = useRef<HTMLUListElement>(null)
  const coordSourceRef = useRef<'gps' | 'place-pending' | 'place' | null>(null)

  const [note, setNote] = useState('')
  const [context, setContext] = useState('')
  const [priority, setPriority] = useState<Priority | null>(null)
  const [dealSource, setDealSource] = useState<string>(QUICK_ADD_DEAL_SOURCES[0])
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
      ? 'Address suggestions loading… (you can still type a full address and save)'
      : 'Start typing for Google address suggestions'

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
      for (const [index, person] of peopleToSave.entries()) {
        const label = [person.firstName, person.lastName].filter(Boolean).join(' ') || 'Contact'
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
          await contactService.linkContactToProperty(result.lead_id, {
            contact_id: created.id,
            role: person.role,
            is_primary: index === 0,
          })
          peopleSaved += 1
        } catch (error) {
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
    if (!street) {
      setAddressError('Property address is required')
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
    quickAddMutation.mutate({
      quickAdd: {
        property_street: street,
        note: note.trim() || null,
        context: context.trim() || null,
        capture_kind: namedPeople.length ? 'lead' : null,
        priority,
        deal_source: dealSource,
        date_identified: dateIdentified || todayIsoDate(),
        capture_latitude: coords?.lat ?? null,
        capture_longitude: coords?.lng ?? null,
        capture_location_label: gpsLabel,
        property_city: parsedAddress.city,
        property_state: parsedAddress.state,
        property_zip: parsedAddress.zip,
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
    setDateIdentified(todayIsoDate())
    setPeople([])
    setPeopleError('')
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

  const intro = 'Save an address you are interested in. Add the people you already know — one property can have more than one — plus where it came from and why.'

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
                  ? 'Added to Skip Trace.'
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
      sx={{ maxWidth: 480, mx: 'auto', pb: 4 }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
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
          label="Property address"
          value={address}
          onChange={(e) => {
            placesRequestIdRef.current += 1
            coordSourceRef.current = null
            setAddress(e.target.value)
            setExistingActionFeedback(null)
            setParsedAddress({ city: null, state: null, zip: null })
            if (e.target.value.trim()) setAddressError('')
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') clearSuggestions()
          }}
          error={!!addressError}
          helperText={addressHelperText}
          required
          fullWidth
          autoComplete="off"
          placeholder="123 Main St, Chicago, IL"
          disabled={quickAddMutation.isPending}
          inputProps={{
            'aria-label': 'Property address',
            'aria-autocomplete': 'list',
            'aria-controls': status === 'OK' ? 'quick-add-suggestions' : undefined,
            'aria-expanded': status === 'OK',
          }}
        />
        {!mapsLoaded && (
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

      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
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
            <FormControl fullWidth size="small" sx={{ mb: 1.5 }}>
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
              fullWidth
              size="small"
              sx={{ mb: 1.5, caretColor: 'text.primary' }}
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
              fullWidth
              size="small"
              sx={{ caretColor: 'text.primary' }}
              inputProps={{ 'aria-label': `Email ${index + 1}` }}
            />
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
        minRows={3}
        sx={{ mb: 2, caretColor: 'text.primary' }}
        placeholder="Anything else to remember"
        inputProps={{ 'aria-label': 'Notes' }}
      />

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Priority
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 3 }}>
        {PRIORITY_OPTIONS.map((opt) => (
          <Chip
            key={opt.value}
            label={opt.label}
            clickable
            color={priority === opt.value ? 'primary' : 'default'}
            variant={priority === opt.value ? 'filled' : 'outlined'}
            onClick={() => setPriority(priority === opt.value ? null : opt.value)}
          />
        ))}
      </Box>

      <Button
        type="submit"
        variant="contained"
        size="large"
        fullWidth
        disabled={quickAddMutation.isPending}
        startIcon={quickAddMutation.isPending ? <CircularProgress size={18} color="inherit" /> : undefined}
      >
        {quickAddMutation.isPending ? 'Saving…' : 'Save to Skip Trace'}
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
      <DialogContent dividers sx={{ pt: 2 }}>
        {formBody}
      </DialogContent>
    </Dialog>
  )
}

export default QuickAddPage
