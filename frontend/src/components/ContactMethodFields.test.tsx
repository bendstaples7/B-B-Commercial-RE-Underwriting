/**
 * Tests for ContactMethodFields component
 */
import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@/test/testUtils'
import { fireEvent, waitFor } from '@testing-library/react'
import {
  ContactMethodFields,
  EMPTY_CONTACT_METHOD,
  buildMethodOptions,
  contactMethodToCallPayload,
  contactMethodToEmailPayload,
  type ContactMethodValue,
} from './ContactMethodFields'
import type { PropertyContact } from '@/types'

const contacts: PropertyContact[] = [
  {
    id: 1,
    first_name: 'Jane',
    last_name: 'Doe',
    role: 'owner',
    role_description: null,
    notes: null,
    phones: [{ id: 10, contact_id: 1, value: '5551234567', label: 'mobile' }],
    emails: [{ id: 20, contact_id: 1, value: 'jane@work.com', label: 'work' }],
    created_at: null,
    updated_at: null,
    property_contact_role: 'owner',
    is_primary: true,
  },
  {
    id: 2,
    first_name: 'John',
    last_name: 'Smith',
    role: 'property_manager',
    role_description: null,
    notes: null,
    phones: [{ id: 11, contact_id: 2, value: '5559876543', label: 'work' }],
    emails: [],
    created_at: null,
    updated_at: null,
    property_contact_role: 'property_manager',
    is_primary: false,
  },
]

describe('ContactMethodFields', () => {
  it('filters phone methods to the selected contact', () => {
    const janeOnly = buildMethodOptions(contacts, 'phone', 1)
    expect(janeOnly).toHaveLength(1)
    expect(janeOnly[0].value).toBe('5551234567')

    const allPhones = buildMethodOptions(contacts, 'phone', null)
    expect(allPhones).toHaveLength(2)
  })

  it('maps call payload with contact and phone', () => {
    const payload = contactMethodToCallPayload({
      contactId: 1,
      methodKey: 'phone:10',
      methodValue: '5551234567',
      methodLabel: 'mobile',
      methodRecordId: 10,
    })
    expect(payload).toEqual({
      contact_id: 1,
      contact_phone_id: 10,
      phone_number: '5551234567',
      phone_label: 'mobile',
    })
  })

  it('maps email payload with contact and email', () => {
    const payload = contactMethodToEmailPayload({
      contactId: 1,
      methodKey: 'email:20',
      methodValue: 'jane@work.com',
      methodLabel: 'work',
      methodRecordId: 20,
    })
    expect(payload).toEqual({
      contact_id: 1,
      contact_email_id: 20,
      email_address: 'jane@work.com',
      email_label: 'work',
    })
  })

  it('invokes onChange when Other is selected', async () => {
    const onChange = vi.fn()
    render(
      <ContactMethodFields
        mode="phone"
        contacts={contacts}
        value={EMPTY_CONTACT_METHOD}
        onChange={onChange}
      />,
    )

    fireEvent.mouseDown(screen.getByRole('combobox', { name: /phone number/i }))
    const otherOption = await screen.findByRole('option', { name: 'Other…' })
    fireEvent.click(otherOption)

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ methodKey: 'other', methodValue: '' }),
    )
  })

  it('defaults to the highest-confidence phone across contacts', async () => {
    const onChange = vi.fn()
    const mixed: PropertyContact[] = [
      {
        ...contacts[0],
        phones: [
          {
            id: 10,
            contact_id: 1,
            value: '5551234567',
            label: 'other',
            confidence_score: 50,
          },
        ],
      },
      {
        ...contacts[1],
        phones: [
          {
            id: 11,
            contact_id: 2,
            value: '5559876543',
            label: 'other',
            notes: 'HubSpot primary',
            source: 'hubspot_import',
            confidence_score: 85,
          },
        ],
      },
    ]
    render(
      <ContactMethodFields
        mode="phone"
        contacts={mixed}
        value={EMPTY_CONTACT_METHOD}
        onChange={onChange}
      />,
    )

    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(onChange).toHaveBeenCalledWith({
      contactId: 2,
      methodKey: 'phone:11',
      methodValue: '5559876543',
      methodLabel: 'other',
      methodRecordId: 11,
    })
  })

  it('defaults to the primary contact + first email (emails) even with multiple contacts', async () => {
    const onChange = vi.fn()
    render(
      <ContactMethodFields
        mode="email"
        contacts={contacts}
        value={EMPTY_CONTACT_METHOD}
        onChange={onChange}
      />,
    )

    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(onChange).toHaveBeenCalledWith({
      contactId: 1,
      methodKey: 'email:20',
      methodValue: 'jane@work.com',
      methodLabel: 'work',
      methodRecordId: 20,
    })
  })

  it('picks highest-confidence phone when no contact is marked primary', async () => {
    const onChange = vi.fn()
    const noPrimary: PropertyContact[] = [
      {
        ...contacts[0],
        is_primary: false,
        phones: [
          {
            id: 10,
            contact_id: 1,
            value: '5551234567',
            label: 'other',
            confidence_score: 40,
          },
        ],
      },
      {
        ...contacts[1],
        is_primary: false,
        phones: [
          {
            id: 11,
            contact_id: 2,
            value: '5559876543',
            label: 'other',
            confidence_score: 70,
          },
        ],
      },
    ]
    render(
      <ContactMethodFields
        mode="phone"
        contacts={noPrimary}
        value={EMPTY_CONTACT_METHOD}
        onChange={onChange}
      />,
    )

    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(onChange).toHaveBeenCalledWith({
      contactId: 2,
      methodKey: 'phone:11',
      methodValue: '5559876543',
      methodLabel: 'other',
      methodRecordId: 11,
    })
  })

  it('selects the contact only when the primary contact has no method of that mode', async () => {
    const onChange = vi.fn()
    const primaryNoEmail: PropertyContact[] = [
      { ...contacts[0], emails: [] }, // Jane (primary) has no email
      { ...contacts[1], emails: [{ id: 30, contact_id: 2, value: 'john@work.com', label: 'work' }] },
    ]
    render(
      <ContactMethodFields
        mode="email"
        contacts={primaryNoEmail}
        value={EMPTY_CONTACT_METHOD}
        onChange={onChange}
      />,
    )

    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(onChange).toHaveBeenCalledWith({ ...EMPTY_CONTACT_METHOD, contactId: 1 })
  })

  it('allows clearing the contact to None after the default is applied', async () => {
    function Harness() {
      const [val, setVal] = useState<ContactMethodValue>(EMPTY_CONTACT_METHOD)
      return (
        <ContactMethodFields
          mode="phone"
          contacts={contacts}
          value={val}
          onChange={setVal}
        />
      )
    }
    render(<Harness />)

    const contactCombo = screen.getByRole('combobox', { name: /contact/i })
    await waitFor(() => expect(contactCombo).toHaveTextContent(/Jane Doe/i))

    fireEvent.mouseDown(contactCombo)
    const noneOption = await screen.findByRole('option', { name: '— None —' })
    fireEvent.click(noneOption)

    // Clearing to None empties the Select display (MUI renders no text for the
    // empty-string value), so the previously-defaulted contact is gone.
    await waitFor(() => expect(contactCombo).not.toHaveTextContent(/Jane Doe/i))
  })
})
