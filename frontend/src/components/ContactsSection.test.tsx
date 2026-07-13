/**
 * Tests for ContactsSection — People vs Companies split.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import { ContactsSection } from './ContactsSection'
import { contactService } from '@/services/api'
import type { CommandCenterPayload, PropertyContact } from '@/types'

vi.mock('@/services/api', () => ({
  contactService: {
    getPropertyContacts: vi.fn(),
    linkContactToProperty: vi.fn(),
    unlinkContactFromProperty: vi.fn(),
    createContact: vi.fn(),
    updateContact: vi.fn(),
    deleteContact: vi.fn(),
    getContact: vi.fn(),
  },
  organizationService: {
    createOrganization: vi.fn(),
    linkOrganizationToProperty: vi.fn(),
    updateOrganization: vi.fn(),
  },
  commandCenterService: {
    getCommandCenter: vi.fn(),
  },
}))

vi.mock('@/services/entityResolutionApi', () => ({
  entityResolutionApi: {
    getStatus: vi.fn().mockResolvedValue({
      lead_id: 42,
      primary_is_entity: false,
      entity_name: null,
      jurisdiction_supported: true,
      supported_jurisdiction: 'us_il',
      organization_id: null,
    }),
    resolve: vi.fn(),
  },
}))

vi.mock('./ContactFormModal', () => ({
  ContactFormModal: ({ open }: { open: boolean }) =>
    open ? <div data-testid="contact-form-modal">ContactFormModal</div> : null,
}))

const PROPERTY_ID = 42

const mockPrimaryContact: PropertyContact = {
  id: 1,
  first_name: 'Alice',
  last_name: 'Smith',
  role: 'owner',
  role_description: null,
  notes: null,
  property_contact_role: 'owner',
  is_primary: true,
  phones: [{ id: 10, contact_id: 1, value: '555-1111', label: 'mobile' }],
  emails: [{ id: 20, contact_id: 1, value: 'alice@example.com', label: 'personal' }],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

const mockSecondaryContact: PropertyContact = {
  id: 2,
  first_name: 'Bob',
  last_name: 'Jones',
  role: 'property_manager',
  role_description: null,
  notes: null,
  property_contact_role: 'property_manager',
  is_primary: false,
  phones: [{ id: 11, contact_id: 2, value: '555-2222', label: 'work' }],
  emails: [{ id: 21, contact_id: 2, value: 'bob@example.com', label: 'work' }],
  created_at: '2024-01-02T00:00:00Z',
  updated_at: '2024-01-02T00:00:00Z',
}

const addressLikeContact: PropertyContact = {
  id: 3,
  first_name: '3508SACRAMENTO',
  last_name: 'MAYNARD',
  role: 'owner',
  role_description: null,
  notes: null,
  property_contact_role: 'owner',
  is_primary: true,
  phones: [],
  emails: [],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ContactsSection', () => {
  it('renders people with phones and emails', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
      mockPrimaryContact,
      mockSecondaryContact,
    ])

    render(<ContactsSection propertyId={PROPERTY_ID} />)

    await waitFor(() => {
      expect(screen.getByText('Alice Smith')).toBeInTheDocument()
      expect(screen.getByText('Bob Jones')).toBeInTheDocument()
    })
    expect(screen.getByText(/555-1111/)).toBeInTheDocument()
    expect(screen.getByText(/alice@example\.com/)).toBeInTheDocument()
  })

  it('puts address-like names under Companies, not People', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
      mockPrimaryContact,
      addressLikeContact,
    ])

    render(
      <ContactsSection
        propertyId={PROPERTY_ID}
        commandCenterData={
          {
            id: PROPERTY_ID,
            organizations: [
              {
                id: 10,
                name: 'Kdg Avondale LLC',
                org_type: 'llc',
                role: 'owner',
                link_id: 1,
              },
            ],
          } as CommandCenterPayload
        }
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Kdg Avondale LLC')).toBeInTheDocument()
      expect(screen.getByText('3508SACRAMENTO MAYNARD')).toBeInTheDocument()
    })
    expect(screen.getByTestId('company-also-listed-row')).toBeInTheDocument()
    expect(screen.getByTestId('people-list')).toHaveTextContent('Alice Smith')
    expect(screen.getByTestId('people-list')).not.toHaveTextContent('3508SACRAMENTO')
  })

  it('shows linked company from commandCenterData even with no contacts', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([])

    render(
      <ContactsSection
        propertyId={PROPERTY_ID}
        commandCenterData={
          {
            id: PROPERTY_ID,
            organizations: [
              {
                id: 10,
                name: 'Kdg Avondale LLC',
                org_type: 'llc',
                role: 'owner',
                link_id: 1,
              },
            ],
          } as CommandCenterPayload
        }
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Kdg Avondale LLC')).toBeInTheDocument()
    })
    expect(screen.queryByText(/No companies linked yet/i)).not.toBeInTheDocument()
  })

  it('calls linkContactToProperty when Set as Primary is clicked', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
      mockPrimaryContact,
      mockSecondaryContact,
    ])
    vi.mocked(contactService.linkContactToProperty).mockResolvedValue({
      ...mockSecondaryContact,
      is_primary: true,
    })

    render(<ContactsSection propertyId={PROPERTY_ID} />)

    await waitFor(() => expect(screen.getByText('Bob Jones')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /set as primary/i }))

    await waitFor(() => {
      expect(contactService.linkContactToProperty).toHaveBeenCalledWith(PROPERTY_ID, {
        contact_id: mockSecondaryContact.id,
        role: mockSecondaryContact.property_contact_role,
        is_primary: true,
      })
    })
  })

  it('opens ContactFormModal from Add Contact', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([])
    render(<ContactsSection propertyId={PROPERTY_ID} />)
    fireEvent.click(screen.getByRole('button', { name: /add contact/i }))
    await waitFor(() => {
      expect(screen.getByTestId('contact-form-modal')).toBeInTheDocument()
    })
  })

  it('surfaces fetch errors', async () => {
    vi.mocked(contactService.getPropertyContacts).mockRejectedValue(
      new Error('Failed to load contacts'),
    )
    render(<ContactsSection propertyId={PROPERTY_ID} />)
    await waitFor(() => {
      expect(screen.getByText('Failed to load contacts')).toBeInTheDocument()
    })
  })

  it('allows pencil edit of a person name', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([mockPrimaryContact])
    vi.mocked(contactService.updateContact).mockResolvedValue(mockPrimaryContact)

    render(<ContactsSection propertyId={PROPERTY_ID} />)
    await waitFor(() => expect(screen.getByText('Alice Smith')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('edit-person-name-btn'))
    const input = screen.getByTestId('person-name-edit-input')
    fireEvent.change(input, { target: { value: 'Alicia Smith' } })
    fireEvent.click(screen.getByLabelText('Save name'))

    await waitFor(() => {
      expect(contactService.updateContact).toHaveBeenCalledWith(1, {
        first_name: 'Alicia',
        last_name: 'Smith',
      })
    })
  })

  it('shows email on Also listed company rows', async () => {
    const withEmail: PropertyContact = {
      ...addressLikeContact,
      emails: [{ id: 99, contact_id: 3, value: 'marvinpoer@mfpoer.com', label: 'other' }],
    }
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
      mockPrimaryContact,
      withEmail,
    ])

    render(
      <ContactsSection
        propertyId={PROPERTY_ID}
        commandCenterData={
          {
            id: PROPERTY_ID,
            mailing_address: '2115 S Halstead St',
            mailing_city: 'Chicago',
            mailing_state: 'IL',
            mailing_zip: '60608',
            organizations: [
              {
                id: 10,
                name: 'Kdg Avondale LLC',
                org_type: 'llc',
                role: 'owner',
                link_id: 1,
                entity_lookup_status: null,
              },
            ],
          } as CommandCenterPayload
        }
      />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('company-row-email')).toHaveTextContent('marvinpoer@mfpoer.com')
    })
    expect(screen.getByTestId('lead-mailing-address')).toHaveTextContent('2115 S Halstead St')
    expect(screen.getByText('Not researched')).toBeInTheDocument()
    expect(screen.queryByTestId('companies-entity-banner')).not.toBeInTheDocument()
  })

  it('shows manager and registered office on researched company; hides orphan mailing bar', async () => {
    const { entityResolutionApi } = await import('@/services/entityResolutionApi')
    vi.mocked(entityResolutionApi.getStatus).mockResolvedValue({
      lead_id: PROPERTY_ID,
      primary_is_entity: false,
      entity_name: 'Kdg Avondale LLC',
      jurisdiction_supported: true,
      supported_jurisdiction: 'us_il',
      organization_id: 10,
      organization_name: 'Kdg Avondale LLC',
      entity_lookup_status: 'resolved',
      entity_lookup_person_found: true,
      entity_lookup_error: null,
      entity_lookup_checked_at: '2026-07-13T12:00:00Z',
      entity_lookup_provider: 'ilsos_bulk',
      registered_office_address: '2115 S HALSTED ST, CHICAGO, 60608-4519',
      resolved_person_name: 'JOSEPH A KIFERBAUM',
      resolved_person_role: 'manager',
      can_resolve: false,
    })
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([mockPrimaryContact])

    render(
      <ContactsSection
        propertyId={PROPERTY_ID}
        commandCenterData={
          {
            id: PROPERTY_ID,
            mailing_address: '2115 S Halstead St',
            mailing_city: 'Chicago',
            mailing_state: 'IL',
            mailing_zip: '60608',
            organizations: [
              {
                id: 10,
                name: 'Kdg Avondale LLC',
                org_type: 'llc',
                role: 'owner',
                link_id: 1,
                entity_lookup_status: 'resolved',
                entity_lookup_person_found: true,
                registered_office_address: '2115 S HALSTED ST, CHICAGO, 60608-4519',
                resolved_person_name: 'JOSEPH A KIFERBAUM',
                resolved_person_role: 'manager',
              },
            ],
          } as CommandCenterPayload
        }
      />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('org-resolved-person')).toHaveTextContent('JOSEPH A KIFERBAUM')
    })
    expect(screen.getByTestId('org-registered-office')).toHaveTextContent(/2115 S HALSTED/i)
    expect(screen.queryByTestId('lead-mailing-address')).not.toBeInTheDocument()
  })

  it('shows researched chip from entity status when CC org status is stale', async () => {
    const { entityResolutionApi } = await import('@/services/entityResolutionApi')
    vi.mocked(entityResolutionApi.getStatus).mockResolvedValue({
      lead_id: PROPERTY_ID,
      primary_is_entity: false,
      entity_name: 'Kdg Avondale LLC',
      jurisdiction_supported: true,
      supported_jurisdiction: 'us_il',
      organization_id: 10,
      organization_name: 'Kdg Avondale LLC',
      entity_lookup_status: 'resolved',
      entity_lookup_person_found: true,
      entity_lookup_error: null,
      entity_lookup_checked_at: '2026-07-13T12:00:00Z',
      entity_lookup_provider: 'ilsos_bulk',
      registered_office_address: '2115 S HALSTED ST, CHICAGO, 60608-4519',
      can_resolve: false,
    })
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([mockPrimaryContact])

    render(
      <ContactsSection
        propertyId={PROPERTY_ID}
        commandCenterData={
          {
            id: PROPERTY_ID,
            organizations: [
              {
                id: 10,
                name: 'Kdg Avondale LLC',
                org_type: 'llc',
                role: 'owner',
                link_id: 1,
                entity_lookup_status: null,
              },
            ],
          } as CommandCenterPayload
        }
      />,
    )

    await waitFor(() => {
      expect(screen.getByText(/Researched — person found/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/^Not researched$/i)).not.toBeInTheDocument()
  })

  it('dedupes Joseph / JOSEPH A in People', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
      {
        ...mockPrimaryContact,
        id: 1170,
        first_name: 'Joseph',
        last_name: 'Kiferbaum',
        is_primary: false,
      },
      {
        ...mockPrimaryContact,
        id: 5269,
        first_name: 'JOSEPH A',
        last_name: 'KIFERBAUM',
        is_primary: true,
        phones: [],
        emails: [],
      },
    ])

    render(<ContactsSection propertyId={PROPERTY_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('people-list')).toHaveTextContent('JOSEPH A KIFERBAUM')
    })
    expect(screen.getByTestId('people-list')).not.toHaveTextContent('Joseph Kiferbaum')
  })

  it('shows company manager role under the matching person', async () => {
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
      {
        ...mockPrimaryContact,
        id: 5269,
        first_name: 'JOSEPH A',
        last_name: 'KIFERBAUM',
        is_primary: true,
        phones: [],
        emails: [],
      },
    ])

    render(
      <ContactsSection
        propertyId={PROPERTY_ID}
        commandCenterData={
          {
            id: PROPERTY_ID,
            organizations: [
              {
                id: 10,
                name: 'Kdg Avondale LLC',
                org_type: 'llc',
                role: 'owner',
                link_id: 1,
                entity_lookup_status: 'resolved',
                entity_lookup_person_found: true,
                resolved_person_name: 'JOSEPH A KIFERBAUM',
                resolved_person_role: 'manager',
              },
            ],
          } as CommandCenterPayload
        }
      />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('person-company-role')).toHaveTextContent(
        /manager of\s+Kdg Avondale LLC/i,
      )
    })
  })
})
