import React, { useEffect, useState } from 'react'
import {
  Alert,
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
  Snackbar,
  TextField,
  Typography,
} from '@mui/material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { contactService } from '@/services/api'
import type {
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

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ContactFormModalProps {
  open: boolean
  onClose: () => void
  propertyId: number
  contact?: PropertyContact
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildInitialState(contact?: PropertyContact): FormState {
  if (contact) {
    return {
      firstName: contact.first_name ?? '',
      lastName: contact.last_name ?? '',
      role: contact.property_contact_role ?? contact.role ?? 'owner',
      roleDescription: contact.role_description ?? '',
      notes: contact.notes ?? '',
      phones: contact.phones?.map((p) => ({ value: p.value, label: p.label })) ?? [],
      emails: contact.emails?.map((e) => ({ value: e.value, label: e.label })) ?? [],
    }
  }
  return {
    firstName: '',
    lastName: '',
    role: 'owner',
    roleDescription: '',
    notes: '',
    phones: [],
    emails: [],
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
}) => {
  const queryClient = useQueryClient()
  const isEditMode = contact !== undefined

  // ── Form state ────────────────────────────────────────────────────────────
  const [form, setForm] = useState<FormState>(() => buildInitialState(contact))
  const [nameError, setNameError] = useState(false)

  // ── Snackbar state ────────────────────────────────────────────────────────
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string }>({
    open: false,
    message: '',
  })

  const showError = (message: string) => setSnackbar({ open: true, message })

  // ── Reset form when contact prop changes or modal opens/closes ────────────
  useEffect(() => {
    setForm(buildInitialState(contact))
    setNameError(false)
  }, [contact, open])

  // ── Create mutation ───────────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: async (payload: ContactCreatePayload) => {
      const newContact = await contactService.createContact(payload)
      await contactService.linkContactToProperty(propertyId, {
        contact_id: newContact.id,
        role: payload.role ?? 'owner',
        is_primary: false,
      })
      return newContact
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      onClose()
    },
    onError: (err: Error) => showError(err.message || 'Failed to create contact.'),
  })

  // ── Update mutation ───────────────────────────────────────────────────────
  const updateMutation = useMutation({
    mutationFn: (payload: ContactCreatePayload) =>
      contactService.updateContact(contact!.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      onClose()
    },
    onError: (err: Error) => showError(err.message || 'Failed to update contact.'),
  })

  const isPending = createMutation.isPending || updateMutation.isPending

  // ── Field change handlers ─────────────────────────────────────────────────
  const handleFieldChange =
    <K extends keyof FormState>(key: K) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setForm((prev) => ({ ...prev, [key]: event.target.value }))
      if (key === 'firstName' || key === 'lastName') {
        setNameError(false)
      }
    }

  // ── Phone row handlers ────────────────────────────────────────────────────
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

  // ── Email row handlers ────────────────────────────────────────────────────
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

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = () => {
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

    if (isEditMode) {
      updateMutation.mutate(payload)
    } else {
      createMutation.mutate(payload)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        fullWidth
        maxWidth="sm"
        aria-labelledby="contact-form-dialog-title"
      >
        <DialogTitle id="contact-form-dialog-title">
          {isEditMode ? 'Edit Contact' : 'Add Contact'}
        </DialogTitle>

        <DialogContent dividers>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            {/* Name row */}
            <Box sx={{ display: 'flex', gap: 2 }}>
              <TextField
                label="First Name"
                value={form.firstName}
                onChange={handleFieldChange('firstName')}
                fullWidth
                error={nameError}
                inputProps={{ 'aria-label': 'First name' }}
              />
              <TextField
                label="Last Name"
                value={form.lastName}
                onChange={handleFieldChange('lastName')}
                fullWidth
                error={nameError}
                inputProps={{ 'aria-label': 'Last name' }}
              />
            </Box>

            {/* Inline name validation error */}
            {nameError && (
              <FormHelperText error>
                At least one of first name or last name is required.
              </FormHelperText>
            )}

            {/* Role */}
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

            {/* Role description — only shown when role = 'other' */}
            {form.role === 'other' && (
              <TextField
                label="Role Description"
                value={form.roleDescription}
                onChange={handleFieldChange('roleDescription')}
                fullWidth
                placeholder="Describe the role"
                inputProps={{ 'aria-label': 'Role description' }}
              />
            )}

            {/* Notes */}
            <TextField
              label="Notes"
              value={form.notes}
              onChange={handleFieldChange('notes')}
              fullWidth
              multiline
              minRows={3}
              inputProps={{ 'aria-label': 'Notes' }}
            />

            {/* ── Phone numbers ─────────────────────────────────────────── */}
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="subtitle2">Phone Numbers</Typography>
                <IconButton
                  size="small"
                  onClick={handleAddPhone}
                  aria-label="Add phone number"
                  title="Add phone number"
                >
                  +
                </IconButton>
              </Box>

              {form.phones.map((phone, index) => (
                <Box key={index} sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
                  <TextField
                    label="Phone"
                    value={phone.value}
                    onChange={(e) => handlePhoneValueChange(index, e.target.value)}
                    size="small"
                    sx={{ flex: 2 }}
                    inputProps={{ 'aria-label': `Phone number ${index + 1}` }}
                  />
                  <FormControl size="small" sx={{ flex: 1 }}>
                    <InputLabel id={`phone-label-${index}`}>Label</InputLabel>
                    <Select
                      labelId={`phone-label-${index}`}
                      label="Label"
                      value={phone.label}
                      onChange={(e) => handlePhoneLabelChange(index, e.target.value as PhoneLabel)}
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
                  >
                    ×
                  </IconButton>
                </Box>
              ))}
            </Box>

            {/* ── Email addresses ───────────────────────────────────────── */}
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="subtitle2">Email Addresses</Typography>
                <IconButton
                  size="small"
                  onClick={handleAddEmail}
                  aria-label="Add email address"
                  title="Add email address"
                >
                  +
                </IconButton>
              </Box>

              {form.emails.map((email, index) => (
                <Box key={index} sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
                  <TextField
                    label="Email"
                    value={email.value}
                    onChange={(e) => handleEmailValueChange(index, e.target.value)}
                    size="small"
                    type="email"
                    sx={{ flex: 2 }}
                    inputProps={{ 'aria-label': `Email address ${index + 1}` }}
                  />
                  <FormControl size="small" sx={{ flex: 1 }}>
                    <InputLabel id={`email-label-${index}`}>Label</InputLabel>
                    <Select
                      labelId={`email-label-${index}`}
                      label="Label"
                      value={email.label}
                      onChange={(e) => handleEmailLabelChange(index, e.target.value as EmailLabel)}
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
                  >
                    ×
                  </IconButton>
                </Box>
              ))}
            </Box>
          </Box>
        </DialogContent>

        <DialogActions>
          <Button onClick={onClose} disabled={isPending}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={isPending}
          >
            {isPending ? 'Saving…' : isEditMode ? 'Save Changes' : 'Add Contact'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* API error snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={5000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
          severity="error"
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </>
  )
}
