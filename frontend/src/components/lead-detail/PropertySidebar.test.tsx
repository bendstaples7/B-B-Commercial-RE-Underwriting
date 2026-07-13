import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import type { CommandCenterPayload } from '@/types'

vi.stubGlobal('navigator', {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
})

function makePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: 'Flat',
    owner_last_name: 'Owner',
    property_street: '123 Test St',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made',
    contacts: [
      {
        id: 10,
        first_name: 'Hilberto',
        last_name: 'Olivier',
        role: 'owner',
        is_primary: true,
        phones: [
          {
            id: 99,
            value: '(630) 202-3839',
            label: 'mobile',
            confidence_score: 80,
            notes: 'CONFIRMED',
          },
        ],
        emails: [],
      },
    ],
    phones: [{ value: '(630) 999-0000', confidence_score: 50 }],
    ...overrides,
  } as CommandCenterPayload
}

describe('PropertySidebar phone confidence', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows confidence chip from contacts[].phones when contacts exist', () => {
    render(<PropertySidebar commandCenterData={makePayload()} />)

    expect(screen.getByTestId('property-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Owner')
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Hilberto Olivier')
    expect(screen.getByTestId('phone-confidence-(630) 202-3839')).toHaveTextContent(
      '80% · CONFIRMED',
    )
    // Top-level phones[] must not be used when contacts exist
    expect(screen.queryByText('(630) 999-0000')).not.toBeInTheDocument()
  })

  it('labels flat owner name as Owner when contacts are empty', () => {
    render(
      <PropertySidebar
        commandCenterData={makePayload({
          contacts: [],
          owner_first_name: 'Joseph',
          owner_last_name: 'Kiferbaum',
        })}
      />,
    )

    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Owner')
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Joseph Kiferbaum')
  })

  it('prefers person Owner, shows Company org, and Also listed for address-like', () => {
    render(
      <PropertySidebar
        commandCenterData={makePayload({
          owner_first_name: 'Joseph',
          owner_last_name: 'Kiferbaum',
          owner_2_first_name: 'Kdg Avondale LLC',
          owner_2_last_name: null,
          organizations: [
            {
              id: 10,
              name: 'Kdg Avondale LLC',
              org_type: 'llc',
              role: 'owner',
              link_id: 1,
            },
          ],
          contacts: [
            {
              id: 1,
              first_name: '3508SACRAMENTO',
              last_name: 'MAYNARD',
              role: 'owner',
              is_primary: true,
              phones: [],
              emails: [],
            },
            {
              id: 2,
              first_name: 'Joseph',
              last_name: 'Kiferbaum',
              role: 'owner',
              is_primary: false,
              phones: [],
              emails: [],
            },
          ],
        })}
      />,
    )

    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Joseph Kiferbaum')
    expect(screen.getByTestId('sidebar-company-name')).toHaveTextContent('Kdg Avondale LLC')
    expect(screen.getByTestId('sidebar-also-listed-name')).toHaveTextContent(
      '3508SACRAMENTO MAYNARD',
    )
  })

  it('shows confidence from top-level phones[] when contacts are empty', () => {
    render(
      <PropertySidebar
        commandCenterData={makePayload({
          contacts: [],
          phones: [{ value: '(630) 430-5720', confidence_score: 90, notes: 'CONFIRMED' }],
        })}
      />,
    )

    expect(screen.getByTestId('phone-confidence-(630) 430-5720')).toHaveTextContent(
      '90% · CONFIRMED',
    )
  })
})
