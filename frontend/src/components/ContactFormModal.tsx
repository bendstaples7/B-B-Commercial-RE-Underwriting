import React, { useEffect, useMemo, useState } from 'react'
import {
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormHelperText,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { contactService } from '@/services/api'
import { AppSnackbar } from '@/components/AppSnackbar'
import { contactDisplayName } from '@/utils/propertyContacts'
import type {
  Contact,
  ContactCreatePayload,
  ContactRole,
  EmailLabel,
  PhoneLabel,
  PropertyContact,
} from '@/types'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONTACT_ROLE_OPTIONS: { value: ContactRole; label: string }[] = [
  { value: 'owner', label: 'Owner' },
  { value: 'property_manager', label: 'Property Manager' },
  { value: 'attorney', label: 'Attorney' },
  { value: 'family_member', label: 'Family Member' },
  { value: 'other', label: 'Other' },
]

const PHONE_LABEL_OPTIONS: { value: PhoneLabel; label: string }[] = [
  { value: 'mobile', label: 'Mobile' },
  { value: 'home', label: 'Home' },
  { value: 'work', label: 'Work' },
  { value: 'other', label: 'Other' },
]

const EMAIL_LABEL_OPTIONS: { value: EmailLabel; label: string }[] = [
  { value: 'personal', label: 'Personal' },
  { value: 'work', label: 'Work' },
  { value: 'other', label: 'Other' },
]

// ---------------------------------------------------------------------------
// Local state types
// ---------------------------------------------------------------------------

interface PhoneRow {
  value: string
  label: PhoneLabel
}

interface EmailRow {
  value: string
  label: EmailLabel
}

interface FormState {
  firstName: string
  lastName: string
  role: ContactRole
  roleDescription: string
  notes: string
  phones: PhoneRow[]
  emails: EmailRow[]
}

export type ContactFormInitialValues = {
  firstName?: string
  lastName?: string
  role?: ContactRole
  roleDescription?: string
  notes?: string
  phones?: Array<{ value: string; label?: PhoneLabel | string }>
  emails?: Array<{ value: string; label?: EmailLabel | string }>
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

/** Edit target — full PropertyContact or a command-center contact summary. */
export type ContactFormEditTarget = {
  id: number
  first_name?: string | null
  last_name?: string | null
  role?: ContactRole | string | null
  property_contact_role?: ContactRole | string | null
  role_description?: string | null
  notes?: string | null
  phones?: Array<{ value: string; label?: PhoneLabel | string }>
  emails?: Array<{ value: string; label?: EmailLabel | string }>
  is_primary?: boolean
}

export interface ContactFormModalProps {
  open: boolean
  onClose: () => void
  propertyId: number
  contact?: ContactFormEditTarget | PropertyContact
  /** Prefill create mode (e.g. flat Key Contact name + phones). */
  initialValues?: ContactFormInitialValues
  /** When creating/linking, set is_primary on the property link. */
  linkAsPrimary?: boolean
  /** Show Create new / Link existing toggle (create mode only). Default true. */
  allowLinkExisting?: boolean
  /** Initial mode for create flows that should first search for an existing contact. */
  initialMode?: 'create' | 'link'
  /** Initial search text when opening directly in link mode. */
  initialLinkQuery?: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function asPhoneLabel(value: string | undefined): PhoneLabel {
  if (value === 'mobile' || value === 'home' || value === 'work' || value === 'other') {
    return value
  }
  return 'mobile'
}

function asEmailLabel(value: string | undefined): EmailLabel {
  if (value === 'personal' || value === 'work' || value === 'other') {
    return value
  }
  return 'personal'
}

function asContactRole(value: string | null | undefined): ContactRole {
  if (
    value === 'owner'
    || value === 'property_manager'
    || value === 'attorney'
    || value === 'family_member'
    || value === 'other'
    || value === 'former_owner'
  ) {
    return value
  }
  return 'owner'
}

function phoneRowKey(value: string): string {
  const digits = value.replace(/\D/g, '')
  return digits || value.trim().toLowerCase()
}

function mergePhoneRows(primary: PhoneRow[], extra: PhoneRow[]): PhoneRow[] {
  const seen = new Set<string>()
  const rows: PhoneRow[] = []
  for (const row of [...primary, ...extra]) {
    const value = row.value.trim()
    const key = phoneRowKey(value)
    if (!value || seen.has(key)) continue
    seen.add(key)
    rows.push({ value, label: row.label })
  }
  return rows
}

function mergeEmailRows(primary: EmailRow[], extra: EmailRow[]): EmailRow[] {
  const seen = new Set<string>()
  const rows: EmailRow[] = []
  for (const row of [...primary, ...extra]) {
    const value = row.value.trim()
    const key = value.toLowerCase()
    if (!value || seen.has(key)) continue
    seen.add(key)
    rows.push({ value, label: row.label })
  }
  return rows
}

function buildInitialState(
  contact?: ContactFormEditTarget,
  initialValues?: ContactFormInitialValues,
): FormState {
  if (contact) {
    const contactPhones =
      contact.phones
        ?.filter((p) => p.value?.trim())
        .map((p) => ({
          value: p.value,
          label: asPhoneLabel(typeof p.label === 'string' ? p.label : undefined),
        })) ?? []
    const seedPhones =
      initialValues?.phones
        ?.filter((p) => p.value?.trim())
        .map((p) => ({ value: p.value.trim(), label: asPhoneLabel(p.label) })) ?? []
    const contactEmails =
      contact.emails
        ?.filter((e) => e.value?.trim())
        .map((e) => ({
          value: e.value,
          label: asEmailLabel(typeof e.label === 'string' ? e.label : undefined),
        })) ?? []
    const seedEmails =
      initialValues?.emails
        ?.filter((e) => e.value?.trim())
        .map((e) => ({ value: e.value.trim(), label: asEmailLabel(e.label) })) ?? []
    return {
      firstName: contact.first_name ?? initialValues?.firstName ?? '',
      lastName: contact.last_name ?? initialValues?.lastName ?? '',
      role: asContactRole(
        contact.property_contact_role ?? contact.role ?? initialValues?.role,
      ),
      roleDescription: contact.role_description ?? initialValues?.roleDescription ?? '',
      notes: contact.notes ?? initialValues?.notes ?? '',
      phones: mergePhoneRows(contactPhones, seedPhones),
      emails: mergeEmailRows(contactEmails, seedEmails),
    }
  }
  return {
    firstName: initialValues?.firstName ?? '',
    lastName: initialValues?.lastName ?? '',
    role: initialValues?.role ?? 'owner',
    roleDescription: initialValues?.roleDescription ?? '',
    notes: initialValues?.notes ?? '',
    phones:
      initialValues?.phones
        ?.filter((p) => p.value?.trim())
        .map((p) => ({ value: p.value.trim(), label: asPhoneLabel(p.label) })) ?? [],
    emails:
      initialValues?.emails
        ?.filter((e) => e.value?.trim())
        .map((e) => ({ value: e.value.trim(), label: asEmailLabel(e.label) })) ?? [],
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const ContactFormModal: React.FC<ContactFormModalProps> = ({
  open,
  onClose,
  propertyId,
  contact,
  initialValues,
  linkAsPrimary = false,
  allowLinkExisting = true,
  initialMode = 'create',
  initialLinkQuery = '',
}) => {
  const queryClient = useQueryClient()
  const isEditMode = contact !== undefined

  const [mode, setMode] = useState<'create' | 'link'>('create')
  const [form, setForm] = useState<FormState>(() => buildInitialState(contact, initialValues))
  const [nameError, setNameError] = useState(false)
  const [linkQuery, setLinkQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedExisting, setSelectedExisting] = useState<Contact | null>(null)
  const [linkRole, setLinkRole] = useState<ContactRole>('owner')

  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string }>({
    open: false,
    message: '',
  })

  const showError = (message: string) => setSnackbar({ open: true, message })

  useEffect(() => {
    if (!open) return
    const nextMode = !isEditMode && allowLinkExisting && initialMode === 'link' ? 'link' : 'create'
    setForm(buildInitialState(contact, initialValues))
    setNameError(false)
    setMode(nextMode)
    setLinkQuery(nextMode === 'link' ? initialLinkQuery : '')
    setDebouncedQuery('')
    setSelectedExisting(null)
    setLinkRole(initialValues?.role ?? 'owner')
    // Reset only when the dialog opens or the edited contact changes — not on
    // every parent re-render of initialValues.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional
  }, [contact, open])

  useEffect(() => {
    if (!open || isEditMode || mode !== 'link') {
      setDebouncedQuery('')
      return
    }
    const trimmed = linkQuery.trim()
    const timeout = window.setTimeout(() => setDebouncedQuery(trimmed), 250)
    return () => window.clearTimeout(timeout)
  }, [isEditMode, linkQuery, mode, open])

  const { data: searchResults = [], isFetching: searchLoading } = useQuery({
    queryKey: ['contactSearch', propertyId, debouncedQuery],
    queryFn: () =>
      contactService.searchContacts({
        q: debouncedQuery,
        excludePropertyId: propertyId,
        limit: 20,
      }),
    enabled: open && !isEditMode && mode === 'link' && debouncedQuery.length >= 2,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
    queryClient.invalidateQueries({ queryKey: ['commandCenter', propertyId] })
  }

  const createMutation = useMutation({
    mutationFn: async (payload: ContactCreatePayload) => {
      const newContact = await contactService.createContact(payload)
      await contactService.linkContactToProperty(propertyId, {
        contact_id: newContact.id,
        role: payload.role ?? 'owner',
        is_primary: linkAsPrimary,
      })
      return newContact
    },
    onSuccess: () => {
      invalidate()
      onClose()
    },
    onError: (err: Error) => showError(err.message || 'Failed to create contact.'),
  })

  const updateMutation = useMutation({
    mutationFn: (payload: ContactCreatePayload) =>
      contactService.updateContact(contact!.id, payload),
    onSuccess: () => {
      invalidate()
      onClose()
    },
    onError: (err: Error) => showError(err.message || 'Failed to update contact.'),
  })

  const linkMutation = useMutation({
    mutationFn: async (existing: Contact) => {
      await contactService.linkContactToProperty(propertyId, {
        contact_id: existing.id,
        role: linkRole,
        is_primary: linkAsPrimary,
      })
      return existing
    },
    onSuccess: () => {
      invalidate()
      onClose()
    },
    onError: (err: Error) => showError(err.message || 'Failed to link contact.'),
  })

  const isPending =
    createMutation.isPending || updateMutation.isPending || linkMutation.isPending

  const handleFieldChange =
    <K extends keyof FormState>(key: K) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [key]: event.target.value }))
      if (key === 'firstName' || key === 'lastName') {
        setNameError(false)
      }
    }

  const handleAddPhone = () => {
    setForm((prev) => ({
      ...prev,
      phones: [...prev.phones, { value: '', label: 'mobile' }],
    }))
  }

  const handleRemovePhone = (index: number) => {
    setForm((prev) => ({
      ...prev,
      phones: prev.phones.filter((_, i) => i !== index),
    }))
  }

  const handlePhoneValueChange = (index: number, value: string) => {
    setForm((prev) => {
      const phones = [...prev.phones]
      phones[index] = { ...phones[index], value }
      return { ...prev, phones }
    })
  }

  const handlePhoneLabelChange = (index: number, label: PhoneLabel) => {
    setForm((prev) => {
      const phones = [...prev.phones]
      phones[index] = { ...phones[index], label }
      return { ...prev, phones }
    })
  }

  const handleAddEmail = () => {
    setForm((prev) => ({
      ...prev,
      emails: [...prev.emails, { value: '', label: 'personal' }],
    }))
  }

  const handleRemoveEmail = (index: number) => {
    setForm((prev) => ({
      ...prev,
      emails: prev.emails.filter((_, i) => i !== index),
    }))
  }

  const handleEmailValueChange = (index: number, value: string) => {
    setForm((prev) => {
      const emails = [...prev.emails]
      emails[index] = { ...emails[index], value }
      return { ...prev, emails }
    })
  }

  const handleEmailLabelChange = (index: number, label: EmailLabel) => {
    setForm((prev) => {
      const emails = [...prev.emails]
      emails[index] = { ...emails[index], label }
      return { ...prev, emails }
    })
  }

  const handleSubmit = () => {
    if (!isEditMode && mode === 'link') {
      if (!selectedExisting) {
        showError('Select an existing contact to link.')
        return
      }
      linkMutation.mutate(selectedExisting)
      return
    }

    const firstNameTrimmed = form.firstName.trim()
    const lastNameTrimmed = form.lastName.trim()

    if (!firstNameTrimmed && !lastNameTrimmed) {
      setNameError(true)
      return
    }

    const payload: ContactCreatePayload = {
      first_name: firstNameTrimmed || null,
      last_name: lastNameTrimmed || null,
      role: form.role,
      role_description: form.role === 'other' ? form.roleDescription.trim() || null : null,
      notes: form.notes.trim() || null,
      phones: form.phones
        .filter((p) => p.value.trim())
        .map((p) => ({ value: p.value.trim(), label: p.label })),
      emails: form.emails
        .filter((e) => e.value.trim())
        .map((e) => ({ value: e.value.trim(), label: e.label })),
    }
    if (isEditMode && contact?.role_description === undefined && initialValues?.roleDescription === undefined) {
      delete payload.role_description
    }
    if (isEditMode && contact?.notes === undefined && initialValues?.notes === undefined) {
      delete payload.notes
    }

    if (isEditMode) {
      updateMutation.mutate(payload)
    } else {
      createMutation.mutate(payload)
    }
  }

  const dialogTitle = useMemo(() => {
    if (isEditMode) return 'Edit Contact'
    if (mode === 'link') return 'Link Existing Contact'
    if (initialValues && (initialValues.firstName || initialValues.lastName || initialValues.phones?.length)) {
      return 'Save Contact'
    }
    return 'Add Contact'
  }, [isEditMode, mode, initialValues])

  const showLinkToggle = !isEditMode && allowLinkExisting

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        fullWidth
        maxWidth="sm"
        aria-labelledby="contact-form-dialog-title"
      >
        <DialogTitle id="contact-form-dialog-title">{dialogTitle}</DialogTitle>

        <DialogContent dividers>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1, cursor: 'auto' }}>
            {showLinkToggle && (
              <ToggleButtonGroup
                exclusive
                size="small"
                value={mode}
                onChange={(_, next) => {
                  if (next) setMode(next)
                }}
                aria-label="Add contact mode"
                data-testid="contact-form-mode-toggle"
                sx={{ alignSelf: 'flex-start' }}
              >
                <ToggleButton value="create" data-testid="contact-form-mode-create">
                  Create new
                </ToggleButton>
                <ToggleButton value="link" data-testid="contact-form-mode-link">
                  Link existing
                </ToggleButton>
              </ToggleButtonGroup>
            )}

            {!isEditMode && mode === 'link' ? (
              <>
                <Autocomplete
                  options={searchResults}
                  loading={searchLoading}
                  value={selectedExisting}
                  onChange={(_, value) => setSelectedExisting(value)}
                  inputValue={linkQuery}
                  onInputChange={(_, value, reason) => {
                    setLinkQuery(value)
                    if (reason === 'input' || reason === 'clear') {
                      setSelectedExisting(null)
                    }
                  }}
                  getOptionLabel={(option) => contactDisplayName(option) || `Contact #${option.id}`}
                  isOptionEqualToValue={(a, b) => a.id === b.id}
                  filterOptions={(x) => x}
                  noOptionsText={
                    linkQuery.trim().length < 2
                      ? 'Type at least 2 characters'
                      : searchLoading
                        ? 'Searching…'
                        : 'No matching contacts'
                  }
                  renderOption={(props, option) => {
                    const phone = option.phones?.[0]?.value
                    return (
                      <li {...props} key={option.id}>
                        <Box>
                          <Typography variant="body2">
                            {contactDisplayName(option) || `Contact #${option.id}`}
                          </Typography>
                          {phone ? (
                            <Typography variant="caption" color="text.secondary">
                              {phone}
                            </Typography>
                          ) : null}
                        </Box>
                      </li>
                    )
                  }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Search contacts"
                      placeholder="Name"
                      inputProps={{
                        ...params.inputProps,
                        'data-testid': 'contact-link-search-input',
                        style: { ...params.inputProps.style, cursor: 'text' },
                      }}
                      sx={{ caretColor: 'text.primary' }}
                    />
                  )}
                />
                <FormControl fullWidth>
                  <InputLabel id="link-contact-role-label">Role on this property</InputLabel>
                  <Select
                    labelId="link-contact-role-label"
                    label="Role on this property"
                    value={linkRole}
                    onChange={(e) => setLinkRole(e.target.value as ContactRole)}
                    data-testid="contact-link-role"
                  >
                    {CONTACT_ROLE_OPTIONS.map((opt) => (
                      <MenuItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </>
            ) : (
              <>
                <Box sx={{ display: 'flex', gap: 2 }}>
                  <TextField
                    label="First Name"
                    value={form.firstName}
                    onChange={handleFieldChange('firstName')}
                    fullWidth
                    error={nameError}
                    inputProps={{ 'aria-label': 'First name', 'data-testid': 'contact-first-name' }}
                    sx={{ caretColor: 'text.primary' }}
                  />
                  <TextField
                    label="Last Name"
                    value={form.lastName}
                    onChange={handleFieldChange('lastName')}
                    fullWidth
                    error={nameError}
                    inputProps={{ 'aria-label': 'Last name', 'data-testid': 'contact-last-name' }}
                    sx={{ caretColor: 'text.primary' }}
                  />
                </Box>

                {nameError && (
                  <FormHelperText error>
                    At least one of first name or last name is required.
                  </FormHelperText>
                )}

                <FormControl fullWidth>
                  <InputLabel id="contact-role-label">Role</InputLabel>
                  <Select
                    labelId="contact-role-label"
                    label="Role"
                    value={form.role}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, role: e.target.value as ContactRole }))
                    }
                  >
                    {CONTACT_ROLE_OPTIONS.map((opt) => (
                      <MenuItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                {form.role === 'other' && (
                  <TextField
                    label="Role Description"
                    value={form.roleDescription}
                    onChange={handleFieldChange('roleDescription')}
                    fullWidth
                    placeholder="Describe the role"
                    inputProps={{ 'aria-label': 'Role description' }}
                    sx={{ caretColor: 'text.primary' }}
                  />
                )}

                <TextField
                  label="Notes"
                  value={form.notes}
                  onChange={handleFieldChange('notes')}
                  fullWidth
                  multiline
                  minRows={3}
                  inputProps={{ 'aria-label': 'Notes' }}
                  sx={{ caretColor: 'text.primary' }}
                />

                <Box>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      mb: 1,
                    }}
                  >
                    <Typography variant="subtitle2">Phone Numbers</Typography>
                    <IconButton
                      size="small"
                      onClick={handleAddPhone}
                      aria-label="Add phone number"
                      title="Add phone number"
                      data-testid="contact-add-phone-btn"
                      sx={{ cursor: 'pointer' }}
                    >
                      +
                    </IconButton>
                  </Box>

                  {form.phones.length === 0 && (
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                      No phones yet — use + to add one.
                    </Typography>
                  )}

                  {form.phones.map((phone, index) => (
                    <Box
                      key={index}
                      sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}
                    >
                      <TextField
                        label="Phone"
                        value={phone.value}
                        onChange={(e) => handlePhoneValueChange(index, e.target.value)}
                        size="small"
                        sx={{ flex: 2, caretColor: 'text.primary' }}
                        inputProps={{
                          'aria-label': `Phone number ${index + 1}`,
                          'data-testid': `contact-phone-input-${index}`,
                          style: { cursor: 'text' },
                        }}
                      />
                      <FormControl size="small" sx={{ flex: 1 }}>
                        <InputLabel id={`phone-label-${index}`}>Label</InputLabel>
                        <Select
                          labelId={`phone-label-${index}`}
                          label="Label"
                          value={phone.label}
                          onChange={(e) =>
                            handlePhoneLabelChange(index, e.target.value as PhoneLabel)
                          }
                        >
                          {PHONE_LABEL_OPTIONS.map((opt) => (
                            <MenuItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <IconButton
                        size="small"
                        onClick={() => handleRemovePhone(index)}
                        aria-label={`Remove phone number ${index + 1}`}
                        title="Remove phone"
                        sx={{ cursor: 'pointer' }}
                      >
                        ×
                      </IconButton>
                    </Box>
                  ))}
                </Box>

                <Box>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      mb: 1,
                    }}
                  >
                    <Typography variant="subtitle2">Email Addresses</Typography>
                    <IconButton
                      size="small"
                      onClick={handleAddEmail}
                      aria-label="Add email address"
                      title="Add email address"
                      sx={{ cursor: 'pointer' }}
                    >
                      +
                    </IconButton>
                  </Box>

                  {form.emails.map((email, index) => (
                    <Box
                      key={index}
                      sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}
                    >
                      <TextField
                        label="Email"
                        value={email.value}
                        onChange={(e) => handleEmailValueChange(index, e.target.value)}
                        size="small"
                        type="email"
                        sx={{ flex: 2, caretColor: 'text.primary' }}
                        inputProps={{
                          'aria-label': `Email address ${index + 1}`,
                          style: { cursor: 'text' },
                        }}
                      />
                      <FormControl size="small" sx={{ flex: 1 }}>
                        <InputLabel id={`email-label-${index}`}>Label</InputLabel>
                        <Select
                          labelId={`email-label-${index}`}
                          label="Label"
                          value={email.label}
                          onChange={(e) =>
                            handleEmailLabelChange(index, e.target.value as EmailLabel)
                          }
                        >
                          {EMAIL_LABEL_OPTIONS.map((opt) => (
                            <MenuItem key={opt.value} value={opt.value}>
                              {opt.label}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                      <IconButton
                        size="small"
                        onClick={() => handleRemoveEmail(index)}
                        aria-label={`Remove email address ${index + 1}`}
                        title="Remove email"
                        sx={{ cursor: 'pointer' }}
                      >
                        ×
                      </IconButton>
                    </Box>
                  ))}
                </Box>
              </>
            )}
          </Box>
        </DialogContent>

        <DialogActions>
          <Button onClick={onClose} disabled={isPending} sx={{ cursor: 'pointer' }}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={isPending}
            data-testid="contact-form-submit"
            sx={{ cursor: 'pointer' }}
          >
            {isPending
              ? 'Saving…'
              : isEditMode
                ? 'Save Changes'
                : mode === 'link'
                  ? 'Link Contact'
                  : initialValues && (initialValues.firstName || initialValues.lastName || initialValues.phones?.length)
                    ? 'Save Contact'
                    : 'Add Contact'}
          </Button>
        </DialogActions>
      </Dialog>

      <AppSnackbar
        open={snackbar.open}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        message={snackbar.message}
        severity="error"
      />
    </>
  )
}
