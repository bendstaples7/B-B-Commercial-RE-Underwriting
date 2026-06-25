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
import type { LeadTimelineEntry, PropertyContact } from '@/types'
import { callLogService } from '@/services/api'
import {
  ContactMethodFields,
  EMPTY_CONTACT_METHOD,
  type ContactMethodValue,
  contactMethodToEmailPayload,
} from '@/components/ContactMethodFields'

const MAX_SUBJECT_LENGTH = 200
const MAX_BODY_LENGTH = 5000

export interface LogEmailFormProps {
  leadId: number
  contacts?: PropertyContact[]
  contactsLoading?: boolean
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

function buildEmailMetadataFallback(
  formattedBody: string,
  subject: string,
  contactMethod: ContactMethodValue,
  contacts: PropertyContact[],
): Record<string, unknown> {
  const payload = contactMethodToEmailPayload(contactMethod)
  const trimmedSubject = subject.trim()
  const metadata: Record<string, unknown> = { body: formattedBody }
  if (trimmedSubject) metadata.subject = trimmedSubject
  if (payload.contact_id != null) metadata.contact_id = payload.contact_id
  if (payload.contact_email_id != null) metadata.contact_email_id = payload.contact_email_id
  if (payload.email_address) metadata.email_address = payload.email_address
  if (payload.email_label) metadata.email_label = payload.email_label
  const contactName = resolveContactName(contacts, contactMethod.contactId)
  if (contactName) metadata.contact_name = contactName
  return metadata
}

export const LogEmailForm = forwardRef<LogEmailFormHandle, LogEmailFormProps>(function LogEmailForm(
  { leadId, contacts = [], contactsLoading = false, onSaved, onCancel },
  ref,
) {
  const formRef = useRef<HTMLDivElement>(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [contactMethod, setContactMethod] = useState<ContactMethodValue>(EMPTY_CONTACT_METHOD)
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
      const formattedBody = formatEmailNote(subject, body)
      const entry = await callLogService.logNote(leadId, {
        body: formattedBody,
        subject: subject.trim() || null,
        ...contactMethodToEmailPayload(contactMethod),
      })
      const metadataFallback = buildEmailMetadataFallback(
        formattedBody,
        subject,
        contactMethod,
        contacts,
      )
      onSaved({
        ...entry,
        summary: entry.summary ?? formattedBody.slice(0, 500),
        event_type: entry.event_type ?? 'email_logged',
        source: entry.source ?? 'manual',
        metadata: entry.metadata ?? metadataFallback,
      })
      setSubject('')
      setBody('')
      setContactMethod(EMPTY_CONTACT_METHOD)
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

      <ContactMethodFields
        mode="email"
        contacts={contacts}
        contactsLoading={contactsLoading}
        value={contactMethod}
        onChange={setContactMethod}
      />

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
