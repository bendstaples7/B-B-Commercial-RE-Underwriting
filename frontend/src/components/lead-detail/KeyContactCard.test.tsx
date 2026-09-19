import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import {
  KeyContactCard,
  formatKeyContactMailing,
  resolveKeyContactChannels,
} from './KeyContactCard'
import { contactService } from '@/services/api'
import type { CommandCenterPayload } from '@/types'

vi.mock('@/services/api', () => ({
  contactService: {
    updateContact: vi.fn(),
    createContact: vi.fn(),
    linkContactToProperty: vi.fn(),
    searchContacts: vi.fn(),
    getContact: vi.fn(),
    clearOwnerPerson: vi.fn(),
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
})

function basePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 634,
    owner_first_name: 'Test',
    owner_last_name: 'Owner',
    property_street: '3046 N Hamlin Ave',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    ...overrides,
  }
}

function renderCard(data: CommandCenterPayload, name = 'Test Owner') {
  return render(
    <KeyContactCard name={name} commandCenterData={data} />,
  )
}

describe('resolveKeyContactChannels', () => {
  it('promotes phone-shaped email_1 to a phone channel (lead 634 class)', () => {
    const channels = resolveKeyContactChannels(
      basePayload({
        phone_1: '(312) 806-0441',
        email_1: '(708) 222-6620',
        email_2: 'ssuperman0018@yahoo.com',
      }),
    )
    expect(channels).toEqual([
      { kind: 'phone', phone: { value: '(312) 806-0441' } },
      { kind: 'phone', phone: { value: '(708) 222-6620' } },
      { kind: 'email', value: 'ssuperman0018@yahoo.com' },
    ])
  })

  it('carries the full LeadPhone DTO (confidence_score) instead of a stripped string', () => {
    const channels = resolveKeyContactChannels(
      basePayload({
        phones: [{ id: 1, value: '(312) 806-0441', confidence_score: 85, label: 'mobile' }],
      }),
    )
    expect(channels).toEqual([
      {
        kind: 'phone',
        phone: { id: 1, value: '(312) 806-0441', confidence_score: 85, label: 'mobile' },
      },
    ])
  })
})

describe('formatKeyContactMailing', () => {
  it('formats street + city/state/zip and does not fall back to property address', () => {
    expect(
      formatKeyContactMailing(
        basePayload({
          mailing_address: '100 Main St',
          mailing_city: 'Evanston',
          mailing_state: 'IL',
          mailing_zip: '60201',
        }),
      ),
    ).toBe('100 Main St\nEvanston, IL 60201')
    expect(formatKeyContactMailing(basePayload())).toBeNull()
  })
})

describe('KeyContactCard', () => {
  it('keeps the contact name subordinate to the Key Contact section title', () => {
    renderCard(
      basePayload({
        phone_1: '3128060441',
        contacts: [{
          id: 1,
          first_name: 'Gaston',
          last_name: 'Padilla',
          role: 'owner',
          is_primary: true,
          phones: [],
          emails: [],
        }],
      }),
      'Gaston Padilla',
    )
    expect(screen.getByRole('heading', { name: 'Key Contact' })).toBeInTheDocument()
    const name = screen.getByTestId('key-contact-name')
    expect(name).toHaveTextContent('Gaston Padilla')
    // Name uses body row title (0.95rem), not a larger hero size than the 1rem section title.
    expect(name).not.toHaveStyle({ fontSize: '1.05rem' })
  })

  it('grays out contact details when contacts_likely_prior_owner (post-sale untrusted)', () => {
    renderCard(
      basePayload({
        phone_1: '(312) 806-0441',
        email_1: 'old@example.com',
        mailing_address: '100 Main St',
        mailing_city: 'Chicago',
        mailing_state: 'IL',
        mailing_zip: '60614',
        contacts_likely_prior_owner: true,
        contacts_stale_since: '2024-07-30',
        contacts: [{
          id: 1,
          first_name: 'Prior',
          last_name: 'Owner',
          role: 'owner',
          is_primary: true,
          phones: [],
          emails: [],
        }],
      }),
      'Prior Owner',
    )
    expect(screen.getByTestId('key-contact-stale')).toBeInTheDocument()
    expect(screen.getByTestId('key-contact-likely-prior-owner')).toHaveTextContent(
      /Likely prior owner/i,
    )
    // Display-only — no tel/mailto while untrusted.
    expect(screen.getByTestId('key-contact-phone').tagName).toBe('P')
    expect(screen.getByTestId('key-contact-email').tagName).toBe('P')
  })

  it('uses phone icon/link for a phone misfiled as email', () => {
    renderCard(
      basePayload({
        phone_1: '(312) 806-0441',
        email_1: '(708) 222-6620',
        email_2: 'ssuperman0018@yahoo.com',
        contacts: [{
          id: 1,
          first_name: 'Sam',
          last_name: 'Superman',
          role: 'owner',
          is_primary: true,
          phones: [],
          emails: [],
        }],
      }),
    )
    expect(screen.getByTestId('key-contact-phone')).toHaveTextContent('(312) 806-0441')
    expect(screen.getByTestId('key-contact-phone-2')).toHaveTextContent('(708) 222-6620')
    expect(screen.getByTestId('key-contact-phone-2')).toHaveAttribute(
      'href',
      expect.stringContaining('tel:'),
    )
    expect(screen.getByTestId('key-contact-email')).toHaveTextContent('ssuperman0018@yahoo.com')
    expect(screen.queryByTestId('key-contact-email')).not.toHaveTextContent('708')
  })

  it('shows owner mailing address under phone/email', () => {
    renderCard(
      basePayload({
        mailing_address: '12709 Holbrook Dr',
        mailing_city: 'Orland Park',
        mailing_state: 'IL',
        mailing_zip: '60467',
      }),
    )
    expect(screen.getByTestId('key-contact-mailing')).toHaveTextContent('12709 Holbrook Dr')
    expect(screen.getByTestId('key-contact-mailing')).toHaveTextContent('Orland Park, IL 60467')
  })

  it('shows empty mailing copy when owner mailing is missing', () => {
    renderCard(basePayload({ mailing_address: null, mailing_city: null }))
    expect(screen.getByTestId('key-contact-mailing-empty')).toHaveTextContent(
      'No mailing address on file',
    )
  })

  it('shows a confidence chip and copy control for phones with a confidence_score', () => {
    renderCard(
      basePayload({
        phones: [{ id: 1, value: '(312) 806-0441', confidence_score: 85, label: 'mobile' }],
        contacts: [{
          id: 1,
          first_name: 'Sam',
          last_name: 'Owner',
          role: 'owner',
          is_primary: true,
          phones: [],
          emails: [],
        }],
      }),
    )
    expect(screen.getByTestId('key-contact-phone')).toHaveTextContent('(312) 806-0441')
    expect(screen.getByTestId('phone-confidence-(312) 806-0441')).toHaveTextContent('85%')
    expect(screen.getByLabelText('Copy phone')).toBeInTheDocument()
  })

  it('shows a copy control for email and mailing address', () => {
    renderCard(
      basePayload({
        email_1: 'owner@example.com',
        mailing_address: '12709 Holbrook Dr',
        mailing_city: 'Orland Park',
        mailing_state: 'IL',
        mailing_zip: '60467',
        contacts: [{
          id: 1,
          first_name: 'Sam',
          last_name: 'Owner',
          role: 'owner',
          is_primary: true,
          phones: [],
          emails: [],
        }],
      }),
    )
    expect(screen.getByTestId('key-contact-email-copy')).toBeInTheDocument()
    expect(screen.getByTestId('key-contact-mailing-copy')).toBeInTheDocument()
  })

  it('omits email/copy actions while contacts are likely prior owner but still shows mailing copy', () => {
    renderCard(
      basePayload({
        email_1: 'old@example.com',
        mailing_address: '100 Main St',
        mailing_city: 'Chicago',
        mailing_state: 'IL',
        mailing_zip: '60614',
        contacts_likely_prior_owner: true,
      }),
    )
    expect(screen.queryByTestId('key-contact-email-copy')).not.toBeInTheDocument()
    expect(screen.getByTestId('key-contact-mailing-copy')).toBeInTheDocument()
  })

  it('edits the primary person name from the pencil', async () => {
    vi.mocked(contactService.updateContact).mockResolvedValue({
      id: 88,
      first_name: 'Gilberto',
      last_name: 'Olivier',
    } as Awaited<ReturnType<typeof contactService.updateContact>>)

    renderCard(
      basePayload({
        contacts: [{
          id: 88,
          first_name: 'Hilberto',
          last_name: 'Olivier',
          role: 'owner',
          is_primary: true,
          phones: [],
          emails: [],
        }],
      }),
      'Hilberto Olivier',
    )

    fireEvent.click(screen.getByTestId('edit-key-contact-name-btn'))
    fireEvent.change(screen.getByTestId('key-contact-name-edit-input'), {
      target: { value: 'Gilberto Olivier' },
    })
    fireEvent.click(screen.getByLabelText('Save name'))

    await waitFor(() => {
      expect(contactService.updateContact).toHaveBeenCalledWith(88, {
        first_name: 'Gilberto',
        last_name: 'Olivier',
      })
    })
  })

  it('settles Key Contact with extra people and Add person (one title)', () => {
    renderCard(
      basePayload({
        contacts: [
          {
            id: 1,
            first_name: 'Yoko',
            last_name: 'Miller',
            role: 'owner',
            is_primary: true,
            phones: [],
            emails: [],
          },
          {
            id: 2,
            first_name: 'Yumi',
            last_name: 'Niece',
            role: 'owner',
            is_primary: false,
            phones: [
              { value: '3125550100', label: 'mobile' },
              { value: '7735550101', label: 'home' },
            ],
            emails: [],
          },
        ],
      }),
      'Yoko Miller',
    )
    const titles = screen.getAllByRole('heading', { name: 'Key Contact' })
    expect(titles).toHaveLength(1)
    expect(screen.getByTestId('key-contact-add-person-btn')).toBeInTheDocument()
    expect(screen.getByTestId('key-contact-other-2')).toHaveTextContent('Yumi Niece')
    expect(screen.getByTestId('key-contact-other-phone-2')).toHaveTextContent('(312) 555-0100')
    expect(screen.getByTestId('key-contact-other-phone-2-2')).toHaveTextContent('(773) 555-0101')
    // Other-people phones match People / primary Key Contact (left-aligned, dense=false)
    expect(screen.getByTestId('key-contact-other-phone-2').closest('div')).toHaveStyle({
      justifyContent: 'flex-start',
    })
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('opens the existing add-person form from Key Contact', () => {
    renderCard(basePayload({ contacts: [] }), 'Yoko Miller')
    fireEvent.click(screen.getByTestId('key-contact-add-person-btn'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getAllByText('Add Contact').length).toBeGreaterThan(0)
  })

  it('does not offer person edit details for an organization-only key contact', () => {
    renderCard(
      basePayload({
        owner_first_name: null,
        owner_last_name: null,
        contacts: [],
        organizations: [
          {
            id: 10,
            name: 'Kdg Avondale LLC',
            org_type: 'llc',
            role: 'owner',
            link_id: 1,
          },
        ],
      }),
      'Kdg Avondale LLC',
    )

    expect(screen.getByTestId('key-contact-name')).toHaveTextContent('Kdg Avondale LLC')
    expect(screen.queryByTestId('key-contact-edit-details-btn')).not.toBeInTheDocument()
  })

  it('does not treat a county name as the key contact', () => {
    renderCard(
      basePayload({
        owner_first_name: 'Gregory',
        owner_last_name: 'Shek',
        phone_1: '(312) 555-0199',
        contacts: [],
      }),
      'Gregory Shek',
    )
    expect(screen.getByTestId('key-contact-name')).toHaveTextContent('No contact on file')
    expect(screen.queryByTestId('key-contact-phone-edit')).not.toBeInTheDocument()
    expect(screen.queryByText('Gregory Shek')).not.toBeInTheDocument()
  })

  it('edits the phone on a linked key contact without opening a form', async () => {
    const user = userEvent.setup()
    vi.mocked(contactService.updateContact).mockResolvedValue({
      id: 88,
      first_name: 'Jane',
      last_name: 'Doe',
      role: 'owner',
      role_description: null,
      notes: null,
      phones: [{ id: 1, contact_id: 88, value: '600-0001', label: 'mobile' }],
      emails: [],
      created_at: null,
      updated_at: null,
    })

    renderCard(
      basePayload({
        contacts: [{
          id: 88,
          first_name: 'Jane',
          last_name: 'Doe',
          role: 'owner',
          is_primary: true,
          phones: [{ value: '(312) 555-0199', label: 'mobile' }],
          emails: [],
        }],
        phones: [{ value: '(312) 555-0199', label: 'mobile' }],
      }),
      'Jane Doe',
    )

    await user.click(screen.getByTestId('key-contact-phone-edit'))
    const input = screen.getByTestId('key-contact-phone-edit-input')
    expect(input).toHaveValue('(312) 555-0199')
    await user.clear(input)
    await user.type(input, '600-0001')
    await user.click(screen.getByLabelText('Save phone'))
    await waitFor(() => {
      expect(contactService.updateContact).toHaveBeenCalledWith(88, {
        phones: [{ value: '600-0001', label: 'mobile' }],
      })
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(contactService.getContact).not.toHaveBeenCalled()
  })

  it('shows an error when inline phone save fails', async () => {
    const user = userEvent.setup()
    vi.mocked(contactService.updateContact).mockRejectedValue(new Error('Could not update phone'))

    renderCard(
      basePayload({
        contacts: [{
          id: 88,
          first_name: 'Jane',
          last_name: 'Doe',
          role: 'owner',
          is_primary: true,
          phones: [{ value: '(312) 555-0199', label: 'mobile' }],
          emails: [],
        }],
        phones: [{ value: '(312) 555-0199', label: 'mobile' }],
      }),
      'Jane Doe',
    )

    await user.click(screen.getByTestId('key-contact-phone-edit'))
    await user.clear(screen.getByTestId('key-contact-phone-edit-input'))
    await user.type(screen.getByTestId('key-contact-phone-edit-input'), '600-0001')
    await user.click(screen.getByLabelText('Save phone'))

    expect(await screen.findByText('Could not update phone')).toBeInTheDocument()
    expect(screen.getByTestId('key-contact-phone-edit-input')).toBeInTheDocument()
  })

  it('clears a linked key contact from the lead', async () => {
    const user = userEvent.setup()
    vi.mocked(contactService.clearOwnerPerson).mockResolvedValue({
      display_name: 'Jane Doe',
    } as any)

    renderCard(
      basePayload({
        contacts: [{
          id: 88,
          first_name: 'Jane',
          last_name: 'Doe',
          role: 'owner',
          is_primary: true,
          phones: [{ value: '(312) 555-0199', label: 'mobile' }],
          emails: [],
        }],
      }),
      'Jane Doe',
    )

    await user.click(screen.getByTestId('key-contact-clear-owner-btn'))
    expect(screen.getByRole('dialog')).toHaveTextContent('Clear owner from lead?')
    await user.click(screen.getByTestId('confirm-key-contact-clear-owner-btn'))

    await waitFor(() => {
      expect(contactService.clearOwnerPerson).toHaveBeenCalledWith(634, {
        contact_id: 88,
        first_name: 'Jane',
        last_name: 'Doe',
        reason: 'cleared_from_key_contact',
      })
    })
    expect(await screen.findByText('Jane Doe cleared from this lead.')).toBeInTheDocument()
  })

  it('does not offer Clear from lead for a name that is not a saved person', () => {
    renderCard(
      basePayload({
        owner_first_name: 'Gary',
        owner_last_name: 'Carlson',
        contacts: [],
      }),
      'Gary Carlson',
    )
    expect(screen.getByTestId('key-contact-name')).toHaveTextContent('No contact on file')
    expect(screen.queryByTestId('key-contact-clear-owner-btn')).not.toBeInTheDocument()
  })
})
