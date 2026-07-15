/**
 * People & Companies tab — HubSpot-style split for a property/lead.
 */
import React, { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  List,
  ListItem,
  Snackbar,
  TextField,
  Typography,
} from '@mui/material'
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import BusinessIcon from '@mui/icons-material/Business'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { contactService, organizationService } from '@/services/api'
import { entityResolutionApi } from '@/services/entityResolutionApi'
import { formatDate } from '@/utils/formatters'
import {
  contactDisplayName,
  isAddressLikeContactName,
  isEntityContactName,
  ownerDisplayEntries,
  personIdentityKey,
  personIdentityKeyFromFullName,
} from '@/utils/propertyContacts'
import { PhoneList } from '@/components/PhoneRow'
import type {
  CommandCenterPayload,
  ContactRole,
  EntityResolutionStatus,
  PropertyContact,
  PropertyOrganizationSummary,
} from '@/types'
import { ContactFormModal } from './ContactFormModal'
import {
  ccMetaSx,
  ccRowTitleSx,
  ccSectionTitleSx,
  ccSubsectionTitleSx,
} from '@/components/lead-detail/commandCenterChrome'

function formatRole(role: ContactRole): string {
  return role
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function normalizeKey(name: string): string {
  return name.toUpperCase().replace(/[^A-Z0-9]/g, '')
}

/** Fuzzy key so Halstead/Halsted and St/Street compare equal. */
function mailingAddressKey(value: string): string {
  return value
    .toUpperCase()
    .replace(/\bHALSTEAD\b/g, 'HALSTED')
    .replace(/\b(STREET|SAINT)\b/g, 'ST')
    .replace(/\b(AVENUE)\b/g, 'AVE')
    .replace(/\b(ROAD)\b/g, 'RD')
    .replace(/\b(BOULEVARD)\b/g, 'BLVD')
    .replace(/\b(DRIVE)\b/g, 'DR')
    .replace(/[^A-Z0-9]/g, '')
}

function splitDisplayName(full: string): { first_name: string | null; last_name: string | null } {
  const trimmed = full.trim()
  if (!trimmed) return { first_name: null, last_name: null }
  const parts = trimmed.split(/\s+/)
  if (parts.length === 1) return { first_name: parts[0], last_name: null }
  return { first_name: parts.slice(0, -1).join(' '), last_name: parts[parts.length - 1] }
}

type CompanyRow = {
  key: string
  name: string
  kind: 'organization' | 'legacy_contact' | 'also_listed' | 'flat'
  organizationId?: number
  contactId?: number
  meta?: string
  contact?: PropertyContact
  organization?: PropertyOrganizationSummary
}

function formatLeadMailing(cc: CommandCenterPayload | null | undefined): string | null {
  if (!cc) return null
  const line1 = (cc.mailing_address || '').trim()
  const line2 = [cc.mailing_city, cc.mailing_state, cc.mailing_zip].filter(Boolean).join(', ')
  if (!line1 && !line2) return null
  return [line1, line2].filter(Boolean).join(', ')
}

function researchChip(org: PropertyOrganizationSummary | undefined): {
  label: string
  color: 'default' | 'success' | 'warning' | 'error' | 'info'
} {
  const status = org?.entity_lookup_status
  if (!status) return { label: 'Not researched', color: 'warning' }
  if (status === 'resolved') {
    return {
      label: org?.entity_lookup_person_found ? 'Researched — person found' : 'Researched — no person on filing',
      color: 'success',
    }
  }
  if (status === 'nonprofit') return { label: 'Nonprofit', color: 'success' }
  if (status === 'no_match') return { label: 'No SOS match', color: 'warning' }
  if (status === 'unsupported_jurisdiction') return { label: 'Non-IL — not researched', color: 'warning' }
  if (status === 'error') return { label: 'Research error', color: 'error' }
  if (status === 'pending') return { label: 'Research pending', color: 'info' }
  return { label: String(status).replace(/_/g, ' '), color: 'default' }
}

export interface ContactsSectionProps {
  propertyId: number
  /** Prefer parent command-center payload so Companies matches the sidebar. */
  commandCenterData?: CommandCenterPayload | null
}

export const ContactsSection: React.FC<ContactsSectionProps> = ({
  propertyId,
  commandCenterData,
}) => {
  const queryClient = useQueryClient()

  const [formOpen, setFormOpen] = useState(false)
  const [editingContact, setEditingContact] = useState<PropertyContact | undefined>(undefined)
  const [companyDialogOpen, setCompanyDialogOpen] = useState(false)
  const [companyName, setCompanyName] = useState('')

  const [removeDialogOpen, setRemoveDialogOpen] = useState(false)
  const [contactToRemove, setContactToRemove] = useState<PropertyContact | null>(null)

  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  const [snackbar, setSnackbar] = useState<{
    open: boolean
    message: string
    severity: 'error' | 'success'
  }>({ open: false, message: '', severity: 'error' })

  const showError = (message: string) =>
    setSnackbar({ open: true, message, severity: 'error' })
  const showSuccess = (message: string) =>
    setSnackbar({ open: true, message, severity: 'success' })

  const {
    data: contacts,
    isLoading,
    error: fetchError,
  } = useQuery<PropertyContact[]>({
    queryKey: ['propertyContacts', propertyId],
    queryFn: () => contactService.getPropertyContacts(propertyId),
  })

  const { data: entityStatus } = useQuery<EntityResolutionStatus>({
    queryKey: ['entityResolution', propertyId],
    queryFn: () => entityResolutionApi.getStatus(propertyId),
  })

  const cc = commandCenterData
  const organizations: PropertyOrganizationSummary[] = useMemo(() => {
    const orgs = [...(cc?.organizations ?? [])]
    if (!entityStatus) return orgs

    const enrich = (org: PropertyOrganizationSummary): PropertyOrganizationSummary => {
      const matchesId =
        entityStatus.organization_id != null && org.id === entityStatus.organization_id
      const matchesName =
        !!entityStatus.entity_name
        && normalizeKey(entityStatus.entity_name) === normalizeKey(org.name || '')
      if (!matchesId && !matchesName) return org

      const statusMissing = !org.entity_lookup_status
      const statusStalePending =
        org.entity_lookup_status === 'pending'
        && entityStatus.entity_lookup_status === 'resolved'
      const needsPerson =
        !org.resolved_person_name && !!entityStatus.resolved_person_name
      const needsOffice =
        !org.registered_office_address && !!entityStatus.registered_office_address
      if (
        !statusMissing
        && !statusStalePending
        && !needsPerson
        && !needsOffice
      ) {
        return org
      }
      return {
        ...org,
        entity_lookup_status:
          entityStatus.entity_lookup_status ?? org.entity_lookup_status,
        entity_lookup_person_found:
          entityStatus.entity_lookup_person_found ?? org.entity_lookup_person_found,
        entity_lookup_checked_at:
          entityStatus.entity_lookup_checked_at ?? org.entity_lookup_checked_at,
        entity_lookup_error:
          entityStatus.entity_lookup_error ?? org.entity_lookup_error,
        registered_office_address:
          org.registered_office_address
          || entityStatus.registered_office_address
          || null,
        registered_agent_name:
          org.registered_agent_name || entityStatus.registered_agent_name || null,
        file_number: org.file_number || entityStatus.file_number || null,
        resolved_person_name:
          org.resolved_person_name || entityStatus.resolved_person_name || null,
        resolved_person_role:
          org.resolved_person_role || entityStatus.resolved_person_role || null,
      }
    }

    const enriched = orgs.map(enrich)
    const hasStatusOrg =
      entityStatus.organization_id != null
      && enriched.some((o) => o.id === entityStatus.organization_id)
    if (
      !hasStatusOrg
      && entityStatus.organization_id != null
      && (entityStatus.organization_name || entityStatus.entity_name)
    ) {
      enriched.push({
        id: entityStatus.organization_id,
        name: entityStatus.organization_name || entityStatus.entity_name || 'Company',
        org_type: entityStatus.organization_org_type ?? 'llc',
        role: 'owner',
        link_id: 0,
        entity_lookup_status: entityStatus.entity_lookup_status,
        entity_lookup_person_found: entityStatus.entity_lookup_person_found,
        entity_lookup_checked_at: entityStatus.entity_lookup_checked_at,
        entity_lookup_error: entityStatus.entity_lookup_error,
        registered_office_address: entityStatus.registered_office_address ?? null,
        registered_agent_name: entityStatus.registered_agent_name ?? null,
        file_number: entityStatus.file_number ?? null,
        resolved_person_name: entityStatus.resolved_person_name ?? null,
        resolved_person_role: entityStatus.resolved_person_role ?? null,
      })
    }
    return enriched
  }, [cc?.organizations, entityStatus])

  const peopleContacts = useMemo(() => {
    const people = (contacts ?? []).filter(
      (c) => !isEntityContactName(c) && !isAddressLikeContactName(c),
    )
    const byKey = new Map<string, PropertyContact>()
    for (const person of people) {
      const key = personIdentityKey(person) || `id:${person.id}`
      const existing = byKey.get(key)
      if (!existing) {
        byKey.set(key, person)
        continue
      }
      const preferNew =
        (person.is_primary && !existing.is_primary)
        || (
          !existing.is_primary
          && !person.is_primary
          && (person.first_name || '').length > (existing.first_name || '').length
        )
      if (preferNew) byKey.set(key, person)
    }
    return Array.from(byKey.values())
  }, [contacts])

  const leftoverEntityContacts = useMemo(
    () => (contacts ?? []).filter((c) => isEntityContactName(c)),
    [contacts],
  )

  const addressLikeContacts = useMemo(
    () => (contacts ?? []).filter((c) => isAddressLikeContactName(c)),
    [contacts],
  )

  const companyRows: CompanyRow[] = useMemo(() => {
    const rows: CompanyRow[] = []
    const seen = new Set<string>()
    const orgByKey = new Map(
      organizations
        .map((org) => [normalizeKey(org.name || ''), org] as const)
        .filter(([key]) => !!key),
    )

    const push = (row: CompanyRow) => {
      const key = normalizeKey(row.name)
      if (!key || seen.has(key)) return
      seen.add(key)
      rows.push(row)
    }

    for (const org of organizations) {
      const name = (org.name || '').trim()
      if (!name) continue
      push({
        key: `org-${org.id}`,
        name,
        kind: 'organization',
        organizationId: org.id,
        organization: org,
        meta: [org.org_type, org.role].filter(Boolean).join(' · '),
      })
    }

    // Align with sidebar: flat Owner2 / entity leftovers when not already an org row
    const displayEntries = ownerDisplayEntries(
      null,
      cc?.owner_first_name,
      cc?.owner_last_name,
      cc?.owner_2_first_name,
      cc?.owner_2_last_name,
      organizations,
    )
    for (const entry of displayEntries) {
      if (entry.label !== 'Company') continue
      const matched = orgByKey.get(normalizeKey(entry.name))
      if (matched) {
        push({
          key: `org-${matched.id}`,
          name: matched.name || entry.name,
          kind: 'organization',
          organizationId: matched.id,
          organization: matched,
          meta: [matched.org_type, matched.role].filter(Boolean).join(' · '),
        })
        continue
      }
      push({
        key: `flat-${normalizeKey(entry.name)}`,
        name: entry.name,
        kind: 'flat',
        organizationId: entry.organizationId,
        meta: entry.organizationId ? undefined : 'From lead Owner 2',
      })
    }

    for (const c of leftoverEntityContacts) {
      const name = contactDisplayName(c)
      if (!name) continue
      const matched = orgByKey.get(normalizeKey(name))
      if (matched) {
        push({
          key: `org-${matched.id}`,
          name: matched.name || name,
          kind: 'organization',
          organizationId: matched.id,
          organization: matched,
          meta: [matched.org_type, matched.role].filter(Boolean).join(' · '),
        })
        continue
      }
      push({
        key: `legacy-${c.id}`,
        name,
        kind: 'legacy_contact',
        contactId: c.id,
        contact: c,
        meta: 'Legacy contact row',
      })
    }

    for (const c of addressLikeContacts) {
      const name = contactDisplayName(c)
      if (!name) continue
      push({
        key: `also-${c.id}`,
        name,
        kind: 'also_listed',
        contactId: c.id,
        contact: c,
        meta: 'Also listed (not a person)',
      })
    }

    return rows
  }, [
    organizations,
    leftoverEntityContacts,
    addressLikeContacts,
    cc?.owner_first_name,
    cc?.owner_last_name,
    cc?.owner_2_first_name,
    cc?.owner_2_last_name,
  ])

  const leadMailing = formatLeadMailing(cc)
  const researchedOffice = organizations.find((o) => o.registered_office_address)?.registered_office_address
  const mailingCoveredByCompany =
    !!researchedOffice
    && (
      !leadMailing
      || mailingAddressKey(leadMailing) === mailingAddressKey(researchedOffice)
    )
  // When SOS gave the company an office, show it on the company — not a floating lead banner.
  const showLeadMailingBanner = !!leadMailing && !researchedOffice

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
        showError(result.message || 'No match found in Illinois SOS data.')
        return
      }
      showError(result.message || `Entity resolution: ${result.status}`)
    },
    onError: (err: Error) => showError(err.message || 'Failed to resolve entity.'),
  })

  const entityActionPending = resolveEntityMutation.isPending

  const needsResearch = (row: CompanyRow): boolean => {
    if (row.kind !== 'organization' && row.kind !== 'flat') return false
    const status = row.organization?.entity_lookup_status
    return !status || status === 'no_match' || status === 'error' || status === 'pending'
  }

  const addCompanyMutation = useMutation({
    mutationFn: async (name: string) => {
      const org = await organizationService.createOrganization({
        name,
        org_type: 'llc',
        status: 'unknown',
        source: 'manual',
      } as Parameters<typeof organizationService.createOrganization>[0])
      await organizationService.linkOrganizationToProperty(org.id, propertyId, 'owner')
      return org
    },
    onSuccess: (org) => {
      queryClient.invalidateQueries({ queryKey: ['commandCenter', propertyId] })
      queryClient.invalidateQueries({ queryKey: ['entityResolution', propertyId] })
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      setCompanyDialogOpen(false)
      setCompanyName('')
      showSuccess(`Company added: ${org.name}`)
    },
    onError: (err: Error) => showError(err.message || 'Failed to add company.'),
  })

  const setPrimaryMutation = useMutation({
    mutationFn: (contact: PropertyContact) =>
      contactService.linkContactToProperty(propertyId, {
        contact_id: contact.id,
        role: contact.property_contact_role,
        is_primary: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      queryClient.invalidateQueries({ queryKey: ['commandCenter', propertyId] })
      showSuccess('Contact set as primary.')
    },
    onError: (err: Error) => showError(err.message || 'Failed to set primary contact.'),
  })

  const removeMutation = useMutation({
    mutationFn: (contactId: number) =>
      contactService.unlinkContactFromProperty(propertyId, contactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      queryClient.invalidateQueries({ queryKey: ['commandCenter', propertyId] })
      showSuccess('Contact removed.')
    },
    onError: (err: Error) => showError(err.message || 'Failed to remove contact.'),
  })

  const saveNameMutation = useMutation({
    mutationFn: async ({
      row,
      name,
    }: {
      row: { type: 'person'; contact: PropertyContact } | { type: 'company'; company: CompanyRow }
      name: string
    }) => {
      if (row.type === 'person') {
        const parts = splitDisplayName(name)
        await contactService.updateContact(row.contact.id, parts)
        return
      }
      const company = row.company
      if (company.organizationId != null) {
        await organizationService.updateOrganization(company.organizationId, { name })
        return
      }
      if (company.contactId != null) {
        const parts = splitDisplayName(name)
        await contactService.updateContact(company.contactId, parts)
        return
      }
      // Flat-only company name: create/link org with the corrected spelling
      const org = await organizationService.createOrganization({
        name,
        org_type: 'llc',
        status: 'unknown',
        source: 'manual',
      } as Parameters<typeof organizationService.createOrganization>[0])
      await organizationService.linkOrganizationToProperty(org.id, propertyId, 'owner')
    },
    onSuccess: () => {
      setEditingKey(null)
      setEditValue('')
      queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
      queryClient.invalidateQueries({ queryKey: ['commandCenter', propertyId] })
      showSuccess('Name updated.')
    },
    onError: (err: Error) => showError(err.message || 'Failed to update name.'),
  })

  const startEdit = (key: string, current: string) => {
    setEditingKey(key)
    setEditValue(current)
  }

  const cancelEdit = () => {
    setEditingKey(null)
    setEditValue('')
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography component="h3" sx={ccSectionTitleSx}>
          People & Companies
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            size="small"
            startIcon={<BusinessIcon />}
            onClick={() => setCompanyDialogOpen(true)}
            aria-label="Add company"
            data-testid="add-company-btn"
          >
            Add Company
          </Button>
          <Button
            variant="contained"
            size="small"
            startIcon={<PersonAddIcon />}
            onClick={() => {
              setEditingContact(undefined)
              setFormOpen(true)
            }}
            aria-label="Add contact"
          >
            Add Contact
          </Button>
        </Box>
      </Box>

      <Typography sx={ccSubsectionTitleSx} data-testid="companies-heading">
        Companies
      </Typography>

      {showLeadMailingBanner && (
        <Alert severity="info" variant="outlined" sx={{ mb: 2 }} data-testid="lead-mailing-address">
          <Typography variant="body2" fontWeight={600}>
            Property mailing address
          </Typography>
          <Typography variant="body2">{leadMailing}</Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            Stored on the lead — not linked to a company yet. After Illinois SOS research, it
            appears on the company as the registered office.
          </Typography>
        </Alert>
      )}

      {companyRows.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          No companies linked yet. Use Add Company for LLCs / entities.
        </Typography>
      ) : (
        <List disablePadding sx={{ mb: 2 }} data-testid="companies-list">
          {companyRows.map((row, index) => {
            const chip =
              row.kind === 'also_listed'
                ? { label: 'Also listed (not a person)', color: 'default' as const }
                : row.kind === 'organization' || row.kind === 'flat'
                  ? researchChip(row.organization)
                  : { label: 'Legacy contact', color: 'default' as const }
            const showResolve =
              (row.kind === 'organization' || row.kind === 'flat') && needsResearch(row)
            return (
              <React.Fragment key={row.key}>
                {index > 0 && <Divider />}
                <ListItem
                  sx={{ flexDirection: 'column', alignItems: 'stretch', py: 1.25 }}
                  data-testid={
                    row.kind === 'also_listed' ? 'company-also-listed-row' : 'company-row'
                  }
                >
                  {editingKey === row.key ? (
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', width: '100%' }}>
                      <TextField
                        size="small"
                        fullWidth
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        inputProps={{ 'data-testid': 'company-name-edit-input' }}
                      />
                      <IconButton
                        size="small"
                        color="primary"
                        aria-label="Save name"
                        disabled={!editValue.trim() || saveNameMutation.isPending}
                        onClick={() =>
                          saveNameMutation.mutate({
                            row: { type: 'company', company: row },
                            name: editValue.trim(),
                          })
                        }
                      >
                        <CheckIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" aria-label="Cancel edit" onClick={cancelEdit}>
                        <CloseIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  ) : (
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, width: '100%' }}>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                          <Typography sx={ccRowTitleSx}>
                            {row.name}
                          </Typography>
                          <Chip size="small" label={chip.label} color={chip.color} variant="outlined" />
                        </Box>
                        {row.meta && row.kind !== 'also_listed' && (
                          <Typography variant="caption" color="text.secondary" display="block">
                            {row.meta}
                          </Typography>
                        )}
                        {row.organization?.resolved_person_name && (
                          <Typography
                            variant="body2"
                            sx={{ mt: 0.75 }}
                            data-testid="org-resolved-person"
                          >
                            {row.organization.resolved_person_role
                              ? `${row.organization.resolved_person_role.charAt(0).toUpperCase()}${row.organization.resolved_person_role.slice(1)}`
                              : 'Person'}
                            {' found: '}
                            <Box component="span" fontWeight={600}>
                              {row.organization.resolved_person_name}
                            </Box>
                          </Typography>
                        )}
                        {(row.organization?.registered_office_address
                          || (mailingCoveredByCompany && leadMailing && row.kind === 'organization')) && (
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5 }}
                            data-testid="org-registered-office"
                          >
                            Registered office:{' '}
                            {row.organization?.registered_office_address || leadMailing}
                          </Typography>
                        )}
                        {row.organization?.registered_agent_name
                          && row.organization.registered_agent_name
                            !== row.organization.resolved_person_name && (
                          <Typography variant="caption" color="text.secondary" display="block">
                            Registered agent: {row.organization.registered_agent_name}
                          </Typography>
                        )}
                        {row.organization?.entity_lookup_checked_at && (
                          <Typography variant="caption" color="text.secondary" display="block">
                            Researched {formatDate(row.organization.entity_lookup_checked_at)}
                            {row.organization.file_number
                              ? ` · file ${row.organization.file_number}`
                              : ''}
                          </Typography>
                        )}
                        {row.contact?.phones?.length ? (
                          <PhoneList phones={row.contact.phones} showLabel dense={false} />
                        ) : null}
                        {row.contact?.emails?.map((email) => (
                          <Typography
                            key={email.id}
                            variant="body2"
                            color="text.secondary"
                            data-testid="company-row-email"
                          >
                            {email.value}
                          </Typography>
                        ))}
                        {showResolve && (
                          <Box sx={{ mt: 1 }}>
                            <Button
                              size="small"
                              variant="outlined"
                              disabled={entityActionPending}
                              onClick={() => resolveEntityMutation.mutate('resolve')}
                              data-testid="resolve-llc-btn"
                            >
                              {entityActionPending ? 'Researching…' : 'Research Illinois LLC'}
                            </Button>
                          </Box>
                        )}
                      </Box>
                      <IconButton
                        size="small"
                        aria-label={`Edit ${row.name}`}
                        onClick={() => startEdit(row.key, row.name)}
                        data-testid="edit-company-name-btn"
                      >
                        <EditOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  )}
                </ListItem>
              </React.Fragment>
            )
          })}
        </List>
      )}

      <Typography sx={{ ...ccSubsectionTitleSx, mt: 2 }} data-testid="people-heading">
        People
      </Typography>

      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={32} aria-label="Loading contacts" />
        </Box>
      )}

      {fetchError && !isLoading && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert">
          {fetchError instanceof Error ? fetchError.message : 'Failed to load contacts.'}
        </Alert>
      )}

      {!isLoading && !fetchError && peopleContacts.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No people linked yet. Use Add Contact to link one.
        </Typography>
      )}

      {!isLoading && !fetchError && peopleContacts.length > 0 && (
        <List disablePadding data-testid="people-list">
          {peopleContacts.map((contact, index) => {
            const fullName =
              [contact.first_name, contact.last_name].filter(Boolean).join(' ') || '(No name)'
            const personKey = `person-${contact.id}`
            return (
              <React.Fragment key={contact.id}>
                {index > 0 && <Divider />}
                <ListItem
                  sx={{ flexDirection: 'column', alignItems: 'stretch', py: 1.25 }}
                  data-testid={`person-row-${contact.id}`}
                >
                  {editingKey === personKey ? (
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', width: '100%' }}>
                      <TextField
                        size="small"
                        fullWidth
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        inputProps={{ 'data-testid': 'person-name-edit-input' }}
                      />
                      <IconButton
                        size="small"
                        color="primary"
                        aria-label="Save name"
                        disabled={!editValue.trim() || saveNameMutation.isPending}
                        onClick={() =>
                          saveNameMutation.mutate({
                            row: { type: 'person', contact },
                            name: editValue.trim(),
                          })
                        }
                      >
                        <CheckIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" aria-label="Cancel edit" onClick={cancelEdit}>
                        <CloseIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  ) : (
                    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, width: '100%' }}>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                          <Typography
                            sx={{
                              ...ccRowTitleSx,
                              fontWeight: contact.is_primary ? 500 : 400,
                            }}
                          >
                            {fullName}
                          </Typography>
                          {contact.is_primary && (
                            <Chip size="small" label="Primary" color="primary" />
                          )}
                          {contact.property_contact_role && (
                            <Chip
                              size="small"
                              label={formatRole(contact.property_contact_role)}
                              variant="outlined"
                            />
                          )}
                        </Box>
                        {contact.phones?.length ? (
                          <PhoneList phones={contact.phones} showLabel dense={false} />
                        ) : null}
                        {contact.emails?.map((email) => (
                          <Typography key={email.id} variant="body2" color="text.secondary">
                            {email.value}
                          </Typography>
                        ))}
                        {organizations
                          .filter(
                            (org) =>
                              org.resolved_person_name
                              && personIdentityKeyFromFullName(org.resolved_person_name)
                                === personIdentityKey(contact),
                          )
                          .map((org) => (
                            <Typography
                              key={`mgr-${org.id}`}
                              sx={{ ...ccMetaSx, mt: 0.5 }}
                              data-testid="person-company-role"
                            >
                              Appears to be the{' '}
                              {(org.resolved_person_role || 'manager').toLowerCase()} of{' '}
                              <Box component="span" fontWeight={600}>
                                {org.name}
                              </Box>
                            </Typography>
                          ))}
                      </Box>
                      <IconButton
                        size="small"
                        aria-label={`Edit ${fullName}`}
                        onClick={() => startEdit(personKey, fullName)}
                        data-testid="edit-person-name-btn"
                      >
                        <EditOutlinedIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  )}
                  <Box sx={{ display: 'flex', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                    {!contact.is_primary && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => setPrimaryMutation.mutate(contact)}
                        disabled={setPrimaryMutation.isPending}
                      >
                        Set as Primary
                      </Button>
                    )}
                    <Button
                      size="small"
                      variant="outlined"
                      onClick={() => {
                        setEditingContact(contact)
                        setFormOpen(true)
                      }}
                    >
                      Edit details
                    </Button>
                    <Button
                      size="small"
                      variant="outlined"
                      color="error"
                      onClick={() => {
                        setContactToRemove(contact)
                        setRemoveDialogOpen(true)
                      }}
                      disabled={removeMutation.isPending}
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

      <Dialog open={companyDialogOpen} onClose={() => setCompanyDialogOpen(false)}>
        <DialogTitle>Add Company</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="Company name"
            fullWidth
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            inputProps={{ 'data-testid': 'company-name-input' }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCompanyDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!companyName.trim() || addCompanyMutation.isPending}
            onClick={() => addCompanyMutation.mutate(companyName.trim())}
          >
            {addCompanyMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={removeDialogOpen} onClose={() => setRemoveDialogOpen(false)}>
        <DialogTitle>Remove contact?</DialogTitle>
        <DialogContent>
          <Typography>
            Unlink{' '}
            {contactToRemove
              ? [contactToRemove.first_name, contactToRemove.last_name].filter(Boolean).join(' ')
              : 'this contact'}{' '}
            from this property?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRemoveDialogOpen(false)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => {
              if (contactToRemove) removeMutation.mutate(contactToRemove.id)
              setRemoveDialogOpen(false)
              setContactToRemove(null)
            }}
          >
            Remove
          </Button>
        </DialogActions>
      </Dialog>

      <ContactFormModal
        open={formOpen}
        onClose={() => {
          setFormOpen(false)
          setEditingContact(undefined)
          queryClient.invalidateQueries({ queryKey: ['propertyContacts', propertyId] })
          queryClient.invalidateQueries({ queryKey: ['commandCenter', propertyId] })
        }}
        propertyId={propertyId}
        contact={editingContact}
      />

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity={snackbar.severity}
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  )
}

export default ContactsSection
