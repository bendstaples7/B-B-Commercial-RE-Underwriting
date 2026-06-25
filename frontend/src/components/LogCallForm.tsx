/**
 * LogCallForm — call outcome + duration + notes form for a lead.
 *
 * Requirements: 9.2, 9.3, 9.4, 22.1
 */
import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import type { LeadTimelineEntry, LogCallPayload, PropertyContact } from '@/types'
import { callLogService } from '@/services/api'
import {
  ContactMethodFields,
  EMPTY_CONTACT_METHOD,
  type ContactMethodValue,
  contactMethodToCallPayload,
} from '@/components/ContactMethodFields'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_NOTES_LENGTH = 2000

function resolveContactName(
  contacts: PropertyContact[],
  contactId: number | null,
): string | null {
  if (contactId == null) return null
  const contact = contacts.find((c) => c.id === contactId)
  if (!contact) return null
  const name = [contact.first_name, contact.last_name].filter(Boolean).join(' ')
  return name || null
}

function buildCallMetadataFallback(
  payload: LogCallPayload,
  contactMethod: ContactMethodValue,
  contacts: PropertyContact[],
): Record<string, unknown> {
  const metadata: Record<string, unknown> = {
    outcome: payload.outcome,
  }
  if (payload.duration_minutes != null) metadata.duration_minutes = payload.duration_minutes
  if (payload.notes) metadata.notes = payload.notes
  if (payload.contact_id != null) metadata.contact_id = payload.contact_id
  if (payload.contact_phone_id != null) metadata.contact_phone_id = payload.contact_phone_id
  if (payload.phone_number) metadata.phone_number = payload.phone_number
  if (payload.phone_label) metadata.phone_label = payload.phone_label
  const contactName = resolveContactName(contacts, contactMethod.contactId)
  if (contactName) metadata.contact_name = contactName
  return metadata
}

const OUTCOME_OPTIONS: { value: LogCallPayload['outcome']; label: string }[] = [
  { value: 'answered', label: 'Answered' },
  { value: 'voicemail', label: 'Voicemail' },
  { value: 'no_answer', label: 'No Answer' },
  { value: 'busy', label: 'Busy' },
  { value: 'wrong_number', label: 'Wrong Number' },
]

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface LogCallFormProps {
  leadId: number
  contacts?: PropertyContact[]
  contactsLoading?: boolean
  onSaved: (entry: LeadTimelineEntry) => void
  onCancel?: () => void
}

export interface LogCallFormHandle {
  focus: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * LogCallForm renders a call outcome dropdown, optional duration field (1–999),
 * and optional notes textarea (max 2,000 chars). Shows validation errors for
 * missing outcome or invalid duration. Preserves form data on server error.
 */
export const LogCallForm = forwardRef<LogCallFormHandle, LogCallFormProps>(function LogCallForm(
  { leadId, contacts = [], contactsLoading = false, onSaved, onCancel },
  ref,
) {
  const formRef = useRef<HTMLDivElement>(null)
  const outcomeInputRef = useRef<HTMLInputElement>(null)
  const [outcome, setOutcome] = useState<LogCallPayload['outcome'] | ''>('')
  const [duration, setDuration] = useState('')
  const [notes, setNotes] = useState('')
  const [contactMethod, setContactMethod] = useState<ContactMethodValue>(EMPTY_CONTACT_METHOD)

  const [outcomeError, setOutcomeError] = useState<string | null>(null)
  const [durationError, setDurationError] = useState<string | null>(null)
  const [notesError, setNotesError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useImperativeHandle(ref, () => ({
    focus: () => {
      outcomeInputRef.current?.focus()
    },
  }))

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  const validateOutcome = (value: string): string | null => {
    if (!value) return 'Outcome is required.'
    return null
  }

  const validateDuration = (value: string): string | null => {
    if (value === '') return null // optional
    const num = Number(value)
    if (!Number.isInteger(num) || num < 1 || num > 999) {
      return 'Duration must be a whole number between 1 and 999.'
    }
    return null
  }

  const validateNotes = (value: string): string | null => {
    if (value.length > MAX_NOTES_LENGTH)
      return `Notes must be ${MAX_NOTES_LENGTH.toLocaleString()} characters or fewer.`
    return null
  }

  const validateAll = (): boolean => {
    const oErr = validateOutcome(outcome)
    const dErr = validateDuration(duration)
    const nErr = validateNotes(notes)

    setOutcomeError(oErr)
    setDurationError(dErr)
    setNotesError(nErr)

    return !oErr && !dErr && !nErr
  }

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleOutcomeChange = (value: string) => {
    setOutcome(value as LogCallPayload['outcome'] | '')
    if (outcomeError) setOutcomeError(null)
  }

  const handleDurationChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setDuration(e.target.value)
    if (durationError) setDurationError(null)
  }

  const handleNotesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setNotes(e.target.value)
    if (notesError) setNotesError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validateAll()) return

    setSubmitError(null)
    setSubmitting(true)

    const payload: LogCallPayload = {
      outcome: outcome as LogCallPayload['outcome'],
      duration_minutes: duration !== '' ? Number(duration) : null,
      notes: notes.trim() || null,
      ...contactMethodToCallPayload(contactMethod),
    }

    try {
      const entry = await callLogService.logCall(leadId, payload)
      const summaryParts = [`Call logged: ${payload.outcome}`]
      if (payload.duration_minutes) {
        summaryParts.push(`${payload.duration_minutes} min`)
      }
      if (payload.notes) {
        summaryParts.push(payload.notes.slice(0, 200))
      }
      const summary = summaryParts.join('. ').slice(0, 500)
      const metadataFallback = buildCallMetadataFallback(payload, contactMethod, contacts)
      onSaved({
        ...entry,
        summary: entry.summary ?? summary,
        event_type: entry.event_type ?? 'call_logged',
        source: entry.source ?? 'manual',
        metadata: entry.metadata ?? metadataFallback,
      })
      setOutcome('')
      setDuration('')
      setNotes('')
      setContactMethod(EMPTY_CONTACT_METHOD)
    } catch (err) {
      // Preserve form data on server error — do NOT clear fields
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to log call. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isNotesOverLimit = notes.length > MAX_NOTES_LENGTH

  return (
    <Box
      ref={formRef}
      component="form"
      onSubmit={handleSubmit}
      data-testid="log-call-form"
    >
      {/* Server-level error */}
      {submitError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          onClose={() => setSubmitError(null)}
          data-testid="call-submit-error"
        >
          {submitError}
        </Alert>
      )}

      <ContactMethodFields
        mode="phone"
        contacts={contacts}
        contactsLoading={contactsLoading}
        value={contactMethod}
        onChange={setContactMethod}
      />

      {/* Outcome dropdown */}
      <FormControl
        fullWidth
        error={!!outcomeError}
        sx={{ mb: 2 }}
      >
        <InputLabel id="call-outcome-label">Outcome *</InputLabel>
        <Select
          inputRef={outcomeInputRef}
          labelId="call-outcome-label"
          label="Outcome *"
          value={outcome}
          onChange={(e) => handleOutcomeChange(e.target.value)}
          SelectDisplayProps={{ 'data-testid': 'call-outcome-select' } as React.HTMLAttributes<HTMLDivElement>}
        >
          {OUTCOME_OPTIONS.map((opt) => (
            <MenuItem key={opt.value} value={opt.value}>
              {opt.label}
            </MenuItem>
          ))}
        </Select>
        {outcomeError && (
          <FormHelperText data-testid="call-outcome-error">{outcomeError}</FormHelperText>
        )}
      </FormControl>

      {/* Duration field */}
      <TextField
        label="Duration (minutes, optional)"
        type="number"
        value={duration}
        onChange={handleDurationChange}
        error={!!durationError}
        fullWidth
        size="small"
        sx={{ mb: 2 }}
        inputProps={{
          min: 1,
          max: 999,
          step: 1,
          'data-testid': 'call-duration-input',
        }}
      />
      {durationError && (
        <Typography
          variant="caption"
          color="error"
          display="block"
          sx={{ mt: -1.5, mb: 2, ml: 1.75 }}
          data-testid="call-duration-error"
        >
          {durationError}
        </Typography>
      )}

      {/* Notes textarea */}
      <TextField
        label="Notes (optional)"
        multiline
        minRows={3}
        value={notes}
        onChange={handleNotesChange}
        error={!!notesError || isNotesOverLimit}
        helperText={
          notesError ?? (
            <Typography
              component="span"
              variant="caption"
              color={isNotesOverLimit ? 'error' : 'text.secondary'}
              data-testid="call-notes-char-count"
            >
              {notes.length}/{MAX_NOTES_LENGTH.toLocaleString()}
            </Typography>
          )
        }
        fullWidth
        sx={{ mb: 2 }}
        inputProps={{ 'data-testid': 'call-notes-input' }}
      />

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        {onCancel && (
          <Button
            size="small"
            onClick={onCancel}
            disabled={submitting}
            data-testid="call-cancel-btn"
          >
            Cancel
          </Button>
        )}
        <Button
          type="submit"
          variant="contained"
          size="small"
          disabled={submitting}
          startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : undefined}
          data-testid="call-save-btn"
        >
          {submitting ? 'Saving…' : 'Log Call'}
        </Button>
      </Stack>
    </Box>
  )
})

export default LogCallForm
