import React, { useState } from 'react'
import {
  Box,
  Typography,
  Button,
  Chip,
  List,
  ListItem,
  ListItemButton,
  Divider,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Drawer,
  IconButton,
  Snackbar,
  Alert,
  CircularProgress,
} from '@mui/material'
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import BusinessIcon from '@mui/icons-material/Business'
import CloseIcon from '@mui/icons-material/Close'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { contactService } from '@/services/api'
import { entityResolutionApi } from '@/services/entityResolutionApi'
import { formatDate } from '@/utils/formatters'
import { isEntityContactName } from '@/utils/propertyContacts'
import { PhoneRow } from '@/components/PhoneRow'
import type { PropertyContact, ContactRole, EntityResolutionStatus } from '@/types'
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

  // ── Contact detail drawer state ───────────────────────────────────────────
  const [detailContact, setDetailContact] = useState<PropertyContact | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)

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

  const {
    data: entityStatus,
  } = useQuery<EntityResolutionStatus>({
    queryKey: ['entityResolution', propertyId],
    queryFn: () => entityResolutionApi.getStatus(propertyId),
  })

  const resolveEntityMutation = useMutation({
    mutationFn: (action: 'resolve' | 'research_nonprofit' | 'mark_nonprofit' = 'resolve') =>
      entityResolutionApi.resolve(propertyId, { action }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      queryClient.invalidateQueries({ queryKey: ['entityResolution', propertyId] })
      queryClient.invalidateQueries({ queryKey: ['commandCenter', propertyId] })
      if ('queued' in data && data.queued) {
        showSuccess('Entity resolution queued.')
        return
      }
      if (!('status' in data) || typeof data.status !== 'string') {
        showError(data.message || 'Entity resolution did not return a result status.')
        return
      }
      const result = data
      if (result.status === 'nonprofit') {
        showSuccess(result.message || 'Marked as nonprofit — cold mail deprioritized.')
        return
      }
      if (result.status === 'unsupported_jurisdiction') {
        showError(result.message || 'Non-Illinois LLC — not supported yet.')
        return
      }
      if (result.status === 'resolved' && result.person_found) {
        showSuccess(
          result.person_name
            ? `Resolved manager: ${result.person_name}. Skip-trace task created.`
            : 'Entity resolved. Skip-trace task created.',
        )
        return
      }
      if (result.status === 'resolved') {
        showSuccess(result.message || 'Entity resolved — no natural person found on filing.')
        return
      }
      if (result.status === 'no_match') {
        showError(result.message || 'No match found — try Resolve Illinois LLC or mark as nonprofit.')
        return
      }
      showError(result.message || `Entity resolution: ${result.status}`)
    },
    onError: (err: Error) =>
      showError(err.message || 'Failed to resolve entity.'),
  })

  const primaryContact = contacts?.find((c) => c.is_primary)
  const showEntityBanner =
    Boolean(entityStatus?.primary_is_entity) ||
    Boolean(entityStatus?.entity_lookup_status) ||
    Boolean(entityStatus?.is_nonprofit) ||
    (primaryContact != null && isEntityContactName(primaryContact))
  const entityActionPending = resolveEntityMutation.isPending

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

      {showEntityBanner && (
        <Alert
          severity={
            entityStatus?.is_nonprofit || entityStatus?.organization_org_type === 'nonprofit'
              ? 'success'
              : entityStatus?.provider_configured === false ||
                  entityStatus?.nonprofit_provider_configured === false
                ? 'warning'
                : entityStatus?.entity_lookup_status === 'unsupported_jurisdiction' ||
                    entityStatus?.entity_lookup_status === 'no_match'
                  ? 'warning'
                  : entityStatus?.entity_lookup_status === 'resolved'
                    ? 'success'
                    : 'info'
          }
          icon={<BusinessIcon />}
          sx={{ mb: 2 }}
          action={
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, alignItems: 'flex-end' }}>
              {entityStatus?.can_research && !entityStatus?.is_nonprofit ? (
                <Button
                  color="inherit"
                  size="small"
                  disabled={entityActionPending}
                  onClick={() => resolveEntityMutation.mutate('research_nonprofit')}
                  aria-label="Research this organization"
                >
                  {entityActionPending ? 'Working…' : 'Research organization'}
                </Button>
              ) : null}
              {entityStatus?.can_mark_nonprofit ? (
                <Button
                  color="inherit"
                  size="small"
                  disabled={entityActionPending}
                  onClick={() => {
                    if (
                      window.confirm(
                        'Mark this owner as a nonprofit? Cold mail will be deprioritized.',
                      )
                    ) {
                      resolveEntityMutation.mutate('mark_nonprofit')
                    }
                  }}
                  aria-label="Mark as nonprofit"
                >
                  Mark as nonprofit
                </Button>
              ) : null}
              {entityStatus?.can_resolve ? (
                <Button
                  color="inherit"
                  size="small"
                  disabled={entityActionPending}
                  onClick={() => resolveEntityMutation.mutate('resolve')}
                  aria-label="Resolve Illinois LLC"
                >
                  {entityActionPending ? 'Resolving…' : 'Resolve Illinois LLC'}
                </Button>
              ) : null}
            </Box>
          }
        >
          <Typography variant="body2" component="div" sx={{ fontWeight: 600 }}>
            {entityStatus?.is_nonprofit || entityStatus?.organization_org_type === 'nonprofit'
              ? 'Nonprofit / institution — cold mail deprioritized'
              : 'Entity owner — research or resolve'}
            {entityStatus?.entity_name ? ` (${entityStatus.entity_name})` : ''}
          </Typography>
          <Typography variant="caption" component="div" color="text.secondary" sx={{ mt: 0.5 }}>
            Research via IRS EO BMF, then Illinois SOS for for-profit LLCs
            {entityStatus?.nonprofit_dataset_imported_at
              ? ` · IRS EO as of ${formatDate(entityStatus.nonprofit_dataset_imported_at)}`
              : ''}
            {entityStatus?.dataset_imported_at
              ? ` · SOS as of ${formatDate(entityStatus.dataset_imported_at)}`
              : ''}
          </Typography>
          {entityStatus?.is_institutional && !entityStatus?.is_nonprofit && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              {entityStatus.is_definite_institutional
                ? 'Name looks like a public / nonprofit institution — research or mark as nonprofit.'
                : 'Name may be institutional (e.g. foundation/school) — research IRS EO or mark as nonprofit before mailing.'}
            </Typography>
          )}
          {entityStatus?.nonprofit_provider_configured === false && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              IRS EO data not loaded yet. An admin can run the IRS EO import, or mark nonprofit manually.
            </Typography>
          )}
          {entityStatus?.provider_configured === false && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              IL SOS bulk data not loaded yet. An admin must run the IL SOS import before Resolve works.
            </Typography>
          )}
          {entityStatus?.entity_lookup_status === 'unsupported_jurisdiction' && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              Non-Illinois jurisdiction not supported yet.
            </Typography>
          )}
          {entityStatus?.entity_lookup_status === 'no_match' && (
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              No match in research data — try Resolve Illinois LLC or mark as nonprofit.
            </Typography>
          )}
          {entityStatus?.entity_lookup_status === 'resolved' &&
            entityStatus.entity_lookup_person_found && (
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                Resolved — person set as primary. Skip-trace task created for phones/emails.
              </Typography>
            )}
          {entityStatus?.entity_lookup_status === 'resolved' &&
            !entityStatus.entity_lookup_person_found &&
            entityStatus.organization_org_type !== 'nonprofit' && (
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                Filing found, but no natural person (often only a corporate registered agent).
              </Typography>
            )}
          {entityStatus?.jurisdiction_supported === false &&
            entityStatus?.entity_lookup_status !== 'unsupported_jurisdiction' && (
              <Typography variant="body2" sx={{ mt: 0.5 }}>
                Non-Illinois — not supported yet.
              </Typography>
            )}
          {entityStatus?.entity_lookup_status && (
            <Chip
              size="small"
              label={entityStatus.entity_lookup_status.replace(/_/g, ' ')}
              sx={{ mt: 0.75 }}
            />
          )}
        </Alert>
      )}

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
                  sx={{ flexDirection: 'column', alignItems: 'stretch' }}
                >
                  {/* Tappable row — opens detail drawer */}
                  <ListItemButton
                    onClick={() => { setDetailContact(contact); setDetailOpen(true) }}
                    sx={{ py: 1.5, flexDirection: 'column', alignItems: 'flex-start' }}
                    aria-label={`View details for ${fullName}`}
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
                          <PhoneRow
                            key={phone.id}
                            phone={phone}
                            showLabel
                            dense={false}
                          />
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
                  </ListItemButton>

                  {/* Action buttons */}
                  <Box sx={{ display: 'flex', gap: 1, px: 2, pb: 1.5, flexWrap: 'wrap' }}>
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

      {/* Contact detail drawer */}
      <Drawer
        anchor="right"
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        PaperProps={{ sx: { width: { xs: '100%', sm: 360 }, p: 3 } }}
      >
        {detailContact && (() => {
          const fullName = [detailContact.first_name, detailContact.last_name].filter(Boolean).join(' ') || '(No name)'
          return (
            <>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6">{fullName}</Typography>
                <IconButton onClick={() => setDetailOpen(false)} aria-label="Close contact detail">
                  <CloseIcon />
                </IconButton>
              </Box>

              <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
                <Chip label={formatRole(detailContact.property_contact_role)} size="small" variant="outlined" />
                {detailContact.is_primary && <Chip label="Primary" size="small" color="primary" />}
              </Box>

              {detailContact.phones && detailContact.phones.length > 0 && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Phone</Typography>
                  {detailContact.phones.map((p) => (
                    <PhoneRow key={p.id} phone={p} showLabel dense={false} />
                  ))}
                </Box>
              )}

              {detailContact.emails && detailContact.emails.length > 0 && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Email</Typography>
                  {detailContact.emails.map((e) => (
                    <Typography key={e.id} variant="body1" sx={{ mb: 0.5 }}>
                      ✉️ <a href={`mailto:${e.value}`} style={{ textDecoration: 'none', color: 'inherit' }}>{e.value}</a>
                      {e.label && e.label !== 'other' && (
                        <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 0.5 }}>({e.label})</Typography>
                      )}
                    </Typography>
                  ))}
                </Box>
              )}

              {/* Show message if no contact info at all */}
              {(!detailContact.phones || detailContact.phones.length === 0) &&
               (!detailContact.emails || detailContact.emails.length === 0) &&
               !detailContact.notes && !detailContact.role_description && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  No contact details on file. Use Edit to add a phone number or email.
                </Typography>
              )}

              {detailContact.notes && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Notes</Typography>
                  <Typography variant="body2">{detailContact.notes}</Typography>
                </Box>
              )}

              {detailContact.role_description && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="subtitle2" color="text.secondary" gutterBottom>Role Description</Typography>
                  <Typography variant="body2">{detailContact.role_description}</Typography>
                </Box>
              )}

              <Box sx={{ display: 'flex', gap: 1, mt: 2, flexWrap: 'wrap' }}>
                <Button
                  variant="contained"
                  size="small"
                  onClick={() => { setDetailOpen(false); handleOpenEdit(detailContact) }}
                >
                  Edit
                </Button>
                {!detailContact.is_primary && (
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => { setPrimaryMutation.mutate(detailContact); setDetailOpen(false) }}
                    disabled={setPrimaryMutation.isPending}
                  >
                    Set as Primary
                  </Button>
                )}
                <Button
                  variant="outlined"
                  color="error"
                  size="small"
                  onClick={() => { setDetailOpen(false); handleRemoveClick(detailContact) }}
                >
                  Remove
                </Button>
              </Box>
            </>
          )
        })()}
      </Drawer>

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
