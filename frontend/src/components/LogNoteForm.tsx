/**
 * LogNoteForm — free-text note entry form for a lead.
 *
 * Requirements: 9.1, 21.1
 */
import { forwardRef, useImperativeHandle, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import type { LeadTimelineEntry } from '@/types'
import { callLogService } from '@/services/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_NOTE_LENGTH = 5000

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface LogNoteFormProps {
  leadId: number
  onSaved: (entry: LeadTimelineEntry) => void
  onCancel?: () => void
}

export interface LogNoteFormHandle {
  focus: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * LogNoteForm renders a free-text textarea (max 5,000 chars) with a character
 * count display, Save button, and validation errors for empty or over-limit
 * submissions. Form data is preserved on server error.
 */
export const LogNoteForm = forwardRef<LogNoteFormHandle, LogNoteFormProps>(function LogNoteForm(
  { leadId, onSaved, onCancel },
  ref,
) {
  const formRef = useRef<HTMLDivElement>(null)
  const [body, setBody] = useState('')
  const [bodyError, setBodyError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useImperativeHandle(ref, () => ({
    focus: () => {
      const input = formRef.current?.querySelector('[data-testid="note-body-input"]') as HTMLElement | null
      input?.focus()
    },
  }))

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  const validate = (value: string): string | null => {
    if (value.trim().length === 0) return 'Note cannot be empty.'
    if (value.length > MAX_NOTE_LENGTH)
      return `Note must be ${MAX_NOTE_LENGTH.toLocaleString()} characters or fewer.`
    return null
  }

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleBodyChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setBody(e.target.value)
    if (bodyError) setBodyError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitting) return

    const error = validate(body)
    if (error) {
      setBodyError(error)
      return
    }

    setBodyError(null)
    setSubmitError(null)
    setSubmitting(true)

    try {
      const entry = await callLogService.logNote(leadId, { body })
      onSaved({
        ...entry,
        summary: entry.summary ?? body.slice(0, 500),
        event_type: entry.event_type ?? 'note_added',
        source: entry.source ?? 'manual',
        metadata: entry.metadata ?? { body },
      })
      setBody('')
    } catch (err) {
      // Preserve form data on server error — do NOT clear body
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to save note. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isOverLimit = body.length > MAX_NOTE_LENGTH

  return (
    <Box
      ref={formRef}
      component="form"
      onSubmit={handleSubmit}
      data-testid="log-note-form"
    >
      {/* Server-level error */}
      {submitError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          onClose={() => setSubmitError(null)}
          data-testid="note-submit-error"
        >
          {submitError}
        </Alert>
      )}

      <TextField
        label="Note"
        multiline
        minRows={4}
        value={body}
        onChange={handleBodyChange}
        error={!!bodyError || isOverLimit}
        helperText={
          bodyError ?? (
            <Typography
              component="span"
              variant="caption"
              color={isOverLimit ? 'error' : 'text.secondary'}
              data-testid="note-char-count"
            >
              {body.length}/{MAX_NOTE_LENGTH.toLocaleString()}
            </Typography>
          )
        }
        fullWidth
        sx={{ mb: 2 }}
        inputProps={{ 'data-testid': 'note-body-input' }}
      />

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        {onCancel && (
          <Button
            size="small"
            onClick={onCancel}
            disabled={submitting}
            data-testid="note-cancel-btn"
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
          data-testid="note-save-btn"
        >
          {submitting ? 'Saving…' : 'Save Note'}
        </Button>
      </Stack>
    </Box>
  )
})

export default LogNoteForm
