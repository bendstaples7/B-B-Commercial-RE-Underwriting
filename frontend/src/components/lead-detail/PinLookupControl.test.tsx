import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MissingPinActions } from '@/components/lead-detail/PinLookupControl'
import { leadTaskService } from '@/services/api'
import { buildingOwnershipService, propertyMatchService } from '@/services/propertyMatchApi'

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    leadTaskService: {
      ...actual.leadTaskService,
      createTask: vi.fn(),
    },
    commandCenterService: {
      ...actual.commandCenterService,
      updateStatus: vi.fn(),
    },
  }
})

vi.mock('@/services/propertyMatchApi', () => ({
  propertyMatchService: {
    preview: vi.fn(),
    approve: vi.fn(),
  },
  buildingOwnershipService: {
    analyze: vi.fn().mockResolvedValue({}),
  },
}))

function renderPinLookup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const onSnack = vi.fn()
  render(
    <QueryClientProvider client={queryClient}>
      <MissingPinActions
        leadId={1}
        currentPin={null}
        onSnack={onSnack}
        testIdPrefix="pin"
        align="start"
      />
    </QueryClientProvider>,
  )
  return { onSnack }
}

describe('MissingPinActions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('replaces Look up PIN with Verify when Enter PIN is chosen', () => {
    renderPinLookup()
    expect(screen.getByTestId('pin-look-up-pin')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('pin-enter-pin'))
    expect(screen.queryByTestId('pin-look-up-pin')).not.toBeInTheDocument()
    expect(screen.getByTestId('pin-verify-pin')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('pin-cancel-pin-entry'))
    expect(screen.getByTestId('pin-look-up-pin')).toBeInTheDocument()
  })

  it('queues research when no match', async () => {
    vi.mocked(propertyMatchService.preview).mockResolvedValue({
      found: false,
      entered_address: {
        property_street: '123 Test St',
        property_city: 'Chicago',
        property_state: 'IL',
        property_zip: '60601',
      },
      recommended_address: null,
      pin: null,
      connector: 'cook_county',
      address_complete: true,
      reason: 'no_match',
      message: 'No assessor match found',
    })
    vi.mocked(leadTaskService.createTask).mockResolvedValue({} as never)

    renderPinLookup()
    fireEvent.click(screen.getByTestId('pin-look-up-pin'))

    await waitFor(() => {
      expect(propertyMatchService.preview).toHaveBeenCalled()
      expect(leadTaskService.createTask).toHaveBeenCalledWith(1, {
        title: 'Research missing PIN',
        task_type: 'research_missing_pin',
      })
    })
    expect(screen.queryByTestId('pin-verify-pin')).not.toBeInTheDocument()
  })

  it('auto-applies a single unambiguous PIN', async () => {
    vi.mocked(propertyMatchService.preview).mockResolvedValue({
      found: true,
      entered_address: {
        property_street: '123 Test St',
        property_city: 'Chicago',
        property_state: 'IL',
        property_zip: '60601',
      },
      recommended_address: {
        property_street: '123 Test St',
        property_city: 'Chicago',
        property_state: 'IL',
        property_zip: '60601',
        county_assessor_pin: '14211234560000',
      },
      pin: '14211234560000',
      pin_count: 1,
      connector: 'cook_county',
    })
    vi.mocked(propertyMatchService.approve).mockResolvedValue({
      lead_id: 1,
      has_property_match: true,
      county_assessor_pin: '14-21-123-456-0000',
      recommended_action: 'call_ready',
      removed_from_queue: true,
    })

    renderPinLookup()
    fireEvent.click(screen.getByTestId('pin-look-up-pin'))
    await waitFor(() => {
      expect(propertyMatchService.approve).toHaveBeenCalledWith(1, {
        pin: '14-21-123-456-0000',
      })
    })
  })

  it('analyzes multi-PIN tax situs without persisting AKA on quiet path is not used here', async () => {
    vi.mocked(propertyMatchService.preview).mockResolvedValue({
      found: true,
      entered_address: {
        property_street: '3715 N Leavitt',
        property_city: 'Chicago',
        property_state: 'IL',
        property_zip: '60618',
      },
      recommended_address: null,
      pin: '14191220010000',
      pins: ['14191220010000', '14191220020000'],
      pin_count: 2,
      candidates: [
        { pin: '14-19-122-001-0000', property_street: '2155 W Bradley Pl' },
        { pin: '14-19-122-002-0000', property_street: '2155 W Bradley Pl' },
      ],
      tax_situs_street: '2155 W Bradley Pl',
      tax_situs_pin_count: 2,
      require_explicit_apply: true,
      connector: 'cook_county',
    })

    renderPinLookup()
    fireEvent.click(screen.getByTestId('pin-look-up-pin'))
    await waitFor(() => {
      expect(buildingOwnershipService.analyze).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          force: true,
          persist_aka: true,
          tax_situs_street: '2155 W Bradley Pl',
        }),
      )
    })
  })
})
