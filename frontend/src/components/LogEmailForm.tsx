/**
 * LogEmailForm — log an outbound email on a lead (stored as a timeline note).
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

const MAX_SUBJECT_LENGTH = 200
const MAX_BODY_LENGTH = 5000

export interface LogEmailFormProps {
  leadId: number
  onSaved: (entry: LeadTimelineEntry) => void
  onCancel?: () => void
}

export interface LogEmailFormHandle {
  focus: () => void
}

function formatEmailNote(subject: string, body: string): string {
  const trimmedSubject = subject.trim()
  const trimmedBody = body.trim()
  if (trimmedSubject) {
    return `[Email] ${trimmedSubject}\n\n${trimmedBody}`
  }
  return `[Email]\n\n${trimmedBody}`
}

export const LogEmailForm = forwardRef<LogEmailFormHandle, LogEmailFormProps>(function LogEmailForm(
  { leadId, onSaved, onCancel },
  ref,
) {
  const formRef = useRef<HTMLDivElement>(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [bodyError, setBodyError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useImperativeHandle(ref, () => ({
    focus: () => {
      const input = formRef.current?.querySelector('[data-testid="email-subject-input"]') as HTMLElement | null
      input?.focus()
    },
  }))

  const validate = (value: string): string | null => {
    if (value.trim().length === 0) return 'Email body cannot be empty.'
    if (value.length > MAX_BODY_LENGTH) {
      return `Email body must be ${MAX_BODY_LENGTH.toLocaleString()} characters or fewer.`
    }
    return null
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
      const entry = await callLogService.logNote(leadId, {
        body: formatEmailNote(subject, body),
      })
      onSaved(entry)
      setSubject('')
      setBody('')
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to save email. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const isOverLimit = body.length > MAX_BODY_LENGTH

  return (
    <Box
      ref={formRef}
      component="form"
      onSubmit={handleSubmit}
      data-testid="log-email-form"
    >
      {submitError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          onClose={() => setSubmitError(null)}
          data-testid="email-submit-error"
        >
          {submitError}
        </Alert>
      )}

      <TextField
        label="Subject (optional)"
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        fullWidth
        sx={{ mb: 2 }}
        inputProps={{ maxLength: MAX_SUBJECT_LENGTH, 'data-testid': 'email-subject-input' }}
      />

      <TextField
        label="Email body"
        multiline
        minRows={4}
        value={body}
        onChange={(e) => {
          setBody(e.target.value)
          if (bodyError) setBodyError(null)
        }}
        error={!!bodyError || isOverLimit}
        helperText={
          bodyError ?? (
            <Typography
              component="span"
              variant="caption"
              color={isOverLimit ? 'error' : 'text.secondary'}
              data-testid="email-char-count"
            >
              {body.length}/{MAX_BODY_LENGTH.toLocaleString()}
            </Typography>
          )
        }
        fullWidth
        sx={{ mb: 2 }}
        inputProps={{ 'data-testid': 'email-body-input' }}
      />

      <Stack direction="row" spacing={1} justifyContent="flex-end">
        {onCancel && (
          <Button size="small" onClick={onCancel} disabled={submitting} data-testid="email-cancel-btn">
            Cancel
          </Button>
        )}
        <Button
          type="submit"
          variant="contained"
          size="small"
          disabled={submitting}
          startIcon={submitting ? <CircularProgress size={14} color="inherit" /> : undefined}
          data-testid="email-save-btn"
        >
          {submitting ? 'Saving…' : 'Save Email'}
        </Button>
      </Stack>
    </Box>
  )
})

export default LogEmailForm
