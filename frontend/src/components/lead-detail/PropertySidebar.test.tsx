import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import type { CommandCenterPayload } from '@/types'

vi.stubGlobal('navigator', {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
})

function renderSidebar(payload: CommandCenterPayload) {
  return render(
    <MemoryRouter>
      <PropertySidebar commandCenterData={payload} />
    </MemoryRouter>,
  )
}

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
    renderSidebar(makePayload())

    expect(screen.getByTestId('property-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Owner')
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Hilberto Olivier')
    expect(screen.getByTestId('sidebar-phones')).toBeInTheDocument()
    expect(screen.getByTestId('phone-confidence-(630) 202-3839')).toHaveTextContent(
      '80% · CONFIRMED',
    )
    // Top-level phones[] must not be used when contacts exist
    expect(screen.queryByText('(630) 999-0000')).not.toBeInTheDocument()
  })

  it('lists multiple phones under a single Phone label', () => {
    renderSidebar(
      makePayload({
        contacts: [
          {
            id: 10,
            first_name: 'Bob',
            last_name: 'Weinstein',
            role: 'owner',
            is_primary: true,
            phones: [
              { id: 1, value: '(847) 707-9193', confidence_score: 90, notes: 'CONFIRMED' },
              { id: 2, value: '(206) 504-9119', confidence_score: 50 },
              { id: 3, value: '(206) 719-9119', confidence_score: 50 },
            ],
            emails: [],
          },
        ],
      }),
    )

    const phonesBlock = screen.getByTestId('sidebar-phones')
    expect(phonesBlock).toHaveTextContent('Phone')
    expect(phonesBlock.querySelectorAll('[data-testid^="phone-confidence-"]')).toHaveLength(3)
    // Label appears once for the group, not once per number
    expect(phonesBlock.textContent?.match(/\bPhone\b/g)).toHaveLength(1)
  })

  it('labels flat owner name as Owner when contacts are empty', () => {
    renderSidebar(
      makePayload({
        contacts: [],
        owner_first_name: 'Joseph',
        owner_last_name: 'Kiferbaum',
      }),
    )

    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Owner')
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Joseph Kiferbaum')
  })

  it('prefers person Owner, shows Company org, and Also listed for address-like', () => {
    renderSidebar(
      makePayload({
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
      }),
    )

    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Joseph Kiferbaum')
    expect(screen.getByTestId('sidebar-company-name')).toHaveTextContent('Kdg Avondale LLC')
    expect(screen.getByTestId('sidebar-also-listed-name')).toHaveTextContent(
      '3508SACRAMENTO MAYNARD',
    )
  })

  it('shows confidence from top-level phones[] when contacts are empty', () => {
    renderSidebar(
      makePayload({
        contacts: [],
        phones: [{ value: '(630) 430-5720', confidence_score: 90, notes: 'CONFIRMED' }],
      }),
    )

    expect(screen.getByTestId('phone-confidence-(630) 430-5720')).toHaveTextContent(
      '90% · CONFIRMED',
    )
  })

  it('shows work queue chips and data quality breakdown', () => {
    renderSidebar(
      makePayload({
        work_queues: [
          { key: 'previously-warm', label: 'Previously Warm', path: '/queues/previously-warm' },
          { key: 'follow-up-overdue', label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue' },
        ],
        data_completeness_score: 72.5,
        data_quality_breakdown: {
          total: 72.5,
          property: 40,
          contact: 32.5,
          best_phone_confidence: 90,
          has_email: true,
          missing: ['pin', 'units'],
        },
      }),
    )

    expect(screen.getByTestId('work-queue-previously-warm')).toHaveTextContent('Previously Warm')
    expect(screen.getByTestId('work-queue-follow-up-overdue')).toHaveTextContent('Follow-Up Overdue')
    expect(screen.getByText('73%')).toBeInTheDocument()
    expect(screen.getByText('90%')).toBeInTheDocument()
    expect(screen.getByTestId('data-quality-missing')).toBeInTheDocument()
  })

  it('shows empty work queue state', () => {
    renderSidebar(makePayload({ work_queues: [] }))
    expect(screen.getByTestId('work-queues-empty')).toHaveTextContent(
      'Not in an active work queue.',
    )
  })
})
