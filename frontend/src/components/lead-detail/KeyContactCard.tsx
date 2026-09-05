import { useMemo, useState } from 'react'
import { Box, Button, Chip, Divider, Link, Paper, Stack, Typography } from '@mui/material'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
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
  splitDisplayName,
  unlinkedPeopleFromLead,
} from '@/utils/propertyContacts'
import { ContactNameInlineEdit } from '@/components/ContactNameInlineEdit'
import {
  ContactFormModal,
  type ContactFormInitialValues,
} from '@/components/ContactFormModal'

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

function formatContactRole(contact: PropertyContactSummary): string {
  const role = (contact.role || 'owner').replace(/_/g, ' ')
  return role.replace(/\b\w/g, (c) => c.toUpperCase())
}

type FormPhoneLabel = 'mobile' | 'home' | 'work' | 'other'

function toFormPhoneLabel(label: string | null | undefined): FormPhoneLabel {
  if (label === 'home' || label === 'work' || label === 'other' || label === 'mobile') {
    return label
  }
  return 'mobile'
}

function channelsToInitialValues(
  name: string,
  channels: KeyContactChannel[],
): ContactFormInitialValues {
  const parts = splitDisplayName(name)
  const phones = channels
    .filter((c): c is Extract<KeyContactChannel, { kind: 'phone' }> => c.kind === 'phone')
    .map((c) => ({
      value: c.phone.value,
      label: toFormPhoneLabel(c.phone.label),
    }))
  const emails = channels
    .filter((c): c is Extract<KeyContactChannel, { kind: 'email' }> => c.kind === 'email')
    .map((c) => ({ value: c.value, label: 'personal' as const }))
  return {
    firstName: parts.first_name ?? '',
    lastName: parts.last_name ?? '',
    role: 'owner',
    phones,
    emails,
  }
}

/**
 * Persistent Key Contact card — name / phone / email / mailing (no avatar).
 * On lg+ this is the single outreach contact surface.
 */
export function KeyContactCard({ name, commandCenterData, sticky = false }: KeyContactCardProps) {
  const [addOpen, setAddOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const channels = resolveKeyContactChannels(commandCenterData)
  const mailing = formatKeyContactMailing(commandCenterData)
  const displayName = name?.trim() || 'No contact on file'
  const editablePerson = primaryEditablePersonContact(commandCenterData.contacts)
  const extraPeople = additionalPeopleForKeyContact(commandCenterData.contacts)
  const ghostPeople = useMemo(
    () =>
      unlinkedPeopleFromLead(commandCenterData.contacts, {
        ownerFirst: commandCenterData.owner_first_name,
        ownerLast: commandCenterData.owner_last_name,
        organizations: commandCenterData.organizations,
        phones: commandCenterData.phones,
        emails: commandCenterData.emails,
      }),
    [
      commandCenterData.contacts,
      commandCenterData.owner_first_name,
      commandCenterData.owner_last_name,
      commandCenterData.organizations,
      commandCenterData.phones,
      commandCenterData.emails,
    ],
  )
  const phoneChannels = channels.filter(
    (c): c is Extract<KeyContactChannel, { kind: 'phone' }> => c.kind === 'phone',
  )
  const emailChannels = channels.filter(
    (c): c is Extract<KeyContactChannel, { kind: 'email' }> => c.kind === 'email',
  )
  const contactsUntrusted = Boolean(commandCenterData.contacts_likely_prior_owner)
  const canEditDetails = !contactsUntrusted && (Boolean(editablePerson) || displayName !== 'No contact on file' || phoneChannels.length > 0)

  const editInitialValues = useMemo(() => {
    if (editablePerson) {
      const hasContactPhones = (editablePerson.phones || []).some((p) => p?.value?.trim())
      if (hasContactPhones) return undefined
      // Contact row exists but phones only live on flat lead slots — seed the form.
      return {
        firstName: editablePerson.first_name ?? '',
        lastName: editablePerson.last_name ?? '',
        role: 'owner' as const,
        phones: phoneChannels.map((ch) => ({
          value: ch.phone.value,
          label: toFormPhoneLabel(ch.phone.label),
        })),
        emails: emailChannels.map((ch) => ({ value: ch.value, label: 'personal' as const })),
      }
    }
    const ghost = ghostPeople[0]
    if (ghost) {
      const ghostPhones = ghost.phones.length
        ? ghost.phones.map((p) => ({ value: p.value, label: 'mobile' as const }))
        : phoneChannels.map((ch) => ({
            value: ch.phone.value,
            label: toFormPhoneLabel(ch.phone.label),
          }))
      const ghostEmails = ghost.emails.length
        ? ghost.emails.map((e) => ({ value: e.value, label: 'personal' as const }))
        : emailChannels.map((ch) => ({ value: ch.value, label: 'personal' as const }))
      return {
        firstName: ghost.first_name ?? '',
        lastName: ghost.last_name ?? '',
        role: 'owner' as const,
        phones: ghostPhones,
        emails: ghostEmails,
      }
    }
    if (displayName === 'No contact on file') {
      return channelsToInitialValues('', channels)
    }
    return channelsToInitialValues(displayName, channels)
  }, [
    editablePerson,
    ghostPeople,
    displayName,
    channels,
    phoneChannels,
    emailChannels,
  ])

  const contactBody = (
    <>
      {editablePerson ? (
        <Box sx={{ mb: 1.5 }}>
          <ContactNameInlineEdit
            contactId={editablePerson.id}
            displayName={displayName}
            leadId={commandCenterData.id}
            isPrimary
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
          <Typography sx={ccMetaSx} data-testid="key-contact-phone-empty">
            No phone on file
          </Typography>
        ) : (
          phoneChannels.map((ch, idx) => (
            <PhoneRow
              key={`phone-${phoneKey(ch.phone.value)}-${idx}`}
              phone={ch.phone}
              dense={false}
              actionable={!contactsUntrusted}
              valueTestId={idx === 0 ? 'key-contact-phone' : `key-contact-phone-${idx + 1}`}
            />
          ))
        )}
        {emailChannels.length === 0 ? (
          <Typography sx={ccMetaSx} data-testid="key-contact-email-empty">
            No email on file
          </Typography>
        ) : (
          emailChannels.map((ch, idx) => {
            const testId = idx === 0 ? 'key-contact-email' : `key-contact-email-${idx + 1}`
            return (
              <Box
                key={`email-${ch.value.toLowerCase()}`}
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
        {canEditDetails && (
          <Box>
            <Button
              size="small"
              variant="text"
              startIcon={<EditOutlinedIcon />}
              onClick={() => setEditOpen(true)}
              aria-label="Edit contact details"
              data-testid="key-contact-edit-details-btn"
              sx={{ cursor: 'pointer', px: 0.5, ml: -0.5 }}
            >
              Edit phone & details
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
      <ContactFormModal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        propertyId={commandCenterData.id}
        contact={editablePerson ?? undefined}
        initialValues={editInitialValues}
        linkAsPrimary={!editablePerson}
        allowLinkExisting={false}
      />
    </Paper>
  )
}
