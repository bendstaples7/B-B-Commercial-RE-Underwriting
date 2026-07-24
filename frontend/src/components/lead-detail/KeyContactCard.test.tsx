import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThemeProvider, createTheme } from '@mui/material'
import {
  KeyContactCard,
  formatKeyContactMailing,
  resolveKeyContactChannels,
} from './KeyContactCard'
import type { CommandCenterPayload } from '@/types'

const theme = createTheme()

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
    <ThemeProvider theme={theme}>
      <KeyContactCard name={name} commandCenterData={data} />
    </ThemeProvider>,
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
      { kind: 'phone', value: '(312) 806-0441' },
      { kind: 'phone', value: '(708) 222-6620' },
      { kind: 'email', value: 'ssuperman0018@yahoo.com' },
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
    ).toBe('100 Main St\nEvanston, IL, 60201')
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
    expect(screen.getByTestId('key-contact-mailing')).toHaveTextContent('Orland Park, IL, 60467')
  })

  it('shows empty mailing copy when owner mailing is missing', () => {
    renderCard(basePayload({ mailing_address: null, mailing_city: null }))
    expect(screen.getByTestId('key-contact-mailing-empty')).toHaveTextContent(
      'No mailing address on file',
    )
  })
})
