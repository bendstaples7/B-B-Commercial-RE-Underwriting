/**
 * ContactMethodFields — optional contact + phone/email method selectors for activity logging.
 */
import { useEffect, useMemo, useRef } from 'react'
import {
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import type { PropertyContact } from '@/types'
import { formatPhoneNumber } from '@/utils/phone'
import { formatPhoneConfidence } from '@/utils/helpers'

export const CONTACT_NONE = ''
export const METHOD_NONE = ''
export const METHOD_OTHER = 'other'

export interface ContactMethodValue {
  contactId: number | null
  methodKey: string
  methodValue: string | null
  methodLabel: string | null
  methodRecordId: number | null
}

export const EMPTY_CONTACT_METHOD: ContactMethodValue = {
  contactId: null,
  methodKey: METHOD_NONE,
  methodValue: null,
  methodLabel: null,
  methodRecordId: null,
}

const selectWrapSx = {
  '& .MuiSelect-select': {
    whiteSpace: 'normal',
    wordBreak: 'break-word',
  },
} as const

function formatContactShortLabel(contact: PropertyContact): string {
  return [contact.first_name, contact.last_name].filter(Boolean).join(' ') || 'Unnamed contact'
}

function formatContactLabel(contact: PropertyContact): string {
  const name = [contact.first_name, contact.last_name].filter(Boolean).join(' ') || 'Unnamed contact'
  const role = contact.property_contact_role.replace(/_/g, ' ')
  const primary = contact.is_primary ? ', primary' : ''
  return `${name} (${role}${primary})`
}

function formatPhoneLabel(value: string, label: string, contactName?: string, phone?: { confidence_score?: number | null; notes?: string | null }): string {
  const formatted = formatPhoneNumber(value)
  const prefix = contactName ? `${contactName}: ` : ''
  const confidence = phone ? formatPhoneConfidence(phone.confidence_score, phone.notes) : ''
  const confidenceSuffix = confidence ? ` · ${confidence}` : ''
  return `${prefix}${formatted} (${label})${confidenceSuffix}`
}

function formatEmailLabel(value: string, label: string, contactName?: string): string {
  const prefix = contactName ? `${contactName}: ` : ''
  return `${prefix}${value} (${label})`
}

export interface MethodOption {
  key: string
  label: string
  value: string
  recordId: number | null
  recordLabel: string | null
  confidenceScore?: number
}

export function buildMethodOptions(
  contacts: PropertyContact[],
  mode: 'phone' | 'email',
  selectedContactId: number | null,
): MethodOption[] {
  const relevantContacts = selectedContactId != null
    ? contacts.filter((c) => c.id === selectedContactId)
    : contacts

  const options: MethodOption[] = []

  for (const contact of relevantContacts) {
    const contactName = [contact.first_name, contact.last_name].filter(Boolean).join(' ') || 'Unnamed contact'
    if (mode === 'phone') {
      for (const phone of contact.phones ?? []) {
        options.push({
          key: `phone:${phone.id}`,
          label: formatPhoneLabel(
            phone.value,
            phone.label,
            selectedContactId == null ? contactName : undefined,
            phone,
          ),
          value: phone.value,
          recordId: phone.id,
          recordLabel: phone.label,
          confidenceScore: phone.confidence_score ?? 50,
        })
      }
    } else {
      for (const email of contact.emails ?? []) {
        options.push({
          key: `email:${email.id}`,
          label: formatEmailLabel(email.value, email.label, selectedContactId == null ? contactName : undefined),
          value: email.value,
          recordId: email.id,
          recordLabel: email.label,
        })
      }
    }
  }

  if (mode === 'phone') {
    return options.sort(
      (a, b) => (b.confidenceScore ?? 50) - (a.confidenceScore ?? 50),
    )
  }

  return options
}

export type ContactCallPayload = {
  contact_id?: number
  contact_phone_id?: number | null
  phone_number?: string
  phone_label?: string | null
}

export type ContactEmailPayload = {
  contact_id?: number
  contact_email_id?: number | null
  email_address?: string
  email_label?: string | null
}

export function contactMethodToCallPayload(value: ContactMethodValue): ContactCallPayload {
  const contact = value.contactId != null ? { contact_id: value.contactId } : {}
  if (!value.methodValue?.trim()) {
    return contact
  }
  return {
    ...contact,
    contact_phone_id: value.methodKey.startsWith('phone:') ? value.methodRecordId : null,
    phone_number: value.methodValue.trim(),
    phone_label: value.methodLabel,
  }
}

export function contactMethodToEmailPayload(value: ContactMethodValue): ContactEmailPayload {
  const contact = value.contactId != null ? { contact_id: value.contactId } : {}
  if (!value.methodValue?.trim()) {
    return contact
  }
  return {
    ...contact,
    contact_email_id: value.methodKey.startsWith('email:') ? value.methodRecordId : null,
    email_address: value.methodValue.trim(),
    email_label: value.methodLabel,
  }
}

export interface ContactMethodFieldsProps {
  mode: 'phone' | 'email'
  contacts: PropertyContact[]
  contactsLoading?: boolean
  value: ContactMethodValue
  onChange: (value: ContactMethodValue) => void
}

export function ContactMethodFields({
  mode,
  contacts,
  contactsLoading = false,
  value,
  onChange,
}: ContactMethodFieldsProps) {
  const methodOptions = useMemo(
    () => buildMethodOptions(contacts, mode, value.contactId),
    [contacts, mode, value.contactId],
  )

  const hasAutoSelected = useRef(false)

  const methodLabel = mode === 'phone' ? 'Phone number' : 'Email address'

  useEffect(() => {
    if (hasAutoSelected.current || contactsLoading || contacts.length === 0) return

    hasAutoSelected.current = true

    // Default to the primary contact (or the first one) and that contact's
    // first phone (calls) / email (emails) so details are captured even when
    // there are multiple contacts. The user can still change or clear to None.
    const defaultContact = contacts.find((c) => c.is_primary) ?? contacts[0]
    const options = buildMethodOptions(contacts, mode, defaultContact.id)
    const opt = options[0]

    if (!opt) {
      // The default contact has no phone/email of this mode — select the
      // contact only so contact attribution is still captured.
      onChange({ ...EMPTY_CONTACT_METHOD, contactId: defaultContact.id })
      return
    }

    onChange({
      contactId: defaultContact.id,
      methodKey: opt.key,
      methodValue: opt.value,
      methodLabel: opt.recordLabel,
      methodRecordId: opt.recordId,
    })
  }, [contacts, contactsLoading, mode, onChange])

  const handleContactChange = (contactKey: string) => {
    if (contactKey === CONTACT_NONE) {
      onChange({ ...EMPTY_CONTACT_METHOD })
      return
    }
    onChange({
      contactId: Number(contactKey),
      methodKey: METHOD_NONE,
      methodValue: null,
      methodLabel: null,
      methodRecordId: null,
    })
  }

  const handleMethodChange = (methodKey: string) => {
    if (methodKey === METHOD_NONE) {
      onChange({
        ...value,
        methodKey: METHOD_NONE,
        methodValue: null,
        methodLabel: null,
        methodRecordId: null,
      })
      return
    }
    if (methodKey === METHOD_OTHER) {
      onChange({
        ...value,
        methodKey: METHOD_OTHER,
        methodValue: value.methodValue ?? '',
        methodLabel: null,
        methodRecordId: null,
      })
      return
    }
    const opt = methodOptions.find((o) => o.key === methodKey)
    onChange({
      ...value,
      methodKey,
      methodValue: opt?.value ?? null,
      methodLabel: opt?.recordLabel ?? null,
      methodRecordId: opt?.recordId ?? null,
    })
  }

  return (
    <>
      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel id="contact-method-contact-label" shrink>
          Contact (optional)
        </InputLabel>
        <Select
          labelId="contact-method-contact-label"
          label="Contact (optional)"
          value={value.contactId != null ? String(value.contactId) : CONTACT_NONE}
          onChange={(e) => handleContactChange(e.target.value)}
          disabled={contactsLoading}
          data-testid="contact-method-contact-select"
          renderValue={(selected) => {
            if (selected === CONTACT_NONE) return '— None —'
            const contact = contacts.find((c) => String(c.id) === selected)
            return contact ? formatContactShortLabel(contact) : selected
          }}
          sx={selectWrapSx}
        >
          <MenuItem value={CONTACT_NONE}>— None —</MenuItem>
          {contacts.map((contact) => (
            <MenuItem key={contact.id} value={String(contact.id)}>
              {formatContactLabel(contact)}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {contacts.length === 0 && !contactsLoading && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 2 }}>
          No contacts linked to this property. Add contacts on the Contacts tab, or enter a method below.
        </Typography>
      )}

      <FormControl fullWidth size="small" sx={{ mb: 2 }}>
        <InputLabel id="contact-method-method-label" shrink>
          {methodLabel} (optional)
        </InputLabel>
        <Select
          labelId="contact-method-method-label"
          label={`${methodLabel} (optional)`}
          value={value.methodKey}
          onChange={(e) => handleMethodChange(e.target.value)}
          disabled={contactsLoading}
          data-testid="contact-method-method-select"
          renderValue={(selected) => {
            if (selected === METHOD_NONE) return '— None —'
            if (selected === METHOD_OTHER) return 'Other…'
            const opt = methodOptions.find((o) => o.key === selected)
            return opt?.label ?? selected
          }}
          sx={selectWrapSx}
        >
          <MenuItem value={METHOD_NONE}>— None —</MenuItem>
          {methodOptions.map((opt) => (
            <MenuItem key={opt.key} value={opt.key}>
              {opt.label}
            </MenuItem>
          ))}
          <MenuItem value={METHOD_OTHER}>Other…</MenuItem>
        </Select>
      </FormControl>

      {value.methodKey === METHOD_OTHER && (
        <TextField
          label={mode === 'phone' ? 'Phone number' : 'Email address'}
          value={value.methodValue ?? ''}
          onChange={(e) =>
            onChange({
              ...value,
              methodValue: e.target.value,
              methodLabel: null,
              methodRecordId: null,
            })
          }
          fullWidth
          size="small"
          sx={{ mb: 2 }}
          inputProps={{ 'data-testid': 'contact-method-other-input' }}
        />
      )}
    </>
  )
}

export default ContactMethodFields
