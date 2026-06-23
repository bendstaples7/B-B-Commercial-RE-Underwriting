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
import type { LeadTimelineEntry, LogCallPayload } from '@/types'
import { callLogService } from '@/services/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_NOTES_LENGTH = 2000

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
  { leadId, onSaved, onCancel },
  ref,
) {
  const formRef = useRef<HTMLDivElement>(null)
  const [outcome, setOutcome] = useState<LogCallPayload['outcome'] | ''>('')
  const [duration, setDuration] = useState('')
  const [notes, setNotes] = useState('')

  const [outcomeError, setOutcomeError] = useState<string | null>(null)
  const [durationError, setDurationError] = useState<string | null>(null)
  const [notesError, setNotesError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useImperativeHandle(ref, () => ({
    focus: () => {
      const select = formRef.current?.querySelector('[data-testid="call-outcome-select"]') as HTMLElement | null
      select?.focus()
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
    }

    try {
      const entry = await callLogService.logCall(leadId, payload)
      onSaved(entry)
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

      {/* Outcome dropdown */}
      <FormControl
        fullWidth
        error={!!outcomeError}
        sx={{ mb: 2 }}
      >
        <InputLabel id="call-outcome-label">Outcome *</InputLabel>
        <Select
          labelId="call-outcome-label"
          label="Outcome *"
          value={outcome}
          onChange={(e) => handleOutcomeChange(e.target.value)}
          SelectDisplayProps={{ 'data-testid': 'call-outcome-select' } as any}
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
