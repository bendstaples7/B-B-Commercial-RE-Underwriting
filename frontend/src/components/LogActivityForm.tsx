/**
 * LogActivityForm — unified call / note / email activity logging form.
 *
 * Consolidates the former LogCallForm, LogNoteForm, and LogEmailForm into a
 * single component keyed by `mode`. Call mode keeps every prior capability:
 * outcomes (including Not Interested), direction, duration, contact method,
 * mail attribution, complete-task, follow-up cadence, next-step types, and
 * HubSpot task completion. Note and email modes share the same Next-step panel
 * (complete task + follow-up) via ActivityNextStepPanel.
 */
import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  FormHelperText,
  FormLabel,
  InputLabel,
  MenuItem,
  Select,
  Grid,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import type { LeadTask, LeadTimelineEntry, LogCallPayload, LogNotePayload, PropertyContact } from '@/types'
import { callLogService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import channelRoiService from '@/services/channelRoiApi'
import { useQuery } from '@tanstack/react-query'
import {
  ContactMethodFields,
  EMPTY_CONTACT_METHOD,
  type ContactMethodValue,
  contactMethodToCallPayload,
  contactMethodToEmailPayload,
} from '@/components/ContactMethodFields'
import { ActivityNextStepPanel } from '@/components/ActivityNextStepPanel'
import { findCompletableTaskForMode, parseHubSpotTaskId } from '@/utils/callCompletableTask'
import {
  type FollowUpPreset,
  followUpDueForPreset,
  resolveFollowUpDueDate,
} from '@/utils/followUpPresets'
import { addSentFromAddress, getSentFromAddresses } from '@/utils/emailSentFromAddresses'

const MAX_CALL_NOTES_LENGTH = 2000
const MAX_BODY_LENGTH = 5000
const MAX_SUBJECT_LENGTH = 200
const ADD_NEW_SENT_FROM = '__add_new__'

export type LogActivityMode = 'call' | 'note' | 'email'

export type LogCallSavedMeta = {
  completedTaskId?: number
  completedHubSpotTaskId?: number
  warning?: string
}

const ROOT_TESTID: Record<LogActivityMode, string> = {
  call: 'log-call-form',
  note: 'log-note-form',
  email: 'log-email-form',
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

function buildCallMetadataFallback(
  payload: LogCallPayload,
  contactMethod: ContactMethodValue,
  contacts: PropertyContact[],
): Record<string, unknown> {
  const metadata: Record<string, unknown> = {
    outcome: payload.outcome,
    direction: payload.direction ?? 'outbound',
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

function formatEmailNote(subject: string, body: string): string {
  const trimmedSubject = subject.trim()
  const trimmedBody = body.trim()
  if (trimmedSubject) {
    return `[Email] ${trimmedSubject}\n\n${trimmedBody}`
  }
  return `[Email]\n\n${trimmedBody}`
}

function buildEmailMetadataFallback(
  formattedBody: string,
  subject: string,
  sentFromEmail: string,
  contactMethod: ContactMethodValue,
  contacts: PropertyContact[],
): Record<string, unknown> {
  const payload = contactMethodToEmailPayload(contactMethod)
  const trimmedSubject = subject.trim()
  const metadata: Record<string, unknown> = { body: formattedBody }
  if (trimmedSubject) metadata.subject = trimmedSubject
  if (sentFromEmail.trim()) metadata.sent_from_email = sentFromEmail.trim()
  if (payload.contact_id != null) metadata.contact_id = payload.contact_id
  if (payload.contact_email_id != null) metadata.contact_email_id = payload.contact_email_id
  if (payload.email_address) metadata.email_address = payload.email_address
  if (payload.email_label) metadata.email_label = payload.email_label
  const contactName = resolveContactName(contacts, contactMethod.contactId)
  if (contactName) metadata.contact_name = contactName
  return metadata
}

const DIRECTION_OPTIONS: { value: NonNullable<LogCallPayload['direction']>; label: string }[] = [
  { value: 'outbound', label: 'Outbound' },
  { value: 'inbound', label: 'Inbound' },
]

const OUTCOME_OPTIONS: { value: LogCallPayload['outcome']; label: string }[] = [
  { value: 'answered', label: 'Answered' },
  { value: 'voicemail', label: 'Voicemail' },
  { value: 'no_answer', label: 'No Answer' },
  { value: 'busy', label: 'Busy' },
  { value: 'wrong_number', label: 'Wrong Number' },
  { value: 'not_interested', label: 'Not Interested' },
]

export interface LogActivityFormProps {
  mode: LogActivityMode
  leadId: number
  contacts?: PropertyContact[]
  contactsLoading?: boolean
  openTasks?: LeadTask[]
  onSaved: (entry: LeadTimelineEntry, meta?: LogCallSavedMeta) => void
  onCancel?: () => void
}

export interface LogActivityFormHandle {
  focus: () => void
}

export const LogActivityForm = forwardRef<LogActivityFormHandle, LogActivityFormProps>(
  function LogActivityForm(
    { mode, leadId, contacts = [], contactsLoading = false, openTasks = [], onSaved, onCancel },
    ref,
  ) {
    const formRef = useRef<HTMLDivElement>(null)
    const outcomeGroupRef = useRef<HTMLDivElement>(null)

    const completableTask = useMemo(
      () => findCompletableTaskForMode(mode, openTasks),
      [mode, openTasks],
    )
    const hasOpenNonCompletableTasks =
      !completableTask && openTasks.some((t) => t.status === 'open' || t.status === 'overdue')

    const { data: recentMailCampaigns } = useQuery({
      queryKey: ['mail-campaigns-for-lead', leadId],
      queryFn: () => openLetterService.campaignsForLead(leadId),
      enabled: mode === 'call',
    })
    const mailCampaignOptions = mode === 'call' ? (recentMailCampaigns?.campaigns ?? []) : []

    const { data: channelRoiSettings } = useQuery({
      queryKey: ['channel-roi-settings'],
      queryFn: () => channelRoiService.getSettings(),
      enabled: mode === 'call',
      staleTime: 60_000,
    })
    const facebookAttributionEnabled =
      mode === 'call' &&
      Boolean(
        channelRoiSettings?.meta_connected ||
          channelRoiSettings?.has_meta_token ||
          channelRoiSettings?.last_synced_at,
      )
    const { data: facebookCampaignsData, isLoading: facebookCampaignsLoading } = useQuery({
      queryKey: ['facebook-campaigns-for-attribution'],
      queryFn: () => channelRoiService.listFacebookCampaigns(),
      enabled: facebookAttributionEnabled,
    })
    const facebookCampaignOptions = facebookAttributionEnabled
      ? (facebookCampaignsData?.campaigns ?? [])
      : []

    // Call-mode fields
    const [outcome, setOutcome] = useState<LogCallPayload['outcome'] | ''>('')
    const [direction, setDirection] = useState<NonNullable<LogCallPayload['direction']>>('outbound')
    const [duration, setDuration] = useState('')
    const [callNotes, setCallNotes] = useState('')
    const [mailCampaignId, setMailCampaignId] = useState<number | ''>('')
    const [facebookCampaignId, setFacebookCampaignId] = useState<number | ''>('')
    const [completeTask, setCompleteTask] = useState(true)

    // Note/email shared body field
    const [body, setBody] = useState('')
    const [bodyError, setBodyError] = useState<string | null>(null)

    // Email-mode fields
    const [subject, setSubject] = useState('')
    const [sentFromOptions, setSentFromOptions] = useState<string[]>(() =>
      mode === 'email' ? getSentFromAddresses() : [],
    )
    const [sentFromEmail, setSentFromEmail] = useState('')
    const [addingSentFrom, setAddingSentFrom] = useState(false)
    const [newSentFromInput, setNewSentFromInput] = useState('')

    // Shared contact method (phone for call, email for email)
    const [contactMethod, setContactMethod] = useState<ContactMethodValue>(EMPTY_CONTACT_METHOD)

    // Shared next-step / follow-up cadence — default on when a completable task exists
    const [createFollowUp, setCreateFollowUp] = useState(Boolean(completableTask))
    const [followUpPreset, setFollowUpPreset] = useState<FollowUpPreset>('3')
    const [customDueDate, setCustomDueDate] = useState('')
    const [nextStepExpanded, setNextStepExpanded] = useState(false)
    const [nextStepType, setNextStepType] = useState<'call_owner_today' | 'add_to_mail_batch' | 'custom'>('call_owner_today')
    const [customTaskTitle, setCustomTaskTitle] = useState('')

    const [outcomeError, setOutcomeError] = useState<string | null>(null)
    const [durationError, setDurationError] = useState<string | null>(null)
    const [callNotesError, setCallNotesError] = useState<string | null>(null)
    const [followUpError, setFollowUpError] = useState<string | null>(null)
    const [submitError, setSubmitError] = useState<string | null>(null)
    const [submitting, setSubmitting] = useState(false)

    useImperativeHandle(ref, () => ({
      focus: () => {
        if (mode === 'call') {
          const first = outcomeGroupRef.current?.querySelector('button')
          ;(first as HTMLButtonElement | null | undefined)?.focus()
          return
        }
        const testid = mode === 'note' ? 'note-body-input' : 'email-subject-input'
        const input = formRef.current?.querySelector(`[data-testid="${testid}"]`) as HTMLElement | null
        input?.focus()
      },
    }))

    const validateOutcome = (value: string): string | null => {
      if (!value) return 'Outcome is required.'
      return null
    }

    const validateDuration = (value: string): string | null => {
      if (value === '') return null
      const num = Number(value)
      if (!Number.isInteger(num) || num < 1 || num > 999) {
        return 'Duration must be a whole number between 1 and 999.'
      }
      return null
    }

    const validateCallNotes = (value: string): string | null => {
      if (value.length > MAX_CALL_NOTES_LENGTH)
        return `Notes must be ${MAX_CALL_NOTES_LENGTH.toLocaleString()} characters or fewer.`
      return null
    }

    const validateBody = (value: string, label: string): string | null => {
      if (value.trim().length === 0) return `${label} cannot be empty.`
      if (value.length > MAX_BODY_LENGTH)
        return `${label} must be ${MAX_BODY_LENGTH.toLocaleString()} characters or fewer.`
      return null
    }

    const getFollowUpDueDate = (): string | null => {
      if (!createFollowUp) return null
      return resolveFollowUpDueDate(followUpPreset, customDueDate)
    }

    const followUpDuePreview =
      createFollowUp && followUpPreset !== 'custom'
        ? followUpDueForPreset(followUpPreset)
        : null

    const buildFollowUpPayload = (dueDate: string | null) => {
      if (!dueDate) return null
      return {
        title: nextStepType === 'add_to_mail_batch'
          ? 'Add to mail queue'
          : nextStepType === 'custom'
            ? customTaskTitle.trim() || 'Custom task'
            : 'Follow up call',
        due_date: dueDate,
        task_type: nextStepType,
      }
    }

    const resetNextStepState = (nextCompletable: LeadTask | null) => {
      setCreateFollowUp(Boolean(nextCompletable))
      setFollowUpPreset('3')
      setCustomDueDate('')
      setNextStepExpanded(false)
      setNextStepType('call_owner_today')
      setCustomTaskTitle('')
      setCompleteTask(true)
    }

    const buildCompletionIds = () => {
      const completingNativeTask =
        completeTask &&
        completableTask &&
        completableTask.source !== 'hubspot' &&
        typeof completableTask.id === 'number'
      const completedTaskId = completingNativeTask ? (completableTask!.id as number) : null
      const completingHubSpotTask = completeTask && completableTask && completableTask.source === 'hubspot'
      const hubSpotTaskId = completingHubSpotTask ? parseHubSpotTaskId(completableTask!.id) : null
      return { completedTaskId, hubSpotTaskId }
    }

    const maybeCompleteHubSpot = async (
      hubSpotTaskId: number | null,
      softWarning: string,
    ): Promise<{ completedHubSpotTaskId?: number; completionWarning?: string }> => {
      if (hubSpotTaskId == null) return {}
      try {
        await callLogService.markHubSpotTaskDone(leadId, hubSpotTaskId, {
          idNamespace: 'lead_task',
        })
        return { completedHubSpotTaskId: hubSpotTaskId }
      } catch (hubSpotErr) {
        console.error('Activity logged but HubSpot task completion failed:', hubSpotErr)
        return { completionWarning: softWarning }
      }
    }

    const handleAddSentFromAddress = () => {
      const trimmed = newSentFromInput.trim()
      if (!trimmed) return
      const next = addSentFromAddress(trimmed)
      setSentFromOptions(next)
      setSentFromEmail(trimmed)
      setAddingSentFrom(false)
      setNewSentFromInput('')
    }

    // -------------------------------------------------------------------
    // Submit handlers per mode
    // -------------------------------------------------------------------

    const handleCallSubmit = async () => {
      const oErr = validateOutcome(outcome)
      const dErr = validateDuration(duration)
      const nErr = validateCallNotes(callNotes)
      let fErr: string | null = null
      if (createFollowUp && followUpPreset === 'custom' && !customDueDate) {
        fErr = 'Choose a follow-up date.'
      }
      setOutcomeError(oErr)
      setDurationError(dErr)
      setCallNotesError(nErr)
      setFollowUpError(fErr)
      if (oErr || dErr || nErr || fErr) return

      setSubmitError(null)
      setSubmitting(true)

      const followUpDue = getFollowUpDueDate()
      const { completedTaskId, hubSpotTaskId } = buildCompletionIds()

      const payload: LogCallPayload = {
        outcome: outcome as LogCallPayload['outcome'],
        direction,
        duration_minutes: duration !== '' ? Number(duration) : null,
        notes: callNotes.trim() || null,
        mail_campaign_id: mailCampaignId === '' ? null : mailCampaignId,
        facebook_campaign_id: facebookCampaignId === '' ? null : facebookCampaignId,
        ...contactMethodToCallPayload(contactMethod),
        complete_task_id: completedTaskId,
        follow_up: buildFollowUpPayload(followUpDue),
      }

      try {
        const entry = await callLogService.logCall(leadId, payload)

        const { completedHubSpotTaskId, completionWarning } = await maybeCompleteHubSpot(
          hubSpotTaskId,
          'Call saved; the HubSpot task is still open.',
        )

        const directionLabel = direction === 'inbound' ? 'Inbound' : 'Outbound'
        const summaryParts = [`${directionLabel} call: ${payload.outcome}`]
        if (payload.duration_minutes) summaryParts.push(`${payload.duration_minutes} min`)
        if (payload.notes) summaryParts.push(payload.notes.slice(0, 200))
        const summary = summaryParts.join('. ').slice(0, 500)
        const metadataFallback = buildCallMetadataFallback(payload, contactMethod, contacts)
        const savedMeta: LogCallSavedMeta | undefined =
          completedTaskId != null || completedHubSpotTaskId != null || completionWarning
            ? {
                completedTaskId: completedTaskId ?? undefined,
                completedHubSpotTaskId,
                warning: completionWarning,
              }
            : undefined
        onSaved(
          {
            ...entry,
            summary: entry.summary ?? summary,
            event_type: entry.event_type ?? 'call_logged',
            source: entry.source ?? 'manual',
            metadata: entry.metadata ?? metadataFallback,
          },
          savedMeta,
        )
        setOutcome('')
        setDirection('outbound')
        setDuration('')
        setCallNotes('')
        setMailCampaignId('')
        setFacebookCampaignId('')
        setContactMethod(EMPTY_CONTACT_METHOD)
        resetNextStepState(completableTask)
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : 'Failed to log call. Please try again.')
      } finally {
        setSubmitting(false)
      }
    }

    const handleNoteSubmit = async () => {
      const error = validateBody(body, 'Note')
      if (error) {
        setBodyError(error)
        return
      }
      let fErr: string | null = null
      if (createFollowUp && followUpPreset === 'custom' && !customDueDate) {
        fErr = 'Choose a follow-up date.'
      }
      setFollowUpError(fErr)
      if (fErr) return

      setBodyError(null)
      setSubmitError(null)
      setSubmitting(true)

      const followUpDue = getFollowUpDueDate()
      const { completedTaskId, hubSpotTaskId } = buildCompletionIds()
      const payload: LogNotePayload = {
        body,
        complete_task_id: completedTaskId,
        follow_up: buildFollowUpPayload(followUpDue),
      }

      try {
        const entry = await callLogService.logNote(leadId, payload)
        const { completedHubSpotTaskId, completionWarning } = await maybeCompleteHubSpot(
          hubSpotTaskId,
          'Note saved; the HubSpot task is still open.',
        )
        const savedMeta: LogCallSavedMeta | undefined =
          completedTaskId != null || completedHubSpotTaskId != null || completionWarning
            ? {
                completedTaskId: completedTaskId ?? undefined,
                completedHubSpotTaskId,
                warning: completionWarning,
              }
            : undefined
        onSaved(
          {
            ...entry,
            summary: entry.summary ?? body.slice(0, 500),
            event_type: entry.event_type ?? 'note_added',
            source: entry.source ?? 'manual',
            metadata: entry.metadata ?? { body },
          },
          savedMeta,
        )
        setBody('')
        resetNextStepState(completableTask)
      } catch (err) {
        // Preserve form data on server error — do NOT clear body
        setSubmitError(err instanceof Error ? err.message : 'Failed to save note. Please try again.')
      } finally {
        setSubmitting(false)
      }
    }

    const handleEmailSubmit = async () => {
      const error = validateBody(body, 'Notes')
      if (error) {
        setBodyError(error)
        return
      }
      let fErr: string | null = null
      if (createFollowUp && followUpPreset === 'custom' && !customDueDate) {
        fErr = 'Choose a follow-up date.'
      }
      setFollowUpError(fErr)
      if (fErr) return

      setBodyError(null)
      setSubmitError(null)
      setSubmitting(true)

      const followUpDue = getFollowUpDueDate()
      const formattedBody = formatEmailNote(subject, body)
      const { completedTaskId, hubSpotTaskId } = buildCompletionIds()
      const payload: LogNotePayload = {
        body: formattedBody,
        subject: subject.trim() || null,
        sent_from_email: sentFromEmail.trim() || null,
        ...contactMethodToEmailPayload(contactMethod),
        complete_task_id: completedTaskId,
        follow_up: buildFollowUpPayload(followUpDue),
      }

      try {
        const entry = await callLogService.logNote(leadId, payload)
        const { completedHubSpotTaskId, completionWarning } = await maybeCompleteHubSpot(
          hubSpotTaskId,
          'Email saved; the HubSpot task is still open.',
        )
        const metadataFallback = buildEmailMetadataFallback(
          formattedBody,
          subject,
          sentFromEmail,
          contactMethod,
          contacts,
        )
        const savedMeta: LogCallSavedMeta | undefined =
          completedTaskId != null || completedHubSpotTaskId != null || completionWarning
            ? {
                completedTaskId: completedTaskId ?? undefined,
                completedHubSpotTaskId,
                warning: completionWarning,
              }
            : undefined
        onSaved(
          {
            ...entry,
            summary: entry.summary ?? formattedBody.slice(0, 500),
            event_type: entry.event_type ?? 'email_logged',
            source: entry.source ?? 'manual',
            metadata: entry.metadata ?? metadataFallback,
          },
          savedMeta,
        )
        setSubject('')
        setBody('')
        setContactMethod(EMPTY_CONTACT_METHOD)
        resetNextStepState(completableTask)
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : 'Failed to log email. Please try again.')
      } finally {
        setSubmitting(false)
      }
    }

    const handleSubmit = async (e: React.FormEvent) => {
      e.preventDefault()
      if (submitting) return
      if (mode === 'call') await handleCallSubmit()
      else if (mode === 'note') await handleNoteSubmit()
      else await handleEmailSubmit()
    }

    const isCallNotesOverLimit = callNotes.length > MAX_CALL_NOTES_LENGTH
    const isBodyOverLimit = body.length > MAX_BODY_LENGTH

    const nextStepPanel = (
      <ActivityNextStepPanel
        completableTask={completableTask}
        showNoCallTaskHint={mode === 'call'}
        hasOpenNonCompletableTasks={hasOpenNonCompletableTasks}
        completeTask={completeTask}
        onCompleteTaskChange={setCompleteTask}
        createFollowUp={createFollowUp}
        onCreateFollowUpChange={setCreateFollowUp}
        followUpPreset={followUpPreset}
        customDueDate={customDueDate}
        followUpError={followUpError}
        followUpDuePreview={followUpDuePreview}
        onFollowUpPresetChange={(value) => {
          setFollowUpPreset(value)
          setFollowUpError(null)
        }}
        onCustomDueDateChange={(value) => {
          setCustomDueDate(value)
          setFollowUpError(null)
        }}
        nextStepExpanded={nextStepExpanded}
        onToggleNextStepExpanded={() => setNextStepExpanded((expanded) => !expanded)}
        nextStepType={nextStepType}
        onNextStepTypeChange={setNextStepType}
        customTaskTitle={customTaskTitle}
        onCustomTaskTitleChange={setCustomTaskTitle}
      />
    )

    return (
      <Box ref={formRef} component="form" onSubmit={handleSubmit} data-testid={ROOT_TESTID[mode]}>
        {submitError && (
          <Alert
            severity="error"
            sx={{ mb: 1.25 }}
            onClose={() => setSubmitError(null)}
            data-testid={mode === 'call' ? 'call-submit-error' : mode === 'note' ? 'note-submit-error' : 'email-submit-error'}
          >
            {submitError}
          </Alert>
        )}

        <Grid container spacing={2} alignItems="stretch">
          <Grid item xs={12} md={7}>
            {mode === 'call' && (
              <>
                <ContactMethodFields
                  dense
                  mode="phone"
                  contacts={contacts}
                  contactsLoading={contactsLoading}
                  value={contactMethod}
                  onChange={setContactMethod}
                />

                <Box sx={{ mb: 1.25 }} data-testid="call-direction-buttons">
                  <FormLabel id="call-direction-label" sx={{ mb: 0.75, display: 'block', typography: 'body2' }}>
                    Direction
                  </FormLabel>
                  <ToggleButtonGroup
                    exclusive
                    size="small"
                    value={direction}
                    onChange={(_e, next: NonNullable<LogCallPayload['direction']> | null) => {
                      if (next) setDirection(next)
                    }}
                    aria-labelledby="call-direction-label"
                    sx={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 0.5,
                      '& .MuiToggleButtonGroup-grouped': {
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: '4px !important',
                        marginLeft: 0,
                        textTransform: 'none',
                        px: 1.25,
                        py: 0.75,
                        minHeight: 40,
                      },
                    }}
                  >
                    {DIRECTION_OPTIONS.map((opt) => (
                      <ToggleButton key={opt.value} value={opt.value} data-testid={`call-direction-${opt.value}`}>
                        {opt.label}
                      </ToggleButton>
                    ))}
                  </ToggleButtonGroup>
                </Box>

                <Box sx={{ mb: 1.25 }} data-testid="call-outcome-buttons">
                  <FormLabel
                    id="call-outcome-label"
                    error={!!outcomeError}
                    sx={{ mb: 0.75, display: 'block', typography: 'body2' }}
                  >
                    Outcome *
                  </FormLabel>
                  <ToggleButtonGroup
                    ref={outcomeGroupRef}
                    exclusive
                    size="small"
                    value={outcome || null}
                    onChange={(_e, next: LogCallPayload['outcome'] | null) => {
                      if (next) {
                        setOutcome(next)
                        if (outcomeError) setOutcomeError(null)
                      }
                    }}
                    aria-labelledby="call-outcome-label"
                    aria-required
                    aria-invalid={!!outcomeError}
                    aria-describedby={outcomeError ? 'call-outcome-error' : undefined}
                    sx={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 0.5,
                      '& .MuiToggleButtonGroup-grouped': {
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: '4px !important',
                        marginLeft: 0,
                        textTransform: 'none',
                        px: 1.25,
                        py: 0.75,
                        minHeight: 40,
                      },
                    }}
                  >
                    {OUTCOME_OPTIONS.map((opt) => (
                      <ToggleButton key={opt.value} value={opt.value} data-testid={`call-outcome-${opt.value}`}>
                        {opt.label}
                      </ToggleButton>
                    ))}
                  </ToggleButtonGroup>
                  {outcomeError && (
                    <FormHelperText error id="call-outcome-error" data-testid="call-outcome-error">
                      {outcomeError}
                    </FormHelperText>
                  )}
                </Box>

                <TextField
                  label="Duration (min)"
                  type="number"
                  value={duration}
                  onChange={(e) => {
                    setDuration(e.target.value)
                    if (durationError) setDurationError(null)
                  }}
                  error={!!durationError}
                  helperText={durationError ?? undefined}
                  fullWidth
                  size="small"
                  sx={{ mb: 1.25 }}
                  inputProps={{ min: 1, max: 999, step: 1, 'data-testid': 'call-duration-input' }}
                  FormHelperTextProps={
                    durationError ? ({ 'data-testid': 'call-duration-error' } as Record<string, string>) : undefined
                  }
                />

                <TextField
                  label="Notes (optional)"
                  multiline
                  minRows={3}
                  maxRows={5}
                  value={callNotes}
                  onChange={(e) => {
                    setCallNotes(e.target.value)
                    if (callNotesError) setCallNotesError(null)
                  }}
                  error={!!callNotesError || isCallNotesOverLimit}
                  size="small"
                  helperText={
                    callNotesError ?? (
                      <Typography
                        component="span"
                        variant="caption"
                        color={isCallNotesOverLimit ? 'error' : 'text.secondary'}
                        data-testid="call-notes-char-count"
                      >
                        {callNotes.length}/{MAX_CALL_NOTES_LENGTH.toLocaleString()}
                      </Typography>
                    )
                  }
                  fullWidth
                  sx={{ mb: 1.25 }}
                  inputProps={{ 'data-testid': 'call-notes-input' }}
                />

                {mailCampaignOptions.length > 0 && (
                  <FormControl fullWidth sx={{ mb: 1.25 }} size="small">
                    <InputLabel id="mail-campaign-label">Response to mailer? (optional)</InputLabel>
                    <Select
                      labelId="mail-campaign-label"
                      label="Response to mailer? (optional)"
                      value={mailCampaignId}
                      onChange={(e) => setMailCampaignId(e.target.value === '' ? '' : Number(e.target.value))}
                    >
                      <MenuItem value="">— Not mail-related —</MenuItem>
                      {mailCampaignOptions.map((c) => (
                        <MenuItem key={c.id} value={c.id}>
                          {c.submitted_at ? new Date(c.submitted_at).toLocaleDateString() : 'Campaign'}{' '}
                          — {c.template_name || `Template ${c.template_id}`}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                )}

                {facebookCampaignOptions.length > 0 && (
                  <FormControl fullWidth sx={{ mb: 0 }} size="small">
                    <InputLabel id="facebook-campaign-label">
                      Response to Facebook campaign? (optional)
                    </InputLabel>
                    <Select
                      labelId="facebook-campaign-label"
                      label="Response to Facebook campaign? (optional)"
                      value={facebookCampaignId}
                      disabled={facebookCampaignsLoading}
                      onChange={(e) =>
                        setFacebookCampaignId(e.target.value === '' ? '' : Number(e.target.value))
                      }
                    >
                      <MenuItem value="">— Not Facebook-related —</MenuItem>
                      {facebookCampaignOptions.map((c) => (
                        <MenuItem key={c.id} value={c.id}>
                          {c.name || c.meta_campaign_id}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                )}
              </>
            )}

            {mode === 'note' && (
              <TextField
                label="Note"
                multiline
                minRows={4}
                value={body}
                onChange={(e) => {
                  setBody(e.target.value)
                  if (bodyError) setBodyError(null)
                }}
                error={!!bodyError || isBodyOverLimit}
                helperText={
                  bodyError ?? (
                    <Typography
                      component="span"
                      variant="caption"
                      color={isBodyOverLimit ? 'error' : 'text.secondary'}
                      data-testid="note-char-count"
                    >
                      {body.length}/{MAX_BODY_LENGTH.toLocaleString()}
                    </Typography>
                  )
                }
                fullWidth
                sx={{ mb: 2 }}
                inputProps={{ 'data-testid': 'note-body-input' }}
              />
            )}

            {mode === 'email' && (
              <>
                <ContactMethodFields
                  mode="email"
                  contacts={contacts}
                  contactsLoading={contactsLoading}
                  value={contactMethod}
                  onChange={setContactMethod}
                />

                <FormControl fullWidth size="small" sx={{ mb: 2 }}>
                  <InputLabel id="email-sent-from-label">Sent from</InputLabel>
                  <Select
                    labelId="email-sent-from-label"
                    label="Sent from"
                    value={addingSentFrom ? ADD_NEW_SENT_FROM : sentFromEmail}
                    onChange={(e) => {
                      const value = e.target.value
                      if (value === ADD_NEW_SENT_FROM) {
                        setAddingSentFrom(true)
                        return
                      }
                      setSentFromEmail(value)
                    }}
                    data-testid="email-sent-from-select"
                    renderValue={(selected) => {
                      if (selected === ADD_NEW_SENT_FROM) return '+ Add new…'
                      if (!selected) return '— None —'
                      return selected as string
                    }}
                  >
                    <MenuItem value="">— None —</MenuItem>
                    {sentFromOptions.map((address) => (
                      <MenuItem key={address} value={address} data-testid={`email-sent-from-option-${address}`}>
                        {address}
                      </MenuItem>
                    ))}
                    <MenuItem value={ADD_NEW_SENT_FROM} data-testid="email-sent-from-add-new">
                      + Add new…
                    </MenuItem>
                  </Select>
                </FormControl>

                {addingSentFrom && (
                  <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
                    <TextField
                      size="small"
                      fullWidth
                      label="New from-address"
                      value={newSentFromInput}
                      onChange={(e) => setNewSentFromInput(e.target.value)}
                      inputProps={{ 'data-testid': 'email-sent-from-new-input' }}
                    />
                    <Button
                      size="small"
                      variant="contained"
                      onClick={handleAddSentFromAddress}
                      data-testid="email-sent-from-save-new"
                    >
                      Add
                    </Button>
                    <Button
                      size="small"
                      onClick={() => {
                        setAddingSentFrom(false)
                        setNewSentFromInput('')
                      }}
                    >
                      Cancel
                    </Button>
                  </Stack>
                )}

                <TextField
                  label="Email subject"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  fullWidth
                  sx={{ mb: 2 }}
                  inputProps={{ maxLength: MAX_SUBJECT_LENGTH, 'data-testid': 'email-subject-input' }}
                />

                <TextField
                  label="Notes"
                  multiline
                  minRows={4}
                  value={body}
                  onChange={(e) => {
                    setBody(e.target.value)
                    if (bodyError) setBodyError(null)
                  }}
                  error={!!bodyError || isBodyOverLimit}
                  helperText={
                    bodyError ?? (
                      <Typography
                        component="span"
                        variant="caption"
                        color={isBodyOverLimit ? 'error' : 'text.secondary'}
                        data-testid="email-notes-char-count"
                      >
                        {body.length}/{MAX_BODY_LENGTH.toLocaleString()}
                      </Typography>
                    )
                  }
                  fullWidth
                  sx={{ mb: 2 }}
                  inputProps={{ 'data-testid': 'email-notes-input' }}
                />
              </>
            )}
          </Grid>

          <Grid item xs={12} md={5}>{nextStepPanel}</Grid>
        </Grid>

        <Stack
          direction="row"
          spacing={1}
          justifyContent="flex-end"
          sx={{ pt: 1.25, mt: 1.5, borderTop: 1, borderColor: 'divider' }}
        >
          {onCancel && (
            <Button
              size="small"
              onClick={onCancel}
              disabled={submitting}
              data-testid={mode === 'call' ? 'call-cancel-btn' : mode === 'note' ? 'note-cancel-btn' : 'email-cancel-btn'}
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
            data-testid={mode === 'call' ? 'call-save-btn' : mode === 'note' ? 'note-save-btn' : 'email-save-btn'}
          >
            {submitting
              ? 'Saving…'
              : mode === 'call'
                ? (completeTask && completableTask ? 'Log call and complete task' : 'Log call')
                : mode === 'note'
                  ? (completeTask && completableTask ? 'Save note and complete task' : 'Save Note')
                  : (completeTask && completableTask ? 'Log email and complete task' : 'Log email')}
          </Button>
        </Stack>
      </Box>
    )
  },
)

export default LogActivityForm
