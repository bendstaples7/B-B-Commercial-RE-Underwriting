/**
 * LogCallForm — call outcome + duration + notes form for a lead.
 *
 * Also supports completing a matching open call task (default on) and
 * scheduling a follow-up at preset or custom intervals.
 */
import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  FormControl,
  FormControlLabel,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import type { LeadTask, LeadTimelineEntry, LogCallPayload, PropertyContact } from '@/types'
import { callLogService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { useQuery } from '@tanstack/react-query'
import {
  ContactMethodFields,
  EMPTY_CONTACT_METHOD,
  type ContactMethodValue,
  contactMethodToCallPayload,
} from '@/components/ContactMethodFields'
import { findCallCompletableTask, parseHubSpotTaskId } from '@/utils/callCompletableTask'
import { addDaysIso } from '@/utils/fromQueue'

const MAX_NOTES_LENGTH = 2000

type FollowUpPreset = '1' | '3' | '7' | 'custom'

export type LogCallSavedMeta = {
  completedTaskId?: number
  completedHubSpotTaskId?: number
}

function formatFollowUpPresetLabel(preset: Exclude<FollowUpPreset, 'custom'>, dueDate: string): string {
  const labels: Record<Exclude<FollowUpPreset, 'custom'>, string> = {
    '1': 'Tomorrow',
    '3': 'In 3 days',
    '7': 'In 1 week',
  }
  const day = new Date(`${dueDate}T00:00:00`).toLocaleDateString(undefined, { weekday: 'long' })
  return `${labels[preset]} (${day})`
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

export interface LogCallFormProps {
  leadId: number
  contacts?: PropertyContact[]
  contactsLoading?: boolean
  openTasks?: LeadTask[]
  onSaved: (entry: LeadTimelineEntry, meta?: LogCallSavedMeta) => void
  onCancel?: () => void
}

export interface LogCallFormHandle {
  focus: () => void
}

export const LogCallForm = forwardRef<LogCallFormHandle, LogCallFormProps>(function LogCallForm(
  { leadId, contacts = [], contactsLoading = false, openTasks = [], onSaved, onCancel },
  ref,
) {
  const formRef = useRef<HTMLDivElement>(null)
  const outcomeInputRef = useRef<HTMLInputElement>(null)

  const callTask = useMemo(() => findCallCompletableTask(openTasks), [openTasks])

  const { data: recentMailCampaigns } = useQuery({
    queryKey: ['mail-campaigns-for-lead', leadId],
    queryFn: () => openLetterService.campaignsForLead(leadId),
  })
  const mailCampaignOptions = recentMailCampaigns?.campaigns ?? []
  const [outcome, setOutcome] = useState<LogCallPayload['outcome'] | ''>('')
  const [duration, setDuration] = useState('')
  const [notes, setNotes] = useState('')
  const [mailCampaignId, setMailCampaignId] = useState<number | ''>('')
  const [contactMethod, setContactMethod] = useState<ContactMethodValue>(EMPTY_CONTACT_METHOD)
  const [completeTask, setCompleteTask] = useState(true)
  const [createFollowUp, setCreateFollowUp] = useState(false)
  const [followUpPreset, setFollowUpPreset] = useState<FollowUpPreset>('3')
  const [customDueDate, setCustomDueDate] = useState('')

  const [outcomeError, setOutcomeError] = useState<string | null>(null)
  const [durationError, setDurationError] = useState<string | null>(null)
  const [notesError, setNotesError] = useState<string | null>(null)
  const [followUpError, setFollowUpError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useImperativeHandle(ref, () => ({
    focus: () => {
      outcomeInputRef.current?.focus()
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

  const validateNotes = (value: string): string | null => {
    if (value.length > MAX_NOTES_LENGTH)
      return `Notes must be ${MAX_NOTES_LENGTH.toLocaleString()} characters or fewer.`
    return null
  }

  const resolveFollowUpDueDate = (): string | null => {
    if (!createFollowUp) return null
    if (followUpPreset === 'custom') return customDueDate || null
    return addDaysIso(Number(followUpPreset))
  }

  const followUpDuePreview =
    createFollowUp && followUpPreset !== 'custom'
      ? addDaysIso(Number(followUpPreset))
      : null

  const validateAll = (): boolean => {
    const oErr = validateOutcome(outcome)
    const dErr = validateDuration(duration)
    const nErr = validateNotes(notes)
    let fErr: string | null = null
    if (createFollowUp && followUpPreset === 'custom' && !customDueDate) {
      fErr = 'Choose a follow-up date.'
    }

    setOutcomeError(oErr)
    setDurationError(dErr)
    setNotesError(nErr)
    setFollowUpError(fErr)

    return !oErr && !dErr && !nErr && !fErr
  }

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

    const followUpDue = resolveFollowUpDueDate()
    const completingNativeTask =
      completeTask && callTask && callTask.source !== 'hubspot' && typeof callTask.id === 'number'
    const completedTaskId = completingNativeTask ? callTask.id as number : null
    const completingHubSpotTask =
      completeTask && callTask && callTask.source === 'hubspot'
    const hubSpotTaskId = completingHubSpotTask ? parseHubSpotTaskId(callTask.id) : null

    const payload: LogCallPayload = {
      outcome: outcome as LogCallPayload['outcome'],
      duration_minutes: duration !== '' ? Number(duration) : null,
      notes: notes.trim() || null,
      mail_campaign_id: mailCampaignId === '' ? null : mailCampaignId,
      ...contactMethodToCallPayload(contactMethod),
      complete_task_id: completedTaskId,
      follow_up: followUpDue
        ? {
            title: 'Follow up call',
            due_date: followUpDue,
            task_type: 'call_owner_today',
          }
        : null,
    }

    try {
      const entry = await callLogService.logCall(leadId, payload)

      let completedHubSpotTaskId: number | undefined
      if (hubSpotTaskId != null) {
        await callLogService.markHubSpotTaskDone(leadId, hubSpotTaskId)
        completedHubSpotTaskId = hubSpotTaskId
      }

      const summaryParts = [`Call logged: ${payload.outcome}`]
      if (payload.duration_minutes) {
        summaryParts.push(`${payload.duration_minutes} min`)
      }
      if (payload.notes) {
        summaryParts.push(payload.notes.slice(0, 200))
      }
      const summary = summaryParts.join('. ').slice(0, 500)
      const metadataFallback = buildCallMetadataFallback(payload, contactMethod, contacts)
      const savedMeta: LogCallSavedMeta | undefined =
        completedTaskId != null || completedHubSpotTaskId != null
          ? { completedTaskId: completedTaskId ?? undefined, completedHubSpotTaskId }
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
      setDuration('')
      setNotes('')
      setMailCampaignId('')
      setContactMethod(EMPTY_CONTACT_METHOD)
      setCompleteTask(true)
      setCreateFollowUp(false)
      setFollowUpPreset('3')
      setCustomDueDate('')
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : 'Failed to log call. Please try again.'
      )
    } finally {
      setSubmitting(false)
    }
  }

  const isNotesOverLimit = notes.length > MAX_NOTES_LENGTH

  return (
    <Box
      ref={formRef}
      component="form"
      onSubmit={handleSubmit}
      data-testid="log-call-form"
    >
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

      <FormControl fullWidth error={!!outcomeError} sx={{ mb: 2 }}>
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

      {mailCampaignOptions.length > 0 && (
        <FormControl fullWidth sx={{ mb: 2 }} size="small">
          <InputLabel id="mail-campaign-label">Response to mailer? (optional)</InputLabel>
          <Select
            labelId="mail-campaign-label"
            label="Response to mailer? (optional)"
            value={mailCampaignId}
            onChange={(e) =>
              setMailCampaignId(e.target.value === '' ? '' : Number(e.target.value))
            }
          >
            <MenuItem value="">— Not mail-related —</MenuItem>
            {mailCampaignOptions.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.submitted_at
                  ? new Date(c.submitted_at).toLocaleDateString()
                  : 'Campaign'}{' '}
                — {c.template_name || `Template ${c.template_id}`}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      <Box sx={{ mb: 2, pt: 1, borderTop: 1, borderColor: 'divider' }} data-testid="call-task-actions">
        {callTask ? (
          <FormControlLabel
            sx={{ alignItems: 'flex-start', m: 0, mb: 1.5, display: 'flex' }}
            control={
              <Checkbox
                checked={completeTask}
                onChange={(e) => setCompleteTask(e.target.checked)}
                data-testid="complete-call-task-checkbox"
                sx={{ pt: 0.25 }}
              />
            }
            label={
              <Box data-testid="complete-call-task-section">
                <Typography variant="body2">
                  Complete task:{' '}
                  <Typography component="span" variant="body2" fontWeight={600}>
                    {callTask.title}
                  </Typography>
                </Typography>
                {callTask.source === 'hubspot' && (
                  <Typography variant="caption" color="text.secondary" display="block">
                    Marks done in HubSpot when possible.
                  </Typography>
                )}
              </Box>
            }
          />
        ) : openTasks.some((t) => t.status === 'open' || t.status === 'overdue') ? (
          <Alert severity="info" sx={{ mb: 1.5 }} data-testid="no-call-task-hint">
            No open call or follow-up task to complete. Mail or email outreach tasks are not completed from a call log.
          </Alert>
        ) : null}

        <FormControlLabel
          sx={{ alignItems: 'flex-start', m: 0, display: 'flex' }}
          control={
            <Checkbox
              checked={createFollowUp}
              onChange={(e) => setCreateFollowUp(e.target.checked)}
              data-testid="create-follow-up-checkbox"
              sx={{ pt: 0.25 }}
            />
          }
          label={
            <Typography variant="body2" data-testid="call-follow-up-section">
              Create a follow-up task
              {followUpDuePreview && (
                <>
                  {' — '}
                  <Typography component="span" variant="body2" color="primary.main">
                    {formatFollowUpPresetLabel(
                      followUpPreset as Exclude<FollowUpPreset, 'custom'>,
                      followUpDuePreview,
                    )}
                  </Typography>
                </>
              )}
            </Typography>
          }
        />

        {createFollowUp && (
          <Box sx={{ pl: 4, mt: 1 }}>
            <ToggleButtonGroup
              exclusive
              size="small"
              value={followUpPreset}
              onChange={(_e, value: FollowUpPreset | null) => {
                if (value != null) {
                  setFollowUpPreset(value)
                  setFollowUpError(null)
                }
              }}
              aria-label="Follow-up interval"
            >
              <ToggleButton value="1" data-testid="follow-up-1d">Tomorrow</ToggleButton>
              <ToggleButton value="3" data-testid="follow-up-3d">3 days</ToggleButton>
              <ToggleButton value="7" data-testid="follow-up-7d">1 week</ToggleButton>
              <ToggleButton value="custom" data-testid="follow-up-custom">Custom</ToggleButton>
            </ToggleButtonGroup>
            {followUpPreset === 'custom' && (
              <TextField
                type="date"
                size="small"
                label="Follow-up date"
                value={customDueDate}
                onChange={(e) => {
                  setCustomDueDate(e.target.value)
                  setFollowUpError(null)
                }}
                error={!!followUpError}
                helperText={followUpError}
                InputLabelProps={{ shrink: true }}
                sx={{ mt: 1.5, display: 'block' }}
                inputProps={{ 'data-testid': 'follow-up-custom-date' }}
              />
            )}
            {followUpError && followUpPreset !== 'custom' && (
              <FormHelperText error>{followUpError}</FormHelperText>
            )}
          </Box>
        )}
      </Box>

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
          {submitting
            ? 'Saving…'
            : completeTask && callTask
              ? 'Log call and complete task'
              : 'Log call'}
        </Button>
      </Stack>
    </Box>
  )
})

export default LogCallForm
