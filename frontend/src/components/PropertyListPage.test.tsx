/**
 * Component tests for PropertyListPage — new filter controls
 *
 * Covers:
 * - source_type Select renders all 5 options plus "All Sources"
 * - Selecting a source_type value calls leadService.listLeads with source_type param
 * - Entering an owner_user_id calls leadService.listLeads with owner_user_id param
 * - Page resets to 1 when source_type changes
 * - Page resets to 1 when owner_user_id changes
 *
 * Requirements: 11.1, 11.2
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@/test/testUtils'
import { PropertyListPage } from './PropertyListPage'

// ---------------------------------------------------------------------------
// Mock heavy sub-components to keep tests fast and focused
// ---------------------------------------------------------------------------

vi.mock('@/components/CondoResultsTable', () => ({
  CondoResultsTable: () => <div data-testid="condo-results-table" />,
}))

vi.mock('@/components/CondoDetailView', () => ({
  CondoDetailView: () => null,
}))

vi.mock('@/components/RecalculateButton', () => ({
  RecalculateButton: () => <button data-testid="recalculate-button">Recalculate</button>,
  default: () => <button data-testid="recalculate-button">Recalculate</button>,
}))

vi.mock('@/components/ScoreLegend', () => ({
  ScoreLegend: () => <div data-testid="score-legend" />,
  default: () => <div data-testid="score-legend" />,
}))

vi.mock('@/components/ScoreFilterPanel', () => ({
  ScoreFilterPanel: () => <div data-testid="score-filter-panel" />,
  EMPTY_SCORE_FILTERS: {
    tiers: [],
    actions: [],
    lowDataQuality: false,
    missingPin: false,
    missingOwnerMailing: false,
    condoNeedsReview: false,
    condoLikelyCondo: false,
  },
}))

vi.mock('@/components/LeadScoreBadge', () => ({
  LeadScoreBadge: () => <span />,
  default: () => <span />,
}))

// AG Grid is DOM-heavy; replace with a minimal stub
vi.mock('ag-grid-react', () => ({
  AgGridReact: () => <div data-testid="ag-grid" />,
}))

vi.mock('ag-grid-community', () => ({
  ModuleRegistry: { registerModules: vi.fn() },
  AllCommunityModule: {},
}))

// ---------------------------------------------------------------------------
// Mock the condo service (used inside the component, not under test here)
// ---------------------------------------------------------------------------

vi.mock('@/services/condoFilterApi', () => ({
  condoFilterService: {
    runAnalysis: vi.fn(),
    getResults: vi.fn().mockResolvedValue({ results: [], total: 0, page: 1, per_page: 20, pages: 0 }),
    exportCsv: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Mock the lead services
// ---------------------------------------------------------------------------

vi.mock('@/services/leadApi', () => ({
  leadService: {
    listLeads: vi.fn(),
    listMarketingLists: vi.fn(),
  },
  propertyService: {
    listLeads: vi.fn(),
    listMarketingLists: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({
  leadScoreService: {
    getLeadScore: vi.fn(),
    recalculate: vi.fn(),
  },
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Shared test helpers
// ---------------------------------------------------------------------------

const EMPTY_LEADS_RESPONSE = {
  leads: [],
  total: 0,
  page: 1,
  per_page: 20,
  pages: 0,
}

const EMPTY_MARKETING_LISTS_RESPONSE = {
  lists: [],
  total: 0,
  page: 1,
  per_page: 20,
  pages: 0,
}

let leadService: typeof import('@/services/leadApi')['leadService']

beforeEach(async () => {
  vi.clearAllMocks()
  const mod = await import('@/services/leadApi')
  leadService = mod.leadService
  vi.mocked(leadService.listLeads).mockResolvedValue(EMPTY_LEADS_RESPONSE)
  vi.mocked(leadService.listMarketingLists).mockResolvedValue(EMPTY_MARKETING_LISTS_RESPONSE)
})

// ---------------------------------------------------------------------------
// Open the filter panel helper
// ---------------------------------------------------------------------------

async function openFilterPanel() {
  const filtersBtn = screen.getByRole('button', { name: /filters/i })
  fireEvent.click(filtersBtn)
  // The Source Type select should now be visible
  await waitFor(() => {
    expect(screen.getByLabelText('Source Type')).toBeInTheDocument()
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PropertyListPage — source_type filter', () => {
  it('renders Source Type select with "All Sources" and all 5 source type options', async () => {
    render(<PropertyListPage />)
    await openFilterPanel()

    // Open the Source Type dropdown
    const sourceTypeSelect = screen.getByLabelText('Source Type')
    fireEvent.mouseDown(sourceTypeSelect)

    const listbox = screen.getByRole('listbox')

    // Assert all 6 options are present (1 default + 5 source types)
    expect(within(listbox).getByText('All Sources')).toBeInTheDocument()
    expect(within(listbox).getByText('Foreclosure')).toBeInTheDocument()
    expect(within(listbox).getByText('Long Owned')).toBeInTheDocument()
    expect(within(listbox).getByText('Absentee Owner')).toBeInTheDocument()
    expect(within(listbox).getByText('Tax Distress')).toBeInTheDocument()
    expect(within(listbox).getByText('Manual Distress')).toBeInTheDocument()

    // Total of 6 options
    expect(within(listbox).getAllByRole('option')).toHaveLength(6)
  })

  it('passes source_type query param when a source type is selected', async () => {
    render(<PropertyListPage />)
    await openFilterPanel()

    // Clear any initial calls
    vi.mocked(leadService.listLeads).mockClear()
    vi.mocked(leadService.listLeads).mockResolvedValue(EMPTY_LEADS_RESPONSE)

    // Open and select "Foreclosure"
    const sourceTypeSelect = screen.getByLabelText('Source Type')
    fireEvent.mouseDown(sourceTypeSelect)
    const listbox = screen.getByRole('listbox')
    fireEvent.click(within(listbox).getByText('Foreclosure'))

    // Wait for the component to re-fetch with the new filter
    await waitFor(() => {
      expect(vi.mocked(leadService.listLeads)).toHaveBeenCalled()
    })

    const calls = vi.mocked(leadService.listLeads).mock.calls
    const lastCallArgs = calls[calls.length - 1][0]
    expect(lastCallArgs).toMatchObject({ source_type: 'foreclosure' })
  })

  it('passes source_type="long_owned" when Long Owned is selected', async () => {
    render(<PropertyListPage />)
    await openFilterPanel()

    vi.mocked(leadService.listLeads).mockClear()
    vi.mocked(leadService.listLeads).mockResolvedValue(EMPTY_LEADS_RESPONSE)

    const sourceTypeSelect = screen.getByLabelText('Source Type')
    fireEvent.mouseDown(sourceTypeSelect)
    const listbox = screen.getByRole('listbox')
    fireEvent.click(within(listbox).getByText('Long Owned'))

    await waitFor(() => {
      expect(vi.mocked(leadService.listLeads)).toHaveBeenCalled()
    })

    const calls = vi.mocked(leadService.listLeads).mock.calls
    const lastCallArgs = calls[calls.length - 1][0]
    expect(lastCallArgs).toMatchObject({ source_type: 'long_owned' })
  })

  it('resets page to 1 when source_type filter changes', async () => {
    // Step 1: Render with enough pages for pagination to appear
    const MULTI_PAGE_RESPONSE = {
      leads: [],
      total: 60,
      page: 1,
      per_page: 20,
      pages: 3,
    }
    vi.mocked(leadService.listLeads).mockResolvedValue(MULTI_PAGE_RESPONSE)

    render(<PropertyListPage />)

    // Wait for pagination to render
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /go to page 2/i })).toBeInTheDocument()
    })

    // Step 2: Navigate to page 2 via the pagination component
    const pageTwoBtn = screen.getByRole('button', { name: /go to page 2/i })
    fireEvent.click(pageTwoBtn)

    // Wait for the re-fetch triggered by page change
    await waitFor(() => {
      expect(vi.mocked(leadService.listLeads).toHaveBeenCalledTimes(2))
    })

    // Step 3: Clear calls and open the filter panel
    vi.mocked(leadService.listLeads).mockClear()
    await openFilterPanel()

    // Step 4: Change a filter that should trigger page reset to 1
    vi.mocked(leadService.listLeads).mockResolvedValue(EMPTY_LEADS_RESPONSE)
    const sourceTypeSelect = screen.getByLabelText('Source Type')
    fireEvent.mouseDown(sourceTypeSelect)
    const listbox = screen.getByRole('listbox')
    fireEvent.click(within(listbox).getByText('Tax Distress'))

    await waitFor(() => {
      expect(vi.mocked(leadService.listLeads)).toHaveBeenCalled()
    })

    // Step 5: Assert the filter change reset the page back to 1
    const calls = vi.mocked(leadService.listLeads).mock.calls
    const lastCallArgs = calls[calls.length - 1][0]
    expect(lastCallArgs).toMatchObject({ page: 1 })
  })
})

describe('PropertyListPage — owner_user_id filter', () => {
  it('passes owner_user_id query param when text is entered in the Owner user ID field', async () => {
    render(<PropertyListPage />)
    await openFilterPanel()

    vi.mocked(leadService.listLeads).mockClear()
    vi.mocked(leadService.listLeads).mockResolvedValue(EMPTY_LEADS_RESPONSE)

    const ownerUserIdField = screen.getByPlaceholderText('Owner user ID')
    fireEvent.change(ownerUserIdField, { target: { value: 'user-123' } })

    await waitFor(() => {
      expect(vi.mocked(leadService.listLeads)).toHaveBeenCalled()
    })

    const calls = vi.mocked(leadService.listLeads).mock.calls
    const lastCallArgs = calls[calls.length - 1][0]
    expect(lastCallArgs).toMatchObject({ owner_user_id: 'user-123' })
  })

  it('resets page to 1 when owner_user_id filter changes', async () => {
    render(<PropertyListPage />)
    await openFilterPanel()

    vi.mocked(leadService.listLeads).mockClear()
    vi.mocked(leadService.listLeads).mockResolvedValue(EMPTY_LEADS_RESPONSE)

    const ownerUserIdField = screen.getByPlaceholderText('Owner user ID')
    fireEvent.change(ownerUserIdField, { target: { value: 'user-abc' } })

    await waitFor(() => {
      expect(vi.mocked(leadService.listLeads)).toHaveBeenCalled()
    })

    const calls = vi.mocked(leadService.listLeads).mock.calls
    const lastCallArgs = calls[calls.length - 1][0]
    expect(lastCallArgs).toMatchObject({ page: 1 })
  })

  it('does not include owner_user_id in params when field is empty', async () => {
    render(<PropertyListPage />)

    // On initial render, listLeads should not include owner_user_id
    await waitFor(() => {
      expect(vi.mocked(leadService.listLeads)).toHaveBeenCalled()
    })

    const calls = vi.mocked(leadService.listLeads).mock.calls
    const firstCallArgs = calls[0][0]
    expect(firstCallArgs).not.toHaveProperty('owner_user_id')
  })
})
