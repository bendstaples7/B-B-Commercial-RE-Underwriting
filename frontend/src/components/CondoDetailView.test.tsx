import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { CondoDetailView } from './CondoDetailView'
import { condoFilterService } from '@/services/condoFilterApi'
import type { AddressGroupDetail } from '@/types'

vi.mock('@/services/condoFilterApi', () => ({
  condoFilterService: {
    runAnalysis: vi.fn(),
    getResults: vi.fn(),
    getDetail: vi.fn(),
    applyOverride: vi.fn(),
    exportCsv: vi.fn(),
  },
}))

const mockDetail: AddressGroupDetail = {
  id: 1,
  normalized_address: '456 oak ave',
  source_type: 'commercial',
  property_count: 2,
  pin_count: 2,
  owner_count: 1,
  has_unit_number: false,
  has_condo_language: false,
  missing_pin_count: 0,
  missing_owner_count: 0,
  condo_risk_status: 'partial_condo_possible',
  building_sale_possible: 'maybe',
  analysis_details: {
    triggered_rules: ['rule_5_multiple_pins_single_owner'],
    reason: 'Multiple PINs with single owner',
    confidence: 'medium',
  },
  manually_reviewed: false,
  manual_override_status: null,
  manual_override_reason: null,
  analyzed_at: '2024-01-15T10:00:00Z',
  created_at: '2024-01-15T10:00:00Z',
  updated_at: '2024-01-15T10:00:00Z',
  leads: [
    {
      id: 10,
      property_street: '456 Oak Ave Unit A',
      county_assessor_pin: '12-34-567-001',
      owner_first_name: 'John',
      owner_last_name: 'Smith',
      owner_2_first_name: null,
      owner_2_last_name: null,
      property_type: 'commercial',
      assessor_class: 'C1',
    },
    {
      id: 11,
      property_street: '456 Oak Ave Unit B',
      county_assessor_pin: '12-34-567-002',
      owner_first_name: 'John',
      owner_last_name: 'Smith',
      owner_2_first_name: 'Jane',
      owner_2_last_name: 'Smith',
      property_type: 'commercial',
      assessor_class: 'C1',
    },
  ],
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

describe('CondoDetailView', () => {
  let onClose: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    onClose = vi.fn()
    vi.mocked(condoFilterService.getDetail).mockResolvedValue(mockDetail)
  })

  it('renders linked leads table when open', async () => {
    render(
      <CondoDetailView analysisId={1} open={true} onClose={onClose} />,
    )

    await waitFor(() => {
      expect(screen.getByText('456 oak ave')).toBeInTheDocument()
    })

    // Check linked leads are displayed
    expect(screen.getByText('456 Oak Ave Unit A')).toBeInTheDocument()
    expect(screen.getByText('456 Oak Ave Unit B')).toBeInTheDocument()
    expect(screen.getByText('12-34-567-001')).toBeInTheDocument()
    expect(screen.getByText('12-34-567-002')).toBeInTheDocument()
    expect(screen.getByText('Linked Properties (2)')).toBeInTheDocument()
  })

  it('renders analysis details', async () => {
    render(
      <CondoDetailView analysisId={1} open={true} onClose={onClose} />,
    )

    await waitFor(() => {
      expect(screen.getByText('456 oak ave')).toBeInTheDocument()
    })

    expect(screen.getByText('Multiple PINs with single owner')).toBeInTheDocument()
    expect(screen.getByText('medium')).toBeInTheDocument()
    expect(screen.getByText('rule_5_multiple_pins_single_owner')).toBeInTheDocument()
  })

  it('does not fetch when closed', () => {
    render(
      <CondoDetailView analysisId={1} open={false} onClose={onClose} />,
    )

    expect(condoFilterService.getDetail).not.toHaveBeenCalled()
  })

  it('does not fetch when analysisId is null', () => {
    render(
      <CondoDetailView analysisId={null} open={true} onClose={onClose} />,
    )

    expect(condoFilterService.getDetail).not.toHaveBeenCalled()
  })

  it('override form submits correctly', async () => {
    const updatedDetail: AddressGroupDetail = {
      ...mockDetail,
      condo_risk_status: 'likely_not_condo',
      building_sale_possible: 'yes',
      manually_reviewed: true,
      manual_override_status: 'likely_not_condo',
      manual_override_reason: 'Verified single owner building',
    }
    vi.mocked(condoFilterService.applyOverride).mockResolvedValue(updatedDetail)

    render(
      <CondoDetailView analysisId={1} open={true} onClose={onClose} />,
    )

    await waitFor(() => {
      expect(screen.getByText('456 oak ave')).toBeInTheDocument()
    })

    // Fill in the override form
    // Select Condo Risk Status - "Likely Not Condo"
    const statusSelect = screen.getByLabelText('Condo Risk Status')
    fireEvent.mouseDown(statusSelect)
    const statusListbox = screen.getByRole('listbox')
    fireEvent.click(statusListbox.querySelector('[data-value="likely_not_condo"]')!)

    // Select Building Sale Possible - "Yes"
    const buildingSaleSelect = screen.getByLabelText('Building Sale Possible')
    fireEvent.mouseDown(buildingSaleSelect)
    const buildingSaleListbox = screen.getByRole('listbox')
    fireEvent.click(buildingSaleListbox.querySelector('[data-value="yes"]')!)

    // Fill in reason
    const reasonField = screen.getByLabelText(/reason/i)
    await user.clear(reasonField)
    await user.type(reasonField, 'Verified single owner building')

    // Submit the form
    const submitButton = screen.getByRole('button', { name: /apply override/i })
    await user.click(submitButton)

    await waitFor(() => {
      expect(condoFilterService.applyOverride).toHaveBeenCalledWith(1, {
        condo_risk_status: 'likely_not_condo',
        building_sale_possible: 'yes',
        reason: 'Verified single owner building',
      })
    })
  })

  it('shows success message after override', async () => {
    const updatedDetail: AddressGroupDetail = {
      ...mockDetail,
      manually_reviewed: true,
      manual_override_status: 'likely_not_condo',
      manual_override_reason: 'Test reason',
    }
    vi.mocked(condoFilterService.applyOverride).mockResolvedValue(updatedDetail)

    render(
      <CondoDetailView analysisId={1} open={true} onClose={onClose} />,
    )

    await waitFor(() => {
      expect(screen.getByText('456 oak ave')).toBeInTheDocument()
    })

    // Fill in reason (required field)
    const reasonField = screen.getByLabelText(/reason/i)
    await user.type(reasonField, 'Test reason')

    // Submit
    const submitButton = screen.getByRole('button', { name: /apply override/i })
    await user.click(submitButton)

    await waitFor(() => {
      expect(screen.getByText('Override applied successfully.')).toBeInTheDocument()
    })
  })

  it('shows validation error when reason is empty', async () => {
    render(
      <CondoDetailView analysisId={1} open={true} onClose={onClose} />,
    )

    await waitFor(() => {
      expect(screen.getByText('456 oak ave')).toBeInTheDocument()
    })

    // Submit the form directly to bypass native HTML5 required validation
    const form = screen.getByRole('button', { name: /apply override/i }).closest('form')!
    fireEvent.submit(form)

    await waitFor(() => {
      expect(screen.getByText('Reason is required.')).toBeInTheDocument()
    })

    // Should not call API
    expect(condoFilterService.applyOverride).not.toHaveBeenCalled()
  })
})
