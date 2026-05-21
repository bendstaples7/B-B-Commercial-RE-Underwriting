/**
 * Tests for ContactsSection component
 *
 * Covers:
 * - Renders contact list with name, role, phones, emails for each linked contact
 * - Renders primary-contact badge on the primary contact
 * - "Set as Primary" button calls contactService.linkContactToProperty with correct arguments
 * - "Remove" button calls contactService.unlinkContactFromProperty with correct property and contact IDs
 * - "Add Contact" button opens ContactFormModal
 * - API error from contacts fetch is surfaced via Snackbar / Alert
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import { ContactsSection } from './ContactsSection'
import { contactService } from '@/services/api'
import type { PropertyContact } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

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
}))

// ---------------------------------------------------------------------------
// Mock ContactFormModal — it's a separate component tested elsewhere
// ---------------------------------------------------------------------------

vi.mock('./ContactFormModal', () => ({
  ContactFormModal: ({ open }: { open: boolean }) =>
    open ? <div data-testid="contact-form-modal">ContactFormModal</div> : null,
}))

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

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
  phones: [
    { id: 10, contact_id: 1, value: '555-1111', label: 'mobile' },
  ],
  emails: [
    { id: 20, contact_id: 1, value: 'alice@example.com', label: 'personal' },
  ],
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
  phones: [
    { id: 11, contact_id: 2, value: '555-2222', label: 'work' },
  ],
  emails: [
    { id: 21, contact_id: 2, value: 'bob@example.com', label: 'work' },
  ],
  created_at: '2024-01-02T00:00:00Z',
  updated_at: '2024-01-02T00:00:00Z',
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ContactsSection', () => {
  describe('renders contact list', () => {
    it('renders name, role, phones, and emails for each linked contact', async () => {
      vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
        mockPrimaryContact,
        mockSecondaryContact,
      ])

      render(<ContactsSection propertyId={PROPERTY_ID} />)

      await waitFor(() => {
        // Names
        expect(screen.getByText('Alice Smith')).toBeInTheDocument()
        expect(screen.getByText('Bob Jones')).toBeInTheDocument()
      })

      // Roles (formatted as Title Case chips)
      expect(screen.getByText('Owner')).toBeInTheDocument()
      expect(screen.getByText('Property Manager')).toBeInTheDocument()

      // Phone numbers
      expect(screen.getByText(/555-1111/)).toBeInTheDocument()
      expect(screen.getByText(/555-2222/)).toBeInTheDocument()

      // Email addresses
      expect(screen.getByText(/alice@example\.com/)).toBeInTheDocument()
      expect(screen.getByText(/bob@example\.com/)).toBeInTheDocument()
    })
  })

  describe('primary contact badge', () => {
    it('renders a "Primary" badge only on the primary contact', async () => {
      vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
        mockPrimaryContact,
        mockSecondaryContact,
      ])

      render(<ContactsSection propertyId={PROPERTY_ID} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Smith')).toBeInTheDocument()
      })

      // Exactly one "Primary" chip
      const primaryBadges = screen.getAllByText('Primary')
      expect(primaryBadges).toHaveLength(1)

      // The "Set as Primary" button should only appear for the non-primary contact
      expect(screen.getByRole('button', { name: /set bob jones as primary/i })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /set alice smith as primary/i })).not.toBeInTheDocument()
    })
  })

  describe('"Set as Primary" button', () => {
    it('calls linkContactToProperty with is_primary: true when clicked', async () => {
      vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
        mockPrimaryContact,
        mockSecondaryContact,
      ])
      vi.mocked(contactService.linkContactToProperty).mockResolvedValue({
        ...mockSecondaryContact,
        is_primary: true,
      })

      render(<ContactsSection propertyId={PROPERTY_ID} />)

      await waitFor(() => {
        expect(screen.getByText('Bob Jones')).toBeInTheDocument()
      })

      const setPrimaryBtn = screen.getByRole('button', { name: /set bob jones as primary/i })
      fireEvent.click(setPrimaryBtn)

      await waitFor(() => {
        expect(contactService.linkContactToProperty).toHaveBeenCalledWith(
          PROPERTY_ID,
          {
            contact_id: mockSecondaryContact.id,
            role: mockSecondaryContact.property_contact_role,
            is_primary: true,
          }
        )
      })
    })
  })

  describe('"Remove" button', () => {
    it('calls unlinkContactFromProperty with correct IDs after confirming the dialog', async () => {
      vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
        mockPrimaryContact,
        mockSecondaryContact,
      ])
      vi.mocked(contactService.unlinkContactFromProperty).mockResolvedValue(undefined)

      render(<ContactsSection propertyId={PROPERTY_ID} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Smith')).toBeInTheDocument()
      })

      // Click the Remove button for the primary contact
      const removeBtn = screen.getByRole('button', { name: /remove alice smith/i })
      fireEvent.click(removeBtn)

      // Confirmation dialog should appear
      await waitFor(() => {
        expect(screen.getByText('Remove Contact')).toBeInTheDocument()
      })

      // Confirm the removal
      const confirmBtn = screen.getByRole('button', { name: /^remove$/i })
      fireEvent.click(confirmBtn)

      await waitFor(() => {
        expect(contactService.unlinkContactFromProperty).toHaveBeenCalledWith(
          PROPERTY_ID,
          mockPrimaryContact.id
        )
      })
    })

    it('does NOT call unlinkContactFromProperty when the dialog is cancelled', async () => {
      vi.mocked(contactService.getPropertyContacts).mockResolvedValue([mockPrimaryContact])

      render(<ContactsSection propertyId={PROPERTY_ID} />)

      await waitFor(() => {
        expect(screen.getByText('Alice Smith')).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: /remove alice smith/i }))

      await waitFor(() => {
        expect(screen.getByText('Remove Contact')).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: /cancel/i }))

      expect(contactService.unlinkContactFromProperty).not.toHaveBeenCalled()
    })
  })

  describe('"Add Contact" button', () => {
    it('opens ContactFormModal when clicked', async () => {
      vi.mocked(contactService.getPropertyContacts).mockResolvedValue([])

      render(<ContactsSection propertyId={PROPERTY_ID} />)

      // Modal should not be visible initially
      expect(screen.queryByTestId('contact-form-modal')).not.toBeInTheDocument()

      const addBtn = screen.getByRole('button', { name: /add contact/i })
      fireEvent.click(addBtn)

      await waitFor(() => {
        expect(screen.getByTestId('contact-form-modal')).toBeInTheDocument()
      })
    })
  })

  describe('API error handling', () => {
    it('surfaces a fetch error via an Alert when getPropertyContacts rejects', async () => {
      vi.mocked(contactService.getPropertyContacts).mockRejectedValue(
        new Error('Failed to load contacts')
      )

      render(<ContactsSection propertyId={PROPERTY_ID} />)

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
        expect(screen.getByText('Failed to load contacts')).toBeInTheDocument()
      })
    })
  })
})
