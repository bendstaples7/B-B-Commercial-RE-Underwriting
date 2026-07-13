import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BuildingOwnershipReviewDrawer } from '@/components/BuildingOwnershipReviewDrawer'
import type { CommandCenterPayload } from '@/types'

vi.mock('@/services/api', () => ({
  buildingOwnershipService: {
    get: vi.fn(),
    analyze: vi.fn(),
    override: vi.fn(),
  },
  leadTaskService: {
    createTask: vi.fn(),
  },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {
    enqueue: vi.fn(),
  },
}))

import { buildingOwnershipService } from '@/services/api'

function makePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 42,
    owner_first_name: 'Joseph',
    owner_last_name: 'Kifferbaum',
    property_street: '3508 S Sacramento Ave',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 60,
    lead_status: 'mailing_no_contact_made',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: {
      value: 'needs_manual_review',
      label: 'Needs Manual Review',
      explanation: 'Condo risk requires review',
      signals: {},
    },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    units: 2,
    mailing_address: '100 Mail St',
    mailing_city: 'Chicago',
    mailing_state: 'IL',
    mailing_zip: '60601',
    condo_risk_status: 'needs_review',
    ...overrides,
  }
}

function renderDrawer(payload: CommandCenterPayload = makePayload()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <BuildingOwnershipReviewDrawer
        leadId={42}
        commandCenterData={payload}
        open
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

describe('BuildingOwnershipReviewDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows imported units from command center', () => {
    renderDrawer()
    expect(screen.getByTestId('ownership-imported-units')).toHaveTextContent('From import: 2 units')
  })

  it('shows feedback when analyze is skipped as current', async () => {
    vi.mocked(buildingOwnershipService.analyze).mockResolvedValue({
      lead_id: 42,
      condo_analysis_id: 9,
      condo_risk_status: 'needs_review',
      building_sale_possible: 'unknown',
      skipped: true,
      skip_reason: 'analysis_current',
      analysis_details: {
        reason: 'Needs review',
        confidence: 'low',
        assessor_pins: [
          { pin: '1', property_class: '2-11', is_condo_class: false },
          { pin: '2', property_class: '2-11', is_condo_class: false },
        ],
      },
    })
    vi.mocked(buildingOwnershipService.get).mockResolvedValue({
      id: 9,
      lead_id: 42,
      normalized_address: '3508 S SACRAMENTO AVE',
      condo_risk_status: 'needs_review',
      building_sale_possible: 'unknown',
      pin_count: 2,
      analysis_details: {
        reason: 'Needs review',
        assessor_pins: [
          { pin: '1', property_class: '2-11', is_condo_class: false },
          { pin: '2', property_class: '2-11', is_condo_class: false },
        ],
      },
    })

    const user = userEvent.setup()
    renderDrawer(makePayload({ condo_analysis_id: 9 }))

    await user.click(screen.getByTestId('run-building-ownership-check'))

    await waitFor(() => {
      expect(screen.getByTestId('building-ownership-analyze-feedback')).toHaveTextContent(
        /Already analyzed/,
      )
    })
    expect(screen.getByTestId('pin-explanation')).toBeInTheDocument()
    expect(screen.getByTestId('confirm-building-ownership')).toHaveTextContent(
      'Save ownership decision',
    )
  })

  it('shows mail queue CTA when likely_not_condo and mailing address present', () => {
    vi.mocked(buildingOwnershipService.get).mockRejectedValue(new Error('not loaded'))
    renderDrawer(
      makePayload({
        condo_risk_status: 'likely_not_condo',
        building_sale_possible: 'yes',
        condo_analysis_id: 1,
      }),
    )
    expect(screen.getByTestId('ownership-add-to-mail-queue')).toBeInTheDocument()
  })
})
