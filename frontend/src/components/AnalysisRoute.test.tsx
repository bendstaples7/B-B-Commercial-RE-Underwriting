/**
 * AnalysisRoute step rendering tests.
 *
 * These tests verify that each workflow step renders the correct content
 * based on the session state returned by the backend. They use a mocked
 * React Query cache so no real API calls are made.
 *
 * Purpose: answer "why is nothing showing on step X?" by reading test
 * output rather than launching a browser.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider, createTheme } from '@mui/material/styles'

// ---------------------------------------------------------------------------
// Mock the Google Maps loader so tests don't need a real API key
// ---------------------------------------------------------------------------
vi.mock('@react-google-maps/api', () => ({
  useLoadScript: () => ({ isLoaded: true }),
}))

// ---------------------------------------------------------------------------
// Mock analysisService — each test sets the return value on getSession
// ---------------------------------------------------------------------------
const mockGetSession = vi.fn()
const mockAdvanceToStep = vi.fn()
const mockUpdateStepData = vi.fn()
const mockGoBackToStep = vi.fn()
const mockListDeals = vi.fn().mockResolvedValue([])

vi.mock('@/services/api', () => ({
  analysisService: {
    getSession: (...args: any[]) => mockGetSession(...args),
    advanceToStep: (...args: any[]) => mockAdvanceToStep(...args),
    updateStepData: (...args: any[]) => mockUpdateStepData(...args),
    goBackToStep: (...args: any[]) => mockGoBackToStep(...args),
    startAnalysis: vi.fn(),
  },
  multifamilyService: {
    listDeals: (...args: any[]) => mockListDeals(...args),
  },
  default: {
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}))

// Mock child components that have complex dependencies
vi.mock('@/components/PropertyFactsForm', () => ({
  PropertyFactsForm: ({ propertyFacts }: any) => (
    <div>
      <h5>Step 1: Property Facts</h5>
      {propertyFacts && <div>Property Information</div>}
    </div>
  ),
}))

vi.mock('@/components/GeminiNarrativePanel', () => ({
  GeminiNarrativePanel: ({ narrative }: any) =>
    narrative ? <div>AI Analysis</div> : null,
}))

import App from '../App'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const theme = createTheme()

function makeSession(overrides: Record<string, any>) {
  return {
    session_id: 'test-session-id',
    current_step: 'PROPERTY_FACTS',
    loading: false,
    subject_property: null,
    step_results: {},
    completed_steps: [],
    ranked_comparables: [],
    valuation_result: null,
    ...overrides,
  }
}

function renderAnalysisStep(sessionOverrides: Record<string, any>) {
  mockGetSession.mockResolvedValue(makeSession(sessionOverrides))

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <MemoryRouter initialEntries={['/analysis/arv/test-session-id']}>
          <App />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

// Helper: wait for the main content area to contain expected text
async function waitForMainContent(text: string) {
  await waitFor(() => {
    const main = document.querySelector('[role="main"]')
    expect(main?.textContent).toContain(text)
  }, { timeout: 5000 })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AnalysisRoute — step rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockListDeals.mockResolvedValue([])
  })

  it('shows property facts form on PROPERTY_FACTS step', async () => {
    renderAnalysisStep({
      current_step: 'PROPERTY_FACTS',
      subject_property: {
        address: '1234 W Lunt Ave, Chicago, IL 60626',
        property_type: 'single_family',
        bedrooms: 4,
        bathrooms: 2,
        square_footage: 1536,
        year_built: 1911,
        construction_type: 'frame',
        interior_condition: 'average',
        basement: false,
        parking_spaces: 0,
        assessed_value: 43000,
        annual_taxes: 0,
        zoning: null,
        lot_size: null,
        units: null,
        latitude: 42.009,
        longitude: -87.663,
        data_source: 'cook_county_assessor',
        user_modified_fields: [],
      },
    })

    await waitForMainContent('Step 1: Property Facts')
    await waitForMainContent('Property Information')
  })

  it('shows AI narrative on COMPARABLE_REVIEW step', async () => {
    renderAnalysisStep({
      current_step: 'COMPARABLE_REVIEW',
      step_results: {
        COMPARABLE_SEARCH: {
          narrative: 'Section A: Location Analysis\nTest narrative content.',
          comparable_count: 4,
          status: 'complete',
        },
      },
    })

    await waitForMainContent('Comparable Review')
    await waitForMainContent('AI Analysis')

    const main = document.querySelector('[role="main"]')!
    expect(main.textContent).toContain('Advance to Weighted Scoring')
    expect(main.textContent).toContain('Back')
  })

  it('shows ranked comparables table on WEIGHTED_SCORING step', async () => {
    renderAnalysisStep({
      current_step: 'WEIGHTED_SCORING',
      ranked_comparables: [
        {
          id: 1,
          rank: 1,
          total_score: 87.0,  // backend stores as 0-100 scale
          score_breakdown: {
            recency_score: 90.0, proximity_score: 85.0, units_score: 100.0,
            beds_baths_score: 80.0, sqft_score: 75.0, construction_score: 100.0, interior_score: 90.0,
          },
          comparable: {
            id: 10, address: '1300 W Greenleaf Ave, Chicago, IL 60626',
            sale_date: '2023-11-15', sale_price: 485000,
            property_type: 'SINGLE_FAMILY', units: 1, bedrooms: 4, bathrooms: 2.0,
            square_footage: 1600, lot_size: 3000, year_built: 1915,
            construction_type: 'FRAME', interior_condition: 'AVERAGE',
            distance_miles: 0.3, latitude: 42.008, longitude: -87.665,
          },
        },
      ],
    })

    await waitForMainContent('Weighted Scoring')

    const main = document.querySelector('[role="main"]')!
    expect(main.textContent).toContain('1300 W Greenleaf Ave')
    expect(main.textContent).toContain('$485,000')
    expect(main.textContent).toContain('87%')  // total_score already in 0-100 scale
    expect(main.textContent).toContain('Advance to Valuation Models')
    expect(main.textContent).toContain('Back')
  })

  it('shows ARV range on VALUATION step', async () => {
    renderAnalysisStep({
      current_step: 'VALUATION_MODELS',
      valuation_result: {
        conservative_arv: 460000,
        likely_arv: 480000,
        aggressive_arv: 500000,
        confidence_score: 85.0,  // backend stores as 0-100 scale
        key_drivers: ['Strong comparable sales', 'Good location'],
        all_valuations: [460000, 475000, 480000, 490000, 500000],
      },
    })

    await waitForMainContent('Valuation Models')

    const main = document.querySelector('[role="main"]')!
    expect(main.textContent).toContain('Conservative ARV')
    expect(main.textContent).toContain('$460,000')
    expect(main.textContent).toContain('Likely ARV')
    expect(main.textContent).toContain('$480,000')
    expect(main.textContent).toContain('Aggressive ARV')
    expect(main.textContent).toContain('$500,000')
    expect(main.textContent).toContain('85%')  // confidence_score already in 0-100 scale
    expect(main.textContent).toContain('Strong comparable sales')
    expect(main.textContent).toContain('Generate Report')
    expect(main.textContent).toContain('Back')
  })

  it('shows report generated on REPORT_GENERATION step', async () => {
    renderAnalysisStep({ current_step: 'REPORT_GENERATION' })

    await waitForMainContent('Report Generated')
    await waitForMainContent('Your analysis report is ready.')

    const main = document.querySelector('[role="main"]')!
    expect(main.textContent).toContain('Back')
    expect(main.textContent).toContain('Start New Analysis')
  })

  it('shows all 5 stepper labels on COMPARABLE_REVIEW step', async () => {
    renderAnalysisStep({
      current_step: 'COMPARABLE_REVIEW',
      step_results: {
        COMPARABLE_SEARCH: { narrative: 'test', comparable_count: 3, status: 'complete' },
      },
    })

    await waitForMainContent('Comparable Review')

    const main = document.querySelector('[role="main"]')!
    expect(main.textContent).toContain('Property Facts')
    expect(main.textContent).toContain('Weighted Scoring')
    expect(main.textContent).toContain('Valuation')
    expect(main.textContent).toContain('Report')
  })
})
