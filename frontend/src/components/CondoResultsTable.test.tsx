import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent, waitFor } from '@/test/testUtils'
import { CondoResultsTable } from './CondoResultsTable'
import { condoFilterService } from '@/services/condoFilterApi'
import type {
  AddressGroupAnalysis,
  CondoFilterParams,
  CondoFilterResultsResponse,
} from '@/types'

vi.mock('@/services/condoFilterApi', () => ({
  condoFilterService: {
    runAnalysis: vi.fn(),
    getResults: vi.fn(),
    getDetail: vi.fn(),
    applyOverride: vi.fn(),
    exportCsv: vi.fn(),
  },
}))

const mockAnalysis: AddressGroupAnalysis = {
  id: 1,
  normalized_address: '123 main st',
  source_type: 'commercial',
  property_count: 3,
  pin_count: 2,
  owner_count: 2,
  has_unit_number: false,
  has_condo_language: false,
  missing_pin_count: 0,
  missing_owner_count: 0,
  condo_risk_status: 'needs_review',
  building_sale_possible: 'unknown',
  analysis_details: {
    triggered_rules: ['rule_6_multiple_owners'],
    reason: 'Multiple owners detected',
    confidence: 'medium',
  },
  manually_reviewed: false,
  manual_override_status: null,
  manual_override_reason: null,
  analyzed_at: '2024-01-15T10:00:00Z',
  created_at: '2024-01-15T10:00:00Z',
  updated_at: '2024-01-15T10:00:00Z',
}

const mockResultsResponse: CondoFilterResultsResponse = {
  results: [mockAnalysis],
  total: 1,
  page: 1,
  per_page: 20,
  pages: 1,
}

const emptyResultsResponse: CondoFilterResultsResponse = {
  results: [],
  total: 0,
  page: 1,
  per_page: 20,
  pages: 0,
}

describe('CondoResultsTable', () => {
  let onFiltersChange: ReturnType<typeof vi.fn>
  let onRowClick: ReturnType<typeof vi.fn>
  const defaultFilters: CondoFilterParams = { page: 1, per_page: 20 }

  beforeEach(() => {
    vi.clearAllMocks()
    onFiltersChange = vi.fn()
    onRowClick = vi.fn()
    vi.mocked(condoFilterService.getResults).mockResolvedValue(mockResultsResponse)
  })

  it('renders filter controls', async () => {
    render(
      <CondoResultsTable
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onRowClick={onRowClick}
      />,
    )

    await waitFor(() => {
      expect(screen.getByLabelText('Condo Risk Status')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Building Sale Possible')).toBeInTheDocument()
    expect(screen.getByLabelText('Manually Reviewed')).toBeInTheDocument()
  })

  it('renders results table with data', async () => {
    render(
      <CondoResultsTable
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onRowClick={onRowClick}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('123 main st')).toBeInTheDocument()
    })

    expect(screen.getByText('needs review')).toBeInTheDocument()
    expect(screen.getByText('unknown')).toBeInTheDocument()
    expect(screen.getByText('medium')).toBeInTheDocument()
  })

  it('shows empty state when no results', async () => {
    vi.mocked(condoFilterService.getResults).mockResolvedValue(emptyResultsResponse)

    render(
      <CondoResultsTable
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onRowClick={onRowClick}
      />,
    )

    await waitFor(() => {
      expect(
        screen.getByText('No results found. Run analysis or adjust filters.'),
      ).toBeInTheDocument()
    })
  })

  it('filter change triggers onFiltersChange with updated condo_risk_status', async () => {
    render(
      <CondoResultsTable
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onRowClick={onRowClick}
      />,
    )

    await waitFor(() => {
      expect(screen.getByLabelText('Condo Risk Status')).toBeInTheDocument()
    })

    // Open the Condo Risk Status select
    const riskStatusSelect = screen.getByLabelText('Condo Risk Status')
    fireEvent.mouseDown(riskStatusSelect)

    const listbox = screen.getByRole('listbox')
    const likelyCondo = within(listbox).getByText('Likely Condo')
    fireEvent.click(likelyCondo)

    expect(onFiltersChange).toHaveBeenCalledWith({
      ...defaultFilters,
      condo_risk_status: 'likely_condo',
      page: 1,
    })
  })

  it('filter change triggers onFiltersChange with updated building_sale_possible', async () => {
    render(
      <CondoResultsTable
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onRowClick={onRowClick}
      />,
    )

    await waitFor(() => {
      expect(screen.getByLabelText('Building Sale Possible')).toBeInTheDocument()
    })

    const buildingSaleSelect = screen.getByLabelText('Building Sale Possible')
    fireEvent.mouseDown(buildingSaleSelect)

    const listbox = screen.getByRole('listbox')
    const yesOption = within(listbox).getByText('Yes')
    fireEvent.click(yesOption)

    expect(onFiltersChange).toHaveBeenCalledWith({
      ...defaultFilters,
      building_sale_possible: 'yes',
      page: 1,
    })
  })

  it('pagination page change triggers onFiltersChange', async () => {
    const manyResults: CondoFilterResultsResponse = {
      results: [mockAnalysis],
      total: 50,
      page: 1,
      per_page: 20,
      pages: 3,
    }
    vi.mocked(condoFilterService.getResults).mockResolvedValue(manyResults)

    render(
      <CondoResultsTable
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onRowClick={onRowClick}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('123 main st')).toBeInTheDocument()
    })

    // Click next page button
    const nextPageButton = screen.getByLabelText('Go to next page')
    fireEvent.click(nextPageButton)

    expect(onFiltersChange).toHaveBeenCalledWith({
      ...defaultFilters,
      page: 2,
    })
  })

  it('row click calls onRowClick with the analysis record', async () => {
    render(
      <CondoResultsTable
        filters={defaultFilters}
        onFiltersChange={onFiltersChange}
        onRowClick={onRowClick}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('123 main st')).toBeInTheDocument()
    })

    const row = screen.getByRole('button', { name: /view details for 123 main st/i })
    fireEvent.click(row)

    expect(onRowClick).toHaveBeenCalledWith(mockAnalysis)
  })
})
