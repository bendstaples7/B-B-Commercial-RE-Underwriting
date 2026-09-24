/**
 * LogActivityForm — unified call / note / email / meeting activity logging form.
 *
 * Consolidates the former LogCallForm, LogNoteForm, and LogEmailForm into a
 * single component keyed by `mode`. Call mode keeps every prior capability:
 * outcomes (including Not Interested), direction, duration, contact method,
 * mail attribution, complete-task, follow-up cadence, next-step types, and
 * HubSpot task completion. Note, email, and meeting modes share the same
 * Next-step panel (complete task + follow-up) via ActivityNextStepPanel.
 */
import { forwardRef, useImperativeHandle, useMemo, useRef, useState, type InputHTMLAttributes } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormHelperText,
  FormLabel,
  InputLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Select,
  Grid,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import type { LeadTask, LeadTimelineEntry, LogCallPayload, LogNotePayload, PropertyContact } from '@/types'
import { callLogService, leadTaskService } from '@/services/api'
import openLetterService, { type MailCampaign } from '@/services/openLetterApi'
import channelRoiService from '@/services/channelRoiApi'
import { useQuery } from '@tanstack/react-query'
import {
  ContactMethodFields,
  EMPTY_CONTACT_METHOD,
  METHOD_OTHER,
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
import {
  nextStepTypeFromTask,
  resolveCreateTaskPayload,
  type CreateTaskPresetId,
} from '@/utils/createTaskPresets'
import { addSentFromAddress, getSentFromAddresses } from '@/utils/emailSentFromAddresses'
import { extractPhoneDigitsFromText, normalizePhoneDigits } from '@/utils/phone'
import { formatDate } from '@/utils/formatters'

const MAX_CALL_NOTES_LENGTH = 2000
const MAX_BODY_LENGTH = 5000
const MAX_SUBJECT_LENGTH = 200
const ADD_NEW_SENT_FROM = '__add_new__'

type MailSourceChoice = 'suggested' | 'none' | number

function mailerBatchLabel(campaign: MailCampaign): string {
  const when = campaign.submitted_at ? formatDate(campaign.submitted_at) : 'Recent batch'
  const name =
    campaign.template_name ||
    (campaign.template_id != null ? `Template ${campaign.template_id}` : `Batch ${campaign.id}`)
  return `${when} — ${name}`
}

function resolveMailerChoice(choice: MailSourceChoice, campaigns: MailCampaign[]): number | null {
  if (campaigns.length === 0 || choice === 'none') return null
  if (typeof choice === 'number') {
    return campaigns.some((c) => c.id === choice) ? choice : null
  }
  return campaigns[0].id
}

function MailerResponseSourceConfirm({
  campaigns,
  choice,
  onChange,
  heading,
}: {
  campaigns: MailCampaign[]
  choice: MailSourceChoice
  onChange: (next: MailSourceChoice) => void
  heading: string
}) {
  if (campaigns.length === 0) return null
  const selected = resolveMailerChoice(choice, campaigns)
  const value = selected == null ? 'none' : String(selected)
  return (
    <FormControl
      component="fieldset"
      fullWidth
      sx={{ mb: 1.25, cursor: 'default' }}
      data-testid="mail-response-source"
    >
      <FormLabel id="mail-response-source-label" sx={{ mb: 0.5, display: 'block', typography: 'body2' }}>
        {heading}
      </FormLabel>
      <RadioGroup
        aria-labelledby="mail-response-source-label"
        value={value}
        onChange={(e) => {
          const next = e.target.value
          onChange(next === 'none' ? 'none' : Number(next))
        }}
      >
        {campaigns.map((c) => (
          <FormControlLabel
            key={c.id}
            value={String(c.id)}
            control={
              <Radio
                size="small"
                inputProps={{
                  'data-testid': `mail-response-source-${c.id}`,
                } as InputHTMLAttributes<HTMLInputElement>}
              />
            }
            label={`Direct mail — ${mailerBatchLabel(c)}`}
          />
        ))}
        <FormControlLabel
          value="none"
          control={<Radio size="small" inputProps={{ 'data-testid': 'mail-response-source-none' } as InputHTMLAttributes<HTMLInputElement>} />}
          label="Not from a mailer"
        />
      </RadioGroup>
    </FormControl>
  )
}

export type LogActivityMode = 'call' | 'note' | 'email' | 'meeting'

export type LogCallSavedMeta = {
  completedTaskId?: number
  completedHubSpotTaskId?: number
  warning?: string
}

const ROOT_TESTID: Record<LogActivityMode, string> = {
  call: 'log-call-form',
  note: 'log-note-form',
  email: 'log-email-form',
  meeting: 'log-meeting-form',
}

const SUBMIT_ERROR_TESTID: Record<LogActivityMode, string> = {
  call: 'call-submit-error',
  note: 'note-submit-error',
  email: 'email-submit-error',
  meeting: 'meeting-submit-error',
}

const CANCEL_BTN_TESTID: Record<LogActivityMode, string> = {
  call: 'call-cancel-btn',
  note: 'note-cancel-btn',
  email: 'email-cancel-btn',
  meeting: 'meeting-cancel-btn',
}

const SAVE_BTN_TESTID: Record<LogActivityMode, string> = {
  call: 'call-save-btn',
  note: 'note-save-btn',
  email: 'email-save-btn',
  meeting: 'meeting-save-btn',
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

export type LogActivityTaskEdit = {
  task: LeadTask
  note?: string
  phoneDigits?: string | null
}

export interface LogActivityFormProps {
  mode: LogActivityMode
  leadId: number
  contacts?: PropertyContact[]
  contactsLoading?: boolean
  openTasks?: LeadTask[]
  /** Digits from recommended outreach / open call task — prefer in phone picker. */
  preferredPhoneDigits?: string | null
  /** When set, Save updates this task instead of logging a new activity. */
  editTask?: LogActivityTaskEdit | null
  onSaved: (entry: LeadTimelineEntry, meta?: LogCallSavedMeta) => void
  onTaskUpdated?: (task: LeadTask) => void
  onCancel?: () => void
}

function contactMethodFromPhoneDigits(phoneDigits: string | null | undefined): ContactMethodValue {
  const raw = (phoneDigits ?? '').trim()
  if (!raw || normalizePhoneDigits(raw).length < 7) return EMPTY_CONTACT_METHOD
  return {
    ...EMPTY_CONTACT_METHOD,
    methodKey: METHOD_OTHER,
    methodValue: raw,
  }
}

export interface LogActivityFormHandle {
  focus: () => void
}

export const LogActivityForm = forwardRef<LogActivityFormHandle, LogActivityFormProps>(
  function LogActivityForm(
    {
      mode,
      leadId,
      contacts = [],
      contactsLoading = false,
      openTasks = [],
      preferredPhoneDigits = null,
      editTask = null,
      onSaved,
      onTaskUpdated,
      onCancel,
    },
    ref,
  ) {
    const formRef = useRef<HTMLDivElement>(null)
    const outcomeGroupRef = useRef<HTMLDivElement>(null)
    const isEditingTask = Boolean(editTask?.task)

    const completableTask = useMemo(
      () => findCompletableTaskForMode(mode, openTasks),
      [mode, openTasks],
    )
    const [inboundText, setInboundText] = useState(false)
    const [mailSourceChoice, setMailSourceChoice] = useState<MailSourceChoice>('suggested')
    const resolvedPreferredPhoneDigits = useMemo(() => {
      const fromEdit = normalizePhoneDigits(editTask?.phoneDigits)
      if (fromEdit.length >= 7) return fromEdit
      if (mode !== 'call' && !editTask) return null
      // Prefer canonical dial_target digits (passed as preferredPhoneDigits)
      // over task-title parsing so Log Call cannot invent a parallel ranking.
      const fromProp = normalizePhoneDigits(preferredPhoneDigits)
      if (fromProp.length >= 7) return fromProp
      if (mode !== 'call') return fromProp || null
      return extractPhoneDigitsFromText(completableTask?.title)
    }, [mode, completableTask?.title, preferredPhoneDigits, editTask])
    const hasOpenNonCompletableTasks =
      !completableTask && openTasks.some((t) => t.status === 'open' || t.status === 'overdue')

    const {
      data: recentMailCampaigns,
      isLoading: mailCampaignsLoading,
      isError: mailCampaignsError,
    } = useQuery({
      queryKey: ['mail-campaigns-for-lead', leadId],
      queryFn: () => openLetterService.campaignsForLead(leadId),
      enabled: mode === 'call' || (mode === 'note' && inboundText && !isEditingTask),
    })
    const mailCampaignOptions =
      mode === 'call' || (mode === 'note' && inboundText)
        ? (recentMailCampaigns?.campaigns ?? [])
        : []

    const { data: channelRoiSettings } = useQuery({
      queryKey: ['channel-roi-settings'],
      queryFn: () => channelRoiService.getSettings(),
      enabled: mode === 'call',
      staleTime: 0,
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
    const [completeTask, setCompleteTask] = useState(!editTask)

    // Note/email shared body field
    const [body, setBody] = useState(() => editTask?.note ?? '')
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
    const [contactMethod, setContactMethod] = useState<ContactMethodValue>(() =>
      contactMethodFromPhoneDigits(editTask?.phoneDigits ?? preferredPhoneDigits),
    )

    // Shared next-step / follow-up cadence — default on when a completable task exists
    const [createFollowUp, setCreateFollowUp] = useState(Boolean(editTask) || Boolean(completableTask))
    const [followUpPreset, setFollowUpPreset] = useState<FollowUpPreset>(editTask ? 'custom' : '3')
    const [customDueDate, setCustomDueDate] = useState(() => editTask?.task.due_date ?? '')
    const [nextStepExpanded, setNextStepExpanded] = useState(Boolean(editTask))
    const [nextStepType, setNextStepType] = useState<CreateTaskPresetId>(() =>
      editTask ? nextStepTypeFromTask(editTask.task) : 'call_owner_today',
    )
    const [customTaskTitle, setCustomTaskTitle] = useState(() => editTask?.task.title ?? '')
    const [editTaskNotes, setEditTaskNotes] = useState(() => editTask?.task.notes ?? '')
    const [followUpNotes, setFollowUpNotes] = useState('')

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
        const testid =
          mode === 'note'
            ? 'note-body-input'
            : mode === 'meeting'
              ? 'meeting-notes-input'
              : 'email-subject-input'
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
      const { title, task_type } = resolveCreateTaskPayload(
        nextStepType,
        nextStepType === 'custom' ? customTaskTitle : '',
      )
      return {
        title,
        due_date: dueDate,
        task_type,
        notes: followUpNotes.trim() || null,
      }
    }

    const resetNextStepState = (nextCompletable: LeadTask | null) => {
      setCreateFollowUp(Boolean(nextCompletable))
      setFollowUpPreset('3')
      setCustomDueDate('')
      setNextStepExpanded(false)
      setNextStepType('call_owner_today')
      setCustomTaskTitle('')
      setFollowUpNotes('')
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
      if (direction === 'inbound' && mailCampaignsLoading) {
        setSubmitError('Still checking recent mailers. Save again in a moment.')
        return
      }
      if (direction === 'inbound' && mailCampaignsError) {
        setSubmitError('Could not load recent mailers. Save again when they appear.')
        return
      }

      setSubmitError(null)
      setSubmitting(true)

      const followUpDue = getFollowUpDueDate()
      const { completedTaskId, hubSpotTaskId } = buildCompletionIds()

      const payload: LogCallPayload = {
        outcome: outcome as LogCallPayload['outcome'],
        direction,
        duration_minutes: duration !== '' ? Number(duration) : null,
        notes: callNotes.trim() || null,
        mail_campaign_id:
          direction === 'inbound'
            ? resolveMailerChoice(mailSourceChoice, mailCampaignOptions)
            : mailCampaignId === ''
              ? null
              : mailCampaignId,
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
        setMailSourceChoice('suggested')
        setFacebookCampaignId('')
        setContactMethod(EMPTY_CONTACT_METHOD)
        resetNextStepState(completableTask)
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : 'Failed to log call. Please try again.')
      } finally {
        setSubmitting(false)
      }
    }

    const handleNoteLikeSubmit = async (kind: 'note' | 'meeting') => {
      const error = validateBody(body, kind === 'meeting' ? 'Notes' : 'Note')
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
      if (kind === 'note' && inboundText && mailCampaignsLoading) {
        setSubmitError('Still checking recent mailers. Save again in a moment.')
        return
      }
      if (kind === 'note' && inboundText && mailCampaignsError) {
        setSubmitError('Could not load recent mailers. Save again when they appear.')
        return
      }

      setBodyError(null)
      setSubmitError(null)
      setSubmitting(true)

      const followUpDue = getFollowUpDueDate()
      const { completedTaskId, hubSpotTaskId } = buildCompletionIds()
      const loggingInboundText = kind === 'note' && inboundText
      const payload: LogNotePayload = {
        body,
        activity_kind: loggingInboundText ? 'text' : kind,
        complete_task_id: completedTaskId,
        follow_up: buildFollowUpPayload(followUpDue),
        ...(loggingInboundText
          ? { mail_campaign_id: resolveMailerChoice(mailSourceChoice, mailCampaignOptions) }
          : {}),
        ...(kind === 'meeting' && contactMethod.contactId != null
          ? { contact_id: contactMethod.contactId }
          : {}),
      }

      try {
        const entry = await callLogService.logNote(leadId, payload)
        const { completedHubSpotTaskId, completionWarning } = await maybeCompleteHubSpot(
          hubSpotTaskId,
          kind === 'meeting'
            ? 'Meeting saved; the HubSpot task is still open.'
            : 'Note saved; the HubSpot task is still open.',
        )
        const contactName = resolveContactName(contacts, contactMethod.contactId)
        const metadataFallback: Record<string, unknown> = { body }
        if (kind === 'meeting' && contactMethod.contactId != null) {
          metadataFallback.contact_id = contactMethod.contactId
        }
        if (kind === 'meeting' && contactName) {
          metadataFallback.contact_name = contactName
        }
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
            event_type: entry.event_type ?? (kind === 'meeting' ? 'meeting_logged' : 'note_added'),
            source: entry.source ?? 'manual',
            metadata: entry.metadata ?? metadataFallback,
          },
          savedMeta,
        )
        setBody('')
        setInboundText(false)
        setMailSourceChoice('suggested')
        if (kind === 'meeting') setContactMethod(EMPTY_CONTACT_METHOD)
        resetNextStepState(completableTask)
      } catch (err) {
        setSubmitError(
          err instanceof Error
            ? err.message
            : kind === 'meeting'
              ? 'Failed to log meeting. Please try again.'
              : 'Failed to save note. Please try again.',
        )
      } finally {
        setSubmitting(false)
      }
    }

    const handleNoteSubmit = async () => handleNoteLikeSubmit('note')

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
      if (isEditingTask) {
        await handleTaskEditSubmit()
        return
      }
      if (mode === 'call') await handleCallSubmit()
      else if (mode === 'note') await handleNoteSubmit()
      else if (mode === 'meeting') await handleNoteLikeSubmit('meeting')
      else await handleEmailSubmit()
    }

    const handleTaskEditSubmit = async () => {
      const task = editTask?.task
      if (!task || typeof task.id !== 'number' || task.id <= 0) return
      const due = resolveFollowUpDueDate(followUpPreset, customDueDate)
      if (!due) {
        setFollowUpError('Choose a follow-up date.')
        return
      }
      setFollowUpError(null)
      setSubmitError(null)
      setSubmitting(true)
      try {
        const { title } = resolveCreateTaskPayload(
          nextStepType,
          nextStepType === 'custom' ? customTaskTitle : '',
        )
        const notesValue = editTaskNotes.trim() || null
        const payload: { title?: string; due_date: string; notes?: string | null } = { due_date: due }
        if (title !== task.title) payload.title = title
        if (notesValue !== (task.notes ?? null)) payload.notes = notesValue
        const updated = await leadTaskService.updateTask(leadId, task.id, payload)
        onTaskUpdated?.({
          ...task,
          ...updated,
          lead_id: updated.lead_id ?? task.lead_id ?? leadId,
          task_type: updated.task_type ?? task.task_type,
          created_at: updated.created_at ?? task.created_at,
          completed_at: updated.completed_at ?? task.completed_at,
          created_by: updated.created_by ?? task.created_by,
          title: updated.title ?? title,
          due_date: updated.due_date !== undefined ? updated.due_date : due,
          notes: updated.notes !== undefined ? updated.notes : notesValue,
        })
      } catch (err) {
        setSubmitError(
          err instanceof Error ? err.message : 'Failed to update task. Please try again.',
        )
      } finally {
        setSubmitting(false)
      }
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
        hideCompleteTask={isEditingTask}
        lockFollowUp={isEditingTask}
        taskNotes={isEditingTask ? editTaskNotes : createFollowUp ? followUpNotes : undefined}
        onTaskNotesChange={isEditingTask ? setEditTaskNotes : createFollowUp ? setFollowUpNotes : undefined}
      />
    )

    return (
      <Box
        ref={formRef}
        component="form"
        onSubmit={handleSubmit}
        data-testid={isEditingTask ? 'edit-task-form' : ROOT_TESTID[mode]}
      >
        {submitError && (
          <Alert
            severity="error"
            sx={{ mb: 1.25 }}
            onClose={() => setSubmitError(null)}
            data-testid={SUBMIT_ERROR_TESTID[mode]}
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
                  preferredPhoneDigits={resolvedPreferredPhoneDigits}
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

                {direction === 'inbound' && (
                  <MailerResponseSourceConfirm
                    campaigns={mailCampaignOptions}
                    choice={mailSourceChoice}
                    onChange={setMailSourceChoice}
                    heading="Where did this inbound call come from?"
                  />
                )}

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

                {direction !== 'inbound' && mailCampaignOptions.length > 0 && (
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
                          {c.submitted_at ? formatDate(c.submitted_at) : 'Campaign'}{' '}
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
              <>
                {isEditingTask && (
                  <>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block', mb: 1 }}
                      data-testid="edit-task-context-hint"
                    >
                      Original note and phone are shown for context. Saving updates this task.
                    </Typography>
                    <ContactMethodFields
                      dense
                      mode="phone"
                      contacts={contacts}
                      contactsLoading={contactsLoading}
                      value={contactMethod}
                      onChange={setContactMethod}
                      preferredPhoneDigits={resolvedPreferredPhoneDigits}
                    />
                  </>
                )}
                {!isEditingTask && (
                  <Box sx={{ mb: 1.25 }} data-testid="inbound-text-toggle">
                    <FormLabel
                      id="inbound-text-label"
                      sx={{ mb: 0.75, display: 'block', typography: 'body2' }}
                    >
                      Inbound text?
                    </FormLabel>
                    <ToggleButtonGroup
                      exclusive
                      size="small"
                      value={inboundText ? 'yes' : 'no'}
                      onChange={(_e, next: 'yes' | 'no' | null) => {
                        if (next) setInboundText(next === 'yes')
                      }}
                      aria-labelledby="inbound-text-label"
                      sx={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: 0.5,
                        mb: inboundText ? 1.25 : 0,
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
                      <ToggleButton value="no" data-testid="inbound-text-no">
                        No
                      </ToggleButton>
                      <ToggleButton value="yes" data-testid="inbound-text-yes">
                        Yes, inbound text
                      </ToggleButton>
                    </ToggleButtonGroup>
                    {inboundText && (
                      <MailerResponseSourceConfirm
                        campaigns={mailCampaignOptions}
                        choice={mailSourceChoice}
                        onChange={setMailSourceChoice}
                        heading="Where did this text come from?"
                      />
                    )}
                  </Box>
                )}
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
              </>
            )}

            {mode === 'meeting' && (
              <>
                <ContactMethodFields
                  dense
                  mode="contact"
                  contacts={contacts}
                  contactsLoading={contactsLoading}
                  value={contactMethod}
                  onChange={setContactMethod}
                />
                <TextField
                  label="Meeting notes"
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
                        data-testid="meeting-char-count"
                      >
                        {body.length}/{MAX_BODY_LENGTH.toLocaleString()}
                      </Typography>
                    )
                  }
                  fullWidth
                  sx={{ mb: 2 }}
                  inputProps={{ 'data-testid': 'meeting-notes-input' }}
                />
              </>
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
              data-testid={CANCEL_BTN_TESTID[mode]}
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
            data-testid={isEditingTask ? 'edit-task-save-btn' : SAVE_BTN_TESTID[mode]}
          >
            {submitting
              ? 'Saving…'
              : isEditingTask
                ? 'Update task'
                : mode === 'call'
                  ? (completeTask && completableTask ? 'Log call and complete task' : 'Log call')
                  : mode === 'note'
                    ? (completeTask && completableTask ? 'Save note and complete task' : 'Save Note')
                    : mode === 'meeting'
                      ? (completeTask && completableTask ? 'Log meeting and complete task' : 'Log meeting')
                    : (completeTask && completableTask ? 'Log email and complete task' : 'Log email')}
          </Button>
        </Stack>
      </Box>
    )
  },
)

export default LogActivityForm
