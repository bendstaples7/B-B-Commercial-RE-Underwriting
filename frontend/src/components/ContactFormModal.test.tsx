/**
 * Tests for ContactFormModal component
 *
 * Covers:
 * - Renders in create mode when no `contact` prop is provided
 * - Renders in edit mode with pre-filled fields when `contact` prop is provided
 * - Submitting with both first name and last name empty shows inline validation error and does not call API
 * - Submitting with only first name filled succeeds (no validation error)
 * - Role description field is hidden when role is not 'other'; shown when role is 'other'
 * - "Add phone" button adds a new phone row; remove button removes it
 * - "Add email" button adds a new email row; remove button removes it
 * - Successful create submission calls `createContact` then `linkContactToProperty` and closes modal
 * - Successful edit submission calls `updateContact` and closes modal
 * - API error is surfaced via Snackbar
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import { ContactFormModal } from './ContactFormModal'
import { contactService } from '@/services/api'
import type { PropertyContact } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  contactService: {
    createContact: vi.fn(),
    updateContact: vi.fn(),
    linkContactToProperty: vi.fn(),
    getPropertyContacts: vi.fn(),
    unlinkContactFromProperty: vi.fn(),
    deleteContact: vi.fn(),
    getContact: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const PROPERTY_ID = 42
const ON_CLOSE = vi.fn()

const mockContact: PropertyContact = {
  id: 7,
  first_name: 'Jane',
  last_name: 'Doe',
  role: 'property_manager',
  role_description: null,
  notes: 'Some notes',
  property_contact_role: 'property_manager',
  is_primary: false,
  phones: [
    { id: 10, contact_id: 7, value: '555-9999', label: 'mobile' },
  ],
  emails: [
    { id: 20, contact_id: 7, value: 'jane@example.com', label: 'personal' },
  ],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderCreateModal() {
  return render(
    <ContactFormModal
      open={true}
      onClose={ON_CLOSE}
      propertyId={PROPERTY_ID}
    />
  )
}

function renderEditModal(contact: PropertyContact = mockContact) {
  return render(
    <ContactFormModal
      open={true}
      onClose={ON_CLOSE}
      propertyId={PROPERTY_ID}
      contact={contact}
    />
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ContactFormModal', () => {
  describe('create mode', () => {
    it('renders "Add Contact" title and submit button when no contact prop is provided', () => {
      renderCreateModal()

      // Both the dialog title and the submit button contain "Add Contact"
      const addContactElements = screen.getAllByText('Add Contact')
      expect(addContactElements.length).toBeGreaterThanOrEqual(1)
      // The submit button specifically
      expect(screen.getByRole('button', { name: /add contact/i })).toBeInTheDocument()
    })

    it('renders empty first name and last name fields', () => {
      renderCreateModal()

      const firstNameInput = screen.getByRole('textbox', { name: /first name/i })
      const lastNameInput = screen.getByRole('textbox', { name: /last name/i })

      expect(firstNameInput).toHaveValue('')
      expect(lastNameInput).toHaveValue('')
    })
  })

  describe('edit mode', () => {
    it('renders "Edit Contact" title and "Save Changes" button when contact prop is provided', () => {
      renderEditModal()

      expect(screen.getByText('Edit Contact')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
    })

    it('pre-fills first name and last name from the contact prop', () => {
      renderEditModal()

      expect(screen.getByRole('textbox', { name: /first name/i })).toHaveValue('Jane')
      expect(screen.getByRole('textbox', { name: /last name/i })).toHaveValue('Doe')
    })

    it('pre-fills notes from the contact prop', () => {
      renderEditModal()

      expect(screen.getByRole('textbox', { name: /notes/i })).toHaveValue('Some notes')
    })

    it('pre-fills phone numbers from the contact prop', () => {
      renderEditModal()

      expect(screen.getByDisplayValue('555-9999')).toBeInTheDocument()
    })

    it('pre-fills email addresses from the contact prop', () => {
      renderEditModal()

      expect(screen.getByDisplayValue('jane@example.com')).toBeInTheDocument()
    })
  })

  describe('validation', () => {
    it('shows inline error and does not call API when both first and last name are empty', async () => {
      renderCreateModal()

      // Both fields are empty by default — click submit
      fireEvent.click(screen.getByRole('button', { name: /add contact/i }))

      await waitFor(() => {
        expect(
          screen.getByText(/at least one of first name or last name is required/i)
        ).toBeInTheDocument()
      })

      expect(contactService.createContact).not.toHaveBeenCalled()
      expect(contactService.linkContactToProperty).not.toHaveBeenCalled()
    })

    it('does not show validation error when only first name is filled', async () => {
      vi.mocked(contactService.createContact).mockResolvedValue({
        id: 99,
        first_name: 'Alice',
        last_name: null,
        role: 'owner',
        role_description: null,
        notes: null,
        phones: [],
        emails: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      })
      vi.mocked(contactService.linkContactToProperty).mockResolvedValue({
        ...mockContact,
        id: 99,
        first_name: 'Alice',
        last_name: null,
      })

      renderCreateModal()

      fireEvent.change(screen.getByRole('textbox', { name: /first name/i }), {
        target: { value: 'Alice' },
      })

      fireEvent.click(screen.getByRole('button', { name: /add contact/i }))

      await waitFor(() => {
        expect(
          screen.queryByText(/at least one of first name or last name is required/i)
        ).not.toBeInTheDocument()
      })

      expect(contactService.createContact).toHaveBeenCalled()
    })
  })

  describe('role description field', () => {
    it('is hidden when role is not "other"', () => {
      renderCreateModal()

      // Default role is 'owner', so role description should not be visible
      expect(screen.queryByRole('textbox', { name: /role description/i })).not.toBeInTheDocument()
    })

    it('is shown when role is changed to "other"', async () => {
      renderCreateModal()

      // MUI Select — click to open, then click the "Other" option
      const roleSelect = screen.getByRole('combobox', { name: /role/i })
      fireEvent.mouseDown(roleSelect)

      await waitFor(() => {
        expect(screen.getByRole('option', { name: /^other$/i })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('option', { name: /^other$/i }))

      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: /role description/i })).toBeInTheDocument()
      })
    })
  })

  describe('phone rows', () => {
    it('"Add phone" button adds a new phone row', async () => {
      renderCreateModal()

      // No phone rows initially
      expect(screen.queryByRole('textbox', { name: /phone number 1/i })).not.toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: /add phone number/i }))

      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: /phone number 1/i })).toBeInTheDocument()
      })
    })

    it('remove button removes the phone row', async () => {
      renderCreateModal()

      fireEvent.click(screen.getByRole('button', { name: /add phone number/i }))

      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: /phone number 1/i })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: /remove phone number 1/i }))

      await waitFor(() => {
        expect(screen.queryByRole('textbox', { name: /phone number 1/i })).not.toBeInTheDocument()
      })
    })
  })

  describe('email rows', () => {
    it('"Add email" button adds a new email row', async () => {
      renderCreateModal()

      // No email rows initially
      expect(screen.queryByRole('textbox', { name: /email address 1/i })).not.toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: /add email address/i }))

      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: /email address 1/i })).toBeInTheDocument()
      })
    })

    it('remove button removes the email row', async () => {
      renderCreateModal()

      fireEvent.click(screen.getByRole('button', { name: /add email address/i }))

      await waitFor(() => {
        expect(screen.getByRole('textbox', { name: /email address 1/i })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: /remove email address 1/i }))

      await waitFor(() => {
        expect(screen.queryByRole('textbox', { name: /email address 1/i })).not.toBeInTheDocument()
      })
    })
  })

  describe('successful create submission', () => {
    it('calls createContact then linkContactToProperty and closes modal', async () => {
      const createdContact = {
        id: 55,
        first_name: 'Bob',
        last_name: null,
        role: 'owner' as const,
        role_description: null,
        notes: null,
        phones: [],
        emails: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      }

      vi.mocked(contactService.createContact).mockResolvedValue(createdContact)
      vi.mocked(contactService.linkContactToProperty).mockResolvedValue({
        ...mockContact,
        id: 55,
        first_name: 'Bob',
        last_name: null,
      })

      renderCreateModal()

      fireEvent.change(screen.getByRole('textbox', { name: /first name/i }), {
        target: { value: 'Bob' },
      })

      fireEvent.click(screen.getByRole('button', { name: /add contact/i }))

      await waitFor(() => {
        expect(contactService.createContact).toHaveBeenCalledWith(
          expect.objectContaining({ first_name: 'Bob' })
        )
      })

      await waitFor(() => {
        expect(contactService.linkContactToProperty).toHaveBeenCalledWith(
          PROPERTY_ID,
          expect.objectContaining({ contact_id: 55 })
        )
      })

      await waitFor(() => {
        expect(ON_CLOSE).toHaveBeenCalled()
      })
    })
  })

  describe('successful edit submission', () => {
    it('calls updateContact and closes modal', async () => {
      vi.mocked(contactService.updateContact).mockResolvedValue({
        ...mockContact,
        first_name: 'Jane',
        last_name: 'Updated',
      })

      renderEditModal()

      fireEvent.change(screen.getByRole('textbox', { name: /last name/i }), {
        target: { value: 'Updated' },
      })

      fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

      await waitFor(() => {
        expect(contactService.updateContact).toHaveBeenCalledWith(
          mockContact.id,
          expect.objectContaining({ last_name: 'Updated' })
        )
      })

      expect(contactService.createContact).not.toHaveBeenCalled()
      expect(contactService.linkContactToProperty).not.toHaveBeenCalled()

      await waitFor(() => {
        expect(ON_CLOSE).toHaveBeenCalled()
      })
    })
  })

  describe('API error handling', () => {
    it('surfaces a createContact error via Snackbar Alert', async () => {
      vi.mocked(contactService.createContact).mockRejectedValue(
        new Error('Network error')
      )

      renderCreateModal()

      fireEvent.change(screen.getByRole('textbox', { name: /first name/i }), {
        target: { value: 'ErrorTest' },
      })

      fireEvent.click(screen.getByRole('button', { name: /add contact/i }))

      await waitFor(() => {
        // MUI Snackbar renders in a portal that may be inside aria-hidden; use hidden:true
        const alerts = screen.getAllByRole('alert', { hidden: true })
        expect(alerts.length).toBeGreaterThan(0)
        expect(screen.getByText('Network error')).toBeInTheDocument()
      })

      // Modal should NOT close on error
      expect(ON_CLOSE).not.toHaveBeenCalled()
    })
  })
})
