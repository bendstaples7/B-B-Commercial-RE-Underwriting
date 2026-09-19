import { useEffect, useState, type ReactNode } from 'react'
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Link,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import LocalPostOfficeOutlinedIcon from '@mui/icons-material/LocalPostOfficeOutlined'
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import type { CommandCenterPayload, LeadPhone, PropertyContactSummary } from '@/types'
import {
  ccCardSx,
  ccMetaSx,
  ccRowTitleSx,
  ccSectionTitleSx,
} from '@/components/lead-detail/commandCenterChrome'
import { PriorOwnerStaleOverlay } from '@/components/lead-detail/PriorOwnerStaleCallout'
import { PhoneRow } from '@/components/PhoneRow'
import { CopyIconButton } from '@/components/CopyIconButton'
import { looksLikePhoneNumber } from '@/utils/phone'
import {
  additionalPeopleForKeyContact,
  contactDisplayName,
  primaryEditablePersonContact,
} from '@/utils/propertyContacts'
import { ContactNameInlineEdit } from '@/components/ContactNameInlineEdit'
import {
  ContactFormModal,
} from '@/components/ContactFormModal'
import { contactService } from '@/services/api'
import { AppSnackbar } from '@/components/AppSnackbar'

export interface KeyContactCardProps {
  name: string | null
  commandCenterData: CommandCenterPayload
  sticky?: boolean
}

export type KeyContactChannel =
  | { kind: 'phone'; phone: LeadPhone }
  | { kind: 'email'; value: string }

/** Owner mailing only (no property-address fallback) — used for mail / skip-trace confidence. */
export function formatKeyContactMailing(data: CommandCenterPayload): string | null {
  const street = data.mailing_address?.trim() || ''
  const city = data.mailing_city?.trim() || ''
  const stateZip = [data.mailing_state?.trim(), data.mailing_zip?.trim()]
    .filter(Boolean)
    .join(' ')
  const cityLine = [city, stateZip].filter(Boolean).join(', ')
  if (!street && !cityLine) return null
  return [street, cityLine].filter(Boolean).join('\n')
}

function phoneKey(value: string): string {
  return value.replace(/\D/g, '')
}

function collectEmailSlotValues(data: CommandCenterPayload): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const push = (raw: string) => {
    const trimmed = raw.trim()
    if (!trimmed) return
    const key = trimmed.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    out.push(trimmed)
  }
  if (data.emails?.length) {
    for (const e of data.emails) {
      if (typeof e === 'string') push(e)
    }
  }
  for (let slot = 1; slot <= 5; slot += 1) {
    const raw = data[`email_${slot}` as keyof CommandCenterPayload]
    if (typeof raw === 'string') push(raw)
  }
  return out
}

/** First usable phone, preferring the full LeadPhone DTO (confidence, notes) over flat slots. */
function primaryPhone(data: CommandCenterPayload): LeadPhone | null {
  if (data.phones?.length) {
    for (const p of data.phones) {
      const v = p?.value?.trim()
      if (v && looksLikePhoneNumber(v)) return p
    }
  }
  for (let slot = 1; slot <= 7; slot += 1) {
    const raw = data[`phone_${slot}` as keyof CommandCenterPayload]
    if (typeof raw === 'string' && raw.trim() && looksLikePhoneNumber(raw)) {
      return { value: raw.trim() }
    }
  }
  return null
}

/**
 * Resolve Key Contact display channels.
 * Phone-shaped values misfiled in email_* render as phones (e.g. lead 634
 * email_1 = "(708) 222-6620"), then the first real email follows.
 */
export function resolveKeyContactChannels(data: CommandCenterPayload): KeyContactChannel[] {
  const channels: KeyContactChannel[] = []
  const seenPhones = new Set<string>()

  const primary = primaryPhone(data)
  if (primary) {
    channels.push({ kind: 'phone', phone: primary })
    seenPhones.add(phoneKey(primary.value))
  }

  let foundEmail = false
  for (const value of collectEmailSlotValues(data)) {
    if (looksLikePhoneNumber(value)) {
      const key = phoneKey(value)
      if (!seenPhones.has(key)) {
        seenPhones.add(key)
        channels.push({ kind: 'phone', phone: { value } })
      }
      continue
    }
    if (!foundEmail) {
      foundEmail = true
      channels.push({ kind: 'email', value })
    }
  }

  return channels
}

function resolveContactChannels(contact: PropertyContactSummary | null): KeyContactChannel[] {
  if (!contact) return []
  const channels: KeyContactChannel[] = []
  const seenPhones = new Set<string>()
  for (const phone of contact.phones || []) {
    const value = phone?.value?.trim()
    if (!value || !looksLikePhoneNumber(value)) continue
    const key = phoneKey(value)
    if (seenPhones.has(key)) continue
    seenPhones.add(key)
    channels.push({ kind: 'phone', phone })
  }
  let foundEmail = false
  for (const email of contact.emails || []) {
    const value = email?.value?.trim()
    if (!value) continue
    if (looksLikePhoneNumber(value)) {
      const key = phoneKey(value)
      if (!seenPhones.has(key)) {
        seenPhones.add(key)
        channels.push({ kind: 'phone', phone: { value } })
      }
      continue
    }
    if (!foundEmail) {
      foundEmail = true
      channels.push({ kind: 'email', value })
    }
  }
  return channels
}

function mergeContactAndFallbackChannels(
  contactChannels: KeyContactChannel[],
  fallbackChannels: KeyContactChannel[],
): KeyContactChannel[] {
  const merged = [...contactChannels]
  for (const fallback of fallbackChannels) {
    const duplicate = merged.some((contact) => {
      if (fallback.kind === 'phone') {
        return contact.kind === 'phone'
          && phoneKey(contact.phone.value) === phoneKey(fallback.phone.value)
      }
      return contact.kind === 'email'
        && contact.value.toLowerCase() === fallback.value.toLowerCase()
    })
    if (!duplicate) merged.push(fallback)
  }
  return merged
}

function formatContactRole(contact: PropertyContactSummary): string {
  const role = (contact.role || 'owner').replace(/_/g, ' ')
  return role.replace(/\b\w/g, (c) => c.toUpperCase())
}

type FormPhoneLabel = 'mobile' | 'home' | 'work' | 'other'
type FormEmailLabel = 'personal' | 'work' | 'other'

function toFormPhoneLabel(label: string | null | undefined): FormPhoneLabel {
  if (label === 'home' || label === 'work' || label === 'other' || label === 'mobile') {
    return label
  }
  return 'mobile'
}

function toFormEmailLabel(label: string | null | undefined): FormEmailLabel {
  if (label === 'work' || label === 'other' || label === 'personal') {
    return label
  }
  return 'personal'
}

function FieldPencil({
  value,
  ariaLabel,
  editTestId,
  inputTestId,
  onSave,
  disabled = false,
  children,
}: {
  value: string
  ariaLabel: string
  editTestId: string
  inputTestId: string
  onSave: (next: string) => Promise<void>
  disabled?: boolean
  children: ReactNode
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const fieldLabel = ariaLabel.replace(/^Edit\s+/i, '')

  if (editing) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, flex: 1 }}>
        <TextField
          size="small"
          fullWidth
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          inputProps={{
            'data-testid': inputTestId,
            style: { cursor: 'text' },
          }}
          sx={{ caretColor: 'text.primary' }}
        />
        <IconButton
          size="small"
          color="primary"
          aria-label={`Save ${fieldLabel}`}
          disabled={saving || disabled}
          onClick={() => {
            setSaving(true)
            void onSave(draft).then(
              () => {
                setEditing(false)
                setSaving(false)
              },
              () => setSaving(false),
            )
          }}
          sx={{ cursor: 'pointer' }}
        >
          <CheckIcon fontSize="small" />
        </IconButton>
        <IconButton
          size="small"
          aria-label={`Cancel ${fieldLabel}`}
          disabled={saving}
          onClick={() => {
            setDraft(value)
            setEditing(false)
          }}
          sx={{ cursor: 'pointer' }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
      <IconButton
        size="small"
        aria-label={ariaLabel}
        data-testid={editTestId}
        disabled={disabled}
        onClick={() => {
          setDraft(value)
          setEditing(true)
        }}
        sx={{ cursor: 'pointer', p: 0.25, flexShrink: 0 }}
      >
        <EditOutlinedIcon sx={{ fontSize: 16 }} />
      </IconButton>
    </Box>
  )
}

/**
 * Persistent Key Contact card — name / phone / email / mailing (no avatar).
 * On lg+ this is the single outreach contact surface.
 */
export function KeyContactCard({ name, commandCenterData, sticky = false }: KeyContactCardProps) {
  const queryClient = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [clearDialogOpen, setClearDialogOpen] = useState(false)
  const [snackbar, setSnackbar] = useState<{
    open: boolean
    message: string
    severity?: 'error' | 'success'
  }>({
    open: false,
    message: '',
  })
  const editablePersonFromData = primaryEditablePersonContact(commandCenterData.contacts)
  const [savedContact, setSavedContact] = useState<Partial<PropertyContactSummary> | null>(null)
  const [methodSaveInFlight, setMethodSaveInFlight] = useState(false)
  useEffect(() => {
    setSavedContact(null)
  }, [editablePersonFromData?.id])
  const editablePerson = editablePersonFromData && savedContact?.id === editablePersonFromData.id
    ? {
        ...editablePersonFromData,
        first_name: savedContact.first_name ?? editablePersonFromData.first_name,
        last_name: savedContact.last_name ?? editablePersonFromData.last_name,
        phones: savedContact.phones ?? editablePersonFromData.phones,
        emails: savedContact.emails ?? editablePersonFromData.emails,
      }
    : editablePersonFromData
  const extraPeople = additionalPeopleForKeyContact(commandCenterData.contacts)
  const personName = editablePerson ? contactDisplayName(editablePerson) : ''
  const orgName = (commandCenterData.organizations ?? [])
    .map((org) => org.name?.trim())
    .find(Boolean) || ''
  const passedName = name?.trim() || ''
  const displayName = personName
    || (passedName && passedName === orgName ? orgName : '')
    || orgName
    || 'No contact on file'
  const contactChannels = resolveContactChannels(editablePerson)
  const channels = editablePerson
    ? mergeContactAndFallbackChannels(
        contactChannels,
        resolveKeyContactChannels(commandCenterData),
      )
    : []
  const mailing = formatKeyContactMailing(commandCenterData)
  const phoneChannels = channels.filter(
    (c): c is Extract<KeyContactChannel, { kind: 'phone' }> => c.kind === 'phone',
  )
  const emailChannels = channels.filter(
    (c): c is Extract<KeyContactChannel, { kind: 'email' }> => c.kind === 'email',
  )
  const contactsUntrusted = Boolean(commandCenterData.contacts_likely_prior_owner)
  const canEditDetails = !contactsUntrusted && Boolean(editablePerson)
  const canClearOwner = canEditDetails && displayName !== 'No contact on file'

  const refreshContact = () => {
    void queryClient.invalidateQueries({ queryKey: ['commandCenter', commandCenterData.id] })
    void queryClient.invalidateQueries({ queryKey: ['propertyContacts', commandCenterData.id] })
  }

  const savePerson = async (extra: {
    first_name?: string | null
    last_name?: string | null
    phones?: Array<{ value: string; label: FormPhoneLabel }>
    emails?: Array<{ value: string; label: FormEmailLabel }>
  }) => {
    if (!editablePerson) {
      setSnackbar({ open: true, message: 'Add a person before editing.', severity: 'error' })
      throw new Error('No person to edit')
    }
    try {
      const updated = await contactService.updateContact(editablePerson.id, extra)
      setSavedContact({
        id: updated.id,
        first_name: updated.first_name,
        last_name: updated.last_name,
        phones: updated.phones,
        emails: updated.emails,
      })
      refreshContact()
      setSnackbar({ open: true, message: 'Saved.', severity: 'success' })
    } catch (err) {
      setSnackbar({
        open: true,
        message: err instanceof Error ? err.message : 'Could not save.',
        severity: 'error',
      })
      throw err
    }
  }

  const savePhoneValue = (previous: string, next: string) => {
    const trimmed = next.trim()
    if (trimmed && !looksLikePhoneNumber(trimmed)) {
      setSnackbar({ open: true, message: 'Enter a valid phone number.', severity: 'error' })
      return Promise.reject(new Error('Enter a valid phone number.'))
    }
    const current = (editablePerson?.phones || [])
      .filter((p) => (p.value || '').trim())
      .map((p) => ({ value: p.value, label: toFormPhoneLabel(p.label) }))
    const match = current.findIndex((p) => (
      p.value === previous || phoneKey(p.value) === phoneKey(previous)
    ))
    let phones = current
    if (match >= 0) {
      phones = current
        .map((p, i) => (i === match ? { ...p, value: trimmed } : p))
        .filter((p) => p.value.trim())
    } else if (trimmed) {
      phones = [...current, { value: trimmed, label: 'mobile' as const }]
    }
    setMethodSaveInFlight(true)
    return savePerson({ phones }).finally(() => setMethodSaveInFlight(false))
  }

  const saveEmailValue = (previous: string, next: string) => {
    const trimmed = next.trim()
    const current = (editablePerson?.emails || [])
      .filter((e) => (e.value || '').trim())
      .map((e) => ({ value: e.value, label: toFormEmailLabel(e.label) }))
    const match = current.findIndex((e) => e.value.toLowerCase() === previous.toLowerCase())
    let emails = current
    if (match >= 0) {
      emails = current
        .map((e, i) => (i === match ? { ...e, value: trimmed } : e))
        .filter((e) => e.value.trim())
    } else if (trimmed) {
      emails = [...current, { value: trimmed, label: 'personal' as const }]
    }
    setMethodSaveInFlight(true)
    return savePerson({ emails }).finally(() => setMethodSaveInFlight(false))
  }

  const clearOwnerMutation = useMutation({
    mutationFn: () => {
      if (!editablePerson) {
        return Promise.reject(new Error('No owner to clear'))
      }
      return contactService.clearOwnerPerson(commandCenterData.id, {
        contact_id: editablePerson.id,
        first_name: editablePerson.first_name,
        last_name: editablePerson.last_name,
        reason: 'cleared_from_key_contact',
      })
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['commandCenter', commandCenterData.id] })
      void queryClient.invalidateQueries({ queryKey: ['propertyContacts', commandCenterData.id] })
      setClearDialogOpen(false)
      setSnackbar({
        open: true,
        message: `${result.display_name} cleared from this lead.`,
        severity: 'success',
      })
    },
    onError: (err: Error) => {
      setSnackbar({
        open: true,
        message: err.message || 'Failed to clear owner from lead.',
        severity: 'error',
      })
    },
  })

  const contactBody = (
    <>
      {editablePerson ? (
        <Box sx={{ mb: 1.5 }}>
          <ContactNameInlineEdit
            contactId={editablePerson.id}
            displayName={displayName}
            leadId={commandCenterData.id}
            inputTestId="key-contact-name-edit-input"
            editButtonTestId="edit-key-contact-name-btn"
            displayNameTestId="key-contact-name"
            titleSx={{ fontWeight: 600, mb: 0 }}
          />
        </Box>
      ) : (
        <Typography sx={{ ...ccRowTitleSx, fontWeight: 600, mb: 1.5 }} data-testid="key-contact-name">
          {displayName}
        </Typography>
      )}
      <Stack spacing={1}>
        {phoneChannels.length === 0 ? (
          canEditDetails ? (
            <FieldPencil
              value=""
              ariaLabel="Edit phone"
              editTestId="key-contact-phone-edit"
              inputTestId="key-contact-phone-edit-input"
              onSave={(next) => savePhoneValue('', next)}
              disabled={methodSaveInFlight}
            >
              <Typography sx={ccMetaSx} data-testid="key-contact-phone-empty">
                No phone on file
              </Typography>
            </FieldPencil>
          ) : (
            <Typography sx={ccMetaSx} data-testid="key-contact-phone-empty">
              No phone on file
            </Typography>
          )
        ) : (
          phoneChannels.map((ch, idx) => {
            const row = (
              <PhoneRow
                phone={ch.phone}
                dense={false}
                actionable={!contactsUntrusted}
                valueTestId={idx === 0 ? 'key-contact-phone' : `key-contact-phone-${idx + 1}`}
              />
            )
            if (!canEditDetails) {
              return <Box key={`phone-${phoneKey(ch.phone.value)}-${idx}`}>{row}</Box>
            }
            return (
              <FieldPencil
                key={`phone-${phoneKey(ch.phone.value)}-${idx}`}
                value={ch.phone.value}
                ariaLabel="Edit phone"
                editTestId={idx === 0 ? 'key-contact-phone-edit' : `key-contact-phone-edit-${idx + 1}`}
                inputTestId={idx === 0 ? 'key-contact-phone-edit-input' : `key-contact-phone-edit-input-${idx + 1}`}
                onSave={(next) => savePhoneValue(ch.phone.value, next)}
                disabled={methodSaveInFlight}
              >
                {row}
              </FieldPencil>
            )
          })
        )}
        {emailChannels.length === 0 ? (
          canEditDetails ? (
            <FieldPencil
              value=""
              ariaLabel="Edit email"
              editTestId="key-contact-email-edit"
              inputTestId="key-contact-email-edit-input"
              onSave={(next) => saveEmailValue('', next)}
              disabled={methodSaveInFlight}
            >
              <Typography sx={ccMetaSx} data-testid="key-contact-email-empty">
                No email on file
              </Typography>
            </FieldPencil>
          ) : (
            <Typography sx={ccMetaSx} data-testid="key-contact-email-empty">
              No email on file
            </Typography>
          )
        ) : (
          emailChannels.map((ch, idx) => {
            const testId = idx === 0 ? 'key-contact-email' : `key-contact-email-${idx + 1}`
            const row = (
              <Box
                sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}
              >
                <EmailOutlinedIcon sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0 }} />
                {contactsUntrusted ? (
                  <Typography
                    sx={{
                      ...ccMetaSx,
                      fontSize: '0.9rem',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                    data-testid={testId}
                  >
                    {ch.value}
                  </Typography>
                ) : (
                  <>
                    <Link
                      href={`mailto:${ch.value}`}
                      underline="hover"
                      sx={{
                        ...ccMetaSx,
                        color: 'primary.main',
                        fontSize: '0.9rem',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                      data-testid={testId}
                    >
                      {ch.value}
                    </Link>
                    <CopyIconButton
                      value={ch.value}
                      ariaLabel="Copy email"
                      testId={`${testId}-copy`}
                    />
                  </>
                )}
              </Box>
            )
            if (!canEditDetails) {
              return <Box key={`email-${ch.value.toLowerCase()}`}>{row}</Box>
            }
            return (
              <FieldPencil
                key={`email-${ch.value.toLowerCase()}`}
                value={ch.value}
                ariaLabel="Edit email"
                editTestId={idx === 0 ? 'key-contact-email-edit' : `key-contact-email-edit-${idx + 1}`}
                inputTestId={idx === 0 ? 'key-contact-email-edit-input' : `key-contact-email-edit-input-${idx + 1}`}
                onSave={(next) => saveEmailValue(ch.value, next)}
                disabled={methodSaveInFlight}
              >
                {row}
              </FieldPencil>
            )
          })
        )}
        <Box
          sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, minWidth: 0 }}
          data-testid="key-contact-mailing-row"
        >
          <LocalPostOfficeOutlinedIcon
            sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0, mt: 0.15 }}
          />
          {mailing ? (
            <>
              <Typography
                sx={{
                  ...ccMetaSx,
                  fontSize: '0.9rem',
                  color: 'text.primary',
                  whiteSpace: 'pre-line',
                }}
                data-testid="key-contact-mailing"
              >
                {mailing}
              </Typography>
              <CopyIconButton
                value={mailing}
                ariaLabel="Copy mailing address"
                testId="key-contact-mailing-copy"
              />
            </>
          ) : (
            <Typography sx={ccMetaSx} data-testid="key-contact-mailing-empty">
              No mailing address on file
            </Typography>
          )}
        </Box>
        {canClearOwner && (
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
            <Button
              size="small"
              variant="text"
              color="error"
              onClick={() => setClearDialogOpen(true)}
              disabled={clearOwnerMutation.isPending}
              data-testid="key-contact-clear-owner-btn"
              sx={{ cursor: 'pointer', px: 0.5, ml: -0.5 }}
            >
              Clear from lead
            </Button>
          </Box>
        )}
        {extraPeople.length > 0 && (
          <Stack spacing={1} sx={{ pt: 0.5 }} data-testid="key-contact-other-people">
            <Divider />
            {extraPeople.map((person) => {
              const personName = contactDisplayName(person) || '(No name)'
              const phones = (person.phones || []).filter((p) => p?.value?.trim())
              return (
                <Box key={person.id} data-testid={`key-contact-other-${person.id}`}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                    <Typography sx={{ ...ccRowTitleSx, fontWeight: 500 }}>{personName}</Typography>
                    <Chip size="small" label={formatContactRole(person)} variant="outlined" />
                  </Box>
                  {phones.length > 0 ? (
                    <Stack spacing={0.25}>
                      {phones.map((phone, index) => (
                        <PhoneRow
                          key={`${phone.value}-${index}`}
                          phone={phone}
                          dense={false}
                          actionable={!contactsUntrusted}
                          valueTestId={
                            index === 0
                              ? `key-contact-other-phone-${person.id}`
                              : `key-contact-other-phone-${person.id}-${index + 1}`
                          }
                        />
                      ))}
                    </Stack>
                  ) : null}
                </Box>
              )
            })}
          </Stack>
        )}
      </Stack>
    </>
  )

  return (
    <>
      <Paper
        data-testid="key-contact-card"
        elevation={0}
        sx={{
          ...ccCardSx,
          ...(sticky
            ? {
                position: 'sticky',
                top: 16,
                zIndex: 2,
              }
            : {}),
          '&[data-owner-link-highlight="true"]': {
            outline: '2px solid',
            outlineColor: 'primary.main',
            outlineOffset: 2,
          },
        }}
      >
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 1,
            mb: 1,
          }}
        >
          <Typography sx={ccSectionTitleSx} component="h2">
            Key Contact
          </Typography>
          <Button
            size="small"
            variant="outlined"
            startIcon={<PersonAddIcon />}
            onClick={() => setAddOpen(true)}
            aria-label="Add person"
            data-testid="key-contact-add-person-btn"
            sx={{ cursor: 'pointer', flexShrink: 0 }}
          >
            Add person
          </Button>
        </Box>
        {contactsUntrusted ? (
          <PriorOwnerStaleOverlay
            testId="key-contact-stale"
            bannerTestId="key-contact-likely-prior-owner"
          >
            {contactBody}
          </PriorOwnerStaleOverlay>
        ) : (
          contactBody
        )}
        <ContactFormModal
          open={addOpen}
          onClose={() => setAddOpen(false)}
          propertyId={commandCenterData.id}
          allowLinkExisting
        />
        <Dialog open={clearDialogOpen} onClose={() => setClearDialogOpen(false)}>
          <DialogTitle>Clear owner from lead?</DialogTitle>
          <DialogContent>
            <Typography>
              Remove {displayName} from this lead. Use this when the person is deceased, sold, or
              otherwise no longer the owner. You can then Move to Skip Trace to find the current
              owner.
            </Typography>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setClearDialogOpen(false)}>Cancel</Button>
            <Button
              color="error"
              variant="contained"
              data-testid="confirm-key-contact-clear-owner-btn"
              disabled={clearOwnerMutation.isPending}
              onClick={() => clearOwnerMutation.mutate()}
            >
              Clear from lead
            </Button>
          </DialogActions>
        </Dialog>
      </Paper>
      <AppSnackbar
        open={snackbar.open}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        message={snackbar.message}
        severity={snackbar.severity ?? 'error'}
      />
    </>
  )
}
