import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BuildingOwnershipSection } from '@/components/BuildingOwnershipSection'
import type { CommandCenterPayload } from '@/types'

vi.mock('@/services/api', () => ({
  buildingOwnershipService: {
    get: vi.fn(),
    analyze: vi.fn(),
    override: vi.fn(),
  },
}))

import { buildingOwnershipService } from '@/services/api'

function makePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 4860,
    owner_first_name: 'Joseph',
    owner_last_name: 'Kiferbaum',
    property_street: '3508 N Sacramento Ave',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 60,
    lead_status: 'mailing_no_contact_made',
    lead_category: 'commercial',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: {
      value: 'needs_manual_review',
      label: 'Needs Manual Review',
      explanation: 'review',
      signals: {},
    },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    units: 2,
    most_recent_sale_display: '01/15/2019',
    condo_risk_status: 'needs_review',
    condo_analysis_id: 9,
    ...overrides,
  }
}

function renderSection(payload: CommandCenterPayload = makePayload()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <BuildingOwnershipSection leadId={4860} commandCenterData={payload} />
    </QueryClientProvider>,
  )
}

describe('BuildingOwnershipSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows Condoized? control with confidence and units/sale', async () => {
    vi.mocked(buildingOwnershipService.get).mockResolvedValue({
      id: 9,
      lead_id: 4860,
      normalized_address: '3508 N SACRAMENTO AVE',
      condo_risk_status: 'needs_review',
      building_sale_possible: 'unknown',
      pin_count: 2,
      analyzed_at: '2026-07-10T15:30:00Z',
      analysis_details: {
        reason: 'Multiple PINs need review',
        confidence: 'medium',
        assessor_pins: [
          { pin: '1', property_class: '2-11', is_condo_class: false },
          { pin: '2', property_class: '2-11', is_condo_class: false },
        ],
      },
    })

    renderSection()

    expect(screen.getByTestId('building-ownership-section')).toBeInTheDocument()
    expect(screen.getByTestId('building-ownership-units')).toHaveTextContent('2 units')
    expect(screen.getByTestId('building-ownership-sale')).toHaveTextContent('01/15/2019')
    expect(screen.queryByText('Confirm Building Ownership')).not.toBeInTheDocument()
    expect(screen.queryByTestId('building-ownership-recommendation')).not.toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByTestId('building-ownership-pin-explanation')).toBeInTheDocument()
    })
    expect(screen.getByTestId('building-ownership-condoized-control')).toBeInTheDocument()
    expect(screen.getByTestId('building-ownership-condoized-unclear')).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByTestId('building-ownership-confidence')).toHaveTextContent(
      /medium confidence/i,
    )
    expect(screen.getByTestId('building-ownership-last-checked')).toHaveTextContent(
      /Last automated check/i,
    )
  })

  it('saves Yes/No via override API from Condoized? control', async () => {
    const user = userEvent.setup()
    vi.mocked(buildingOwnershipService.get).mockResolvedValue({
      id: 9,
      lead_id: 4860,
      normalized_address: '3508 N SACRAMENTO AVE',
      condo_risk_status: 'needs_review',
      building_sale_possible: 'unknown',
      pin_count: 2,
      analyzed_at: '2026-07-10T15:30:00Z',
      analysis_details: {
        reason: 'Multiple PINs need review',
        confidence: 'medium',
        assessor_pins: [{ pin: '1', property_class: '2-11', is_condo_class: false }],
      },
    })
    vi.mocked(buildingOwnershipService.override).mockResolvedValue({})

    renderSection()
    await waitFor(() => {
      expect(screen.getByTestId('building-ownership-condoized-no')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('building-ownership-condoized-no'))

    await waitFor(() => {
      expect(buildingOwnershipService.override).toHaveBeenCalledWith(4860, {
        condo_risk_status: 'likely_not_condo',
        building_sale_possible: 'yes',
        reason: 'Set from Condoized? control',
      })
    })
  })

  it('hides run-check CTA when ownership is already clear', async () => {
    vi.mocked(buildingOwnershipService.get).mockResolvedValue({
      id: 9,
      lead_id: 4860,
      normalized_address: '3508 N SACRAMENTO AVE',
      condo_risk_status: 'likely_not_condo',
      building_sale_possible: 'yes',
      pin_count: 1,
      analysis_details: {
        reason: 'Single PIN single owner',
        confidence: 'high',
        assessor_pins: [{ pin: '1', property_class: '2-11', is_condo_class: false }],
      },
    })

    renderSection(
      makePayload({
        condo_risk_status: 'likely_not_condo',
        building_sale_possible: 'yes',
      }),
    )

    await waitFor(() => {
      expect(screen.getByTestId('building-ownership-condoized-no')).toHaveAttribute(
        'aria-pressed',
        'true',
      )
    })
    expect(screen.queryByTestId('building-ownership-run-check')).not.toBeInTheDocument()
  })

  it('does not render for residential leads without ownership data', () => {
    renderSection(
      makePayload({
        lead_category: 'residential',
        condo_risk_status: null,
        condo_analysis_id: null,
        building_sale_possible: null,
      }),
    )
    expect(screen.queryByTestId('building-ownership-section')).not.toBeInTheDocument()
  })
})
