import React, { useState } from 'react'
import {
  Box,
  Typography,
  Button,
  Chip,
  List,
  ListItem,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  Alert,
  CircularProgress,
} from '@mui/material'
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { contactService } from '@/services/api'
import type { PropertyContact, ContactRole } from '@/types'
import { ContactFormModal } from './ContactFormModal'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert snake_case role to Title Case display label. */
function formatRole(role: ContactRole): string {
  return role
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ContactsSectionProps {
  propertyId: number
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const ContactsSection: React.FC<ContactsSectionProps> = ({ propertyId }) => {
  const queryClient = useQueryClient()

  // ── Modal state ──────────────────────────────────────────────────────────
  const [formOpen, setFormOpen] = useState(false)
  const [editingContact, setEditingContact] = useState<PropertyContact | undefined>(undefined)

  // ── Confirmation dialog state ─────────────────────────────────────────────
  const [removeDialogOpen, setRemoveDialogOpen] = useState(false)
  const [contactToRemove, setContactToRemove] = useState<PropertyContact | null>(null)

  // ── Snackbar state ────────────────────────────────────────────────────────
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'error' | 'success' }>({
    open: false,
    message: '',
    severity: 'error',
  })

  const showError = (message: string) =>
    setSnackbar({ open: true, message, severity: 'error' })

  const showSuccess = (message: string) =>
    setSnackbar({ open: true, message, severity: 'success' })

  // ── Query ─────────────────────────────────────────────────────────────────
  const {
    data: contacts,
    isLoading,
    error: fetchError,
  } = useQuery<PropertyContact[]>({
    queryKey: ['propertyContacts', propertyId],
    queryFn: () => contactService.getPropertyContacts(propertyId),
  })

  // ── Set as Primary mutation ───────────────────────────────────────────────
  const setPrimaryMutation = useMutation({
    mutationFn: (contact: PropertyContact) =>
      contactService.linkContactToProperty(propertyId, {
        contact_id: contact.id,
        role: contact.property_contact_role,
        is_primary: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      showSuccess('Contact set as primary.')
    },
    onError: (err: Error) => showError(err.message || 'Failed to set primary contact.'),
  })

  // ── Remove (unlink) mutation ──────────────────────────────────────────────
  const removeMutation = useMutation({
    mutationFn: (contactId: number) =>
      contactService.unlinkContactFromProperty(propertyId, contactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      showSuccess('Contact removed.')
    },
    onError: (err: Error) => showError(err.message || 'Failed to remove contact.'),
  })

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleOpenAdd = () => {
    setEditingContact(undefined)
    setFormOpen(true)
  }

  const handleOpenEdit = (contact: PropertyContact) => {
    setEditingContact(contact)
    setFormOpen(true)
  }

  const handleCloseForm = () => {
    setFormOpen(false)
    setEditingContact(undefined)
  }

  const handleRemoveClick = (contact: PropertyContact) => {
    setContactToRemove(contact)
    setRemoveDialogOpen(true)
  }

  const handleRemoveConfirm = () => {
    if (contactToRemove) {
      removeMutation.mutate(contactToRemove.id)
    }
    setRemoveDialogOpen(false)
    setContactToRemove(null)
  }

  const handleRemoveCancel = () => {
    setRemoveDialogOpen(false)
    setContactToRemove(null)
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <Box>
      {/* Header row */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" component="h3">
          Contacts
        </Typography>
        <Button
          variant="contained"
          size="small"
          startIcon={<PersonAddIcon />}
          onClick={handleOpenAdd}
          aria-label="Add contact"
        >
          Add Contact
        </Button>
      </Box>

      {/* Loading state */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={32} aria-label="Loading contacts" />
        </Box>
      )}

      {/* Fetch error */}
      {fetchError && !isLoading && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert">
          {fetchError instanceof Error ? fetchError.message : 'Failed to load contacts.'}
        </Alert>
      )}

      {/* Empty state */}
      {!isLoading && !fetchError && contacts?.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No contacts linked to this property yet. Use "Add Contact" to link one.
        </Typography>
      )}

      {/* Contact list */}
      {!isLoading && !fetchError && contacts && contacts.length > 0 && (
        <List disablePadding>
          {contacts.map((contact, index) => {
            const fullName = [contact.first_name, contact.last_name].filter(Boolean).join(' ') || '(No name)'
            const isPrimary = contact.is_primary
            const role = contact.property_contact_role

            return (
              <React.Fragment key={contact.id}>
                {index > 0 && <Divider component="li" />}
                <ListItem
                  disablePadding
                  sx={{ py: 1.5, flexDirection: 'column', alignItems: 'flex-start' }}
                >
                  {/* Name + badges row */}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 0.5 }}>
                    <Typography variant="subtitle1" fontWeight="bold">
                      {fullName}
                    </Typography>
                    <Chip
                      label={formatRole(role)}
                      size="small"
                      variant="outlined"
                      color="default"
                    />
                    {isPrimary && (
                      <Chip
                        label="Primary"
                        size="small"
                        color="primary"
                        aria-label="Primary contact"
                      />
                    )}
                  </Box>

                  {/* Phone numbers */}
                  {contact.phones && contact.phones.length > 0 && (
                    <Box sx={{ mb: 0.25 }}>
                      {contact.phones.map((phone) => (
                        <Typography key={phone.id} variant="body2" color="text.secondary">
                          📞 {phone.value}
                          {phone.label && phone.label !== 'other' ? ` (${phone.label})` : ''}
                        </Typography>
                      ))}
                    </Box>
                  )}

                  {/* Email addresses */}
                  {contact.emails && contact.emails.length > 0 && (
                    <Box sx={{ mb: 0.5 }}>
                      {contact.emails.map((email) => (
                        <Typography key={email.id} variant="body2" color="text.secondary">
                          ✉️ {email.value}
                          {email.label && email.label !== 'other' ? ` (${email.label})` : ''}
                        </Typography>
                      ))}
                    </Box>
                  )}

                  {/* Action buttons */}
                  <Box sx={{ display: 'flex', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
                    {!isPrimary && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => setPrimaryMutation.mutate(contact)}
                        disabled={setPrimaryMutation.isPending}
                        aria-label={`Set ${fullName} as primary contact`}
                      >
                        Set as Primary
                      </Button>
                    )}
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => handleOpenEdit(contact)}
                      aria-label={`Edit ${fullName}`}
                    >
                      Edit
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      color="error"
                      onClick={() => handleRemoveClick(contact)}
                      disabled={removeMutation.isPending}
                      aria-label={`Remove ${fullName}`}
                    >
                      Remove
                    </Button>
                  </Box>
                </ListItem>
              </React.Fragment>
            )
          })}
        </List>
      )}

      {/* Remove confirmation dialog */}
      <Dialog
        open={removeDialogOpen}
        onClose={handleRemoveCancel}
        aria-labelledby="remove-contact-dialog-title"
      >
        <DialogTitle id="remove-contact-dialog-title">Remove Contact</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to remove{' '}
            <strong>
              {contactToRemove
                ? [contactToRemove.first_name, contactToRemove.last_name].filter(Boolean).join(' ') || '(No name)'
                : 'this contact'}
            </strong>{' '}
            from this property? The contact record will not be deleted.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleRemoveCancel} autoFocus>
            Cancel
          </Button>
          <Button onClick={handleRemoveConfirm} color="error" variant="contained">
            Remove
          </Button>
        </DialogActions>
      </Dialog>

      {/* Contact form modal */}
      <ContactFormModal
        open={formOpen}
        onClose={handleCloseForm}
        propertyId={propertyId}
        contact={editingContact}
      />

      {/* Snackbar for API errors / success */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={5000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  )
}
