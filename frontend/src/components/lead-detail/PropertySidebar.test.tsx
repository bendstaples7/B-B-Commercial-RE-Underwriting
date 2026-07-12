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
    expect(screen.getByText('Hilberto Olivier')).toBeInTheDocument()
    expect(screen.getByTestId('phone-confidence-(630) 202-3839')).toHaveTextContent(
      '80% · CONFIRMED',
    )
    // Top-level phones[] must not be used when contacts exist
    expect(screen.queryByText('(630) 999-0000')).not.toBeInTheDocument()
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
