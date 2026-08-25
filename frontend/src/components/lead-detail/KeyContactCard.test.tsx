import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@/test/testUtils'
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
  },
}))

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
    renderCard(basePayload({ phone_1: '3128060441' }), 'Gaston Padilla')
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
})
