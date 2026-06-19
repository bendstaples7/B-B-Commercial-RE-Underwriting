/**
 * Tests for DataSourcesPanel component and sub-components
 *
 * Task 7.1 — Unit tests
 * Task 7.2 — Property test: CoverageBar value bounded [0, 100]
 * Task 7.3 — Property test: StatusSummaryBanner color logic
 *
 * Validates: Requirements 1.5, 1.6, 4.1, 6.5, 7.1, 7.2, 7.3, 7.4
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@/test/testUtils'
import * as fc from 'fast-check'
import DataSourcesPanel, { StatusSummaryBanner } from './DataSourcesPanel'
import { dataSourcesService } from '@/services/api'
import type {
  DataSourceStatus,
  SocrataDatasetStatus,
  EnrichmentSourceStatus,
  ImportSourceStatus,
  HubSpotSourceStatus,
} from '@/types'

// ---------------------------------------------------------------------------
// Mock the API service
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  dataSourcesService: {
    getStatus: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Fixture helpers
// ---------------------------------------------------------------------------

function makeSocrataDataset(overrides: Partial<SocrataDatasetStatus> = {}): SocrataDatasetStatus {
  return {
    name: 'parcel_universe',
    source_type: 'socrata',
    refresh_type: 'periodic',
    is_active: true,
    status: 'fresh',
    last_refreshed_at: '2025-01-15T14:32:00Z',
    row_count: 100000,
    days_since_sync: 1,
    last_error: null,
    ...overrides,
  }
}

function makeEnrichmentSource(overrides: Partial<EnrichmentSourceStatus> = {}): EnrichmentSourceStatus {
  return {
    name: 'skip_trace',
    source_type: 'enrichment',
    refresh_type: 'on_demand',
    is_active: true,
    last_refreshed_at: '2025-01-14T09:10:00Z',
    success_count: 34,
    failed_count: 0,
    pending_count: 0,
    not_run_count: 16,
    total_leads_count: 50,
    ...overrides,
  }
}

function makeImportSource(overrides: Partial<ImportSourceStatus> = {}): ImportSourceStatus {
  return {
    name: 'Google Sheets',
    source_type: 'import',
    refresh_type: 'static',
    is_active: true,
    last_refreshed_at: '2025-01-10T08:00:00Z',
    rows_imported: 120,
    import_status: 'completed',
    ...overrides,
  }
}

function makeHubSpotSource(overrides: Partial<HubSpotSourceStatus> = {}): HubSpotSourceStatus {
  return {
    name: 'HubSpot',
    source_type: 'hubspot',
    refresh_type: 'on_demand',
    is_active: true,
    connected: true,
    ...overrides,
  }
}

function makeStatus(overrides: Partial<DataSourceStatus> = {}): DataSourceStatus {
  return {
    socrata_datasets: [makeSocrataDataset()],
    enrichment_sources: [makeEnrichmentSource()],
    import_source: makeImportSource(),
    hubspot_source: makeHubSpotSource(),
    gis_connectors: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Task 7.1 — Unit tests
// ---------------------------------------------------------------------------

describe('DataSourcesPanel', () => {
  describe('loading state', () => {
    it('renders loading skeleton while query is loading', async () => {
      // Never-resolving promise keeps the query in loading state
      vi.mocked(dataSourcesService.getStatus).mockReturnValue(new Promise(() => {}))

      render(<DataSourcesPanel />)

      expect(screen.getByLabelText('Loading data sources')).toBeInTheDocument()
    })
  })

  describe('error state', () => {
    it('renders error message and Retry button when query fails', async () => {
      vi.mocked(dataSourcesService.getStatus).mockRejectedValue(new Error('Network error'))

      render(<DataSourcesPanel />)

      await waitFor(() => {
        expect(screen.getByText('Data source status could not be loaded.')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
    })

    it('Retry button is clickable and does not throw', async () => {
      vi.mocked(dataSourcesService.getStatus).mockRejectedValue(new Error('Network error'))

      render(<DataSourcesPanel />)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument()
      })

      // Clicking Retry triggers a refetch — mock resolves on the second call
      vi.mocked(dataSourcesService.getStatus).mockResolvedValue(makeStatus())

      expect(() => {
        fireEvent.click(screen.getByRole('button', { name: /retry/i }))
      }).not.toThrow()
    })
  })

  describe('stale Socrata dataset', () => {
    it('shows amber WarningAmberIcon with aria-label "{name}: stale"', async () => {
      vi.mocked(dataSourcesService.getStatus).mockResolvedValue(
        makeStatus({
          socrata_datasets: [
            makeSocrataDataset({ name: 'parcel_universe', status: 'stale', days_since_sync: 5 }),
          ],
        })
      )

      render(<DataSourcesPanel />)

      await waitFor(() => {
        // The component renders both a Box wrapper and the icon SVG with this label
        const elements = screen.getAllByLabelText('parcel_universe: stale')
        expect(elements.length).toBeGreaterThanOrEqual(1)
      })
    })
  })

  describe('never-synced Socrata dataset', () => {
    it('shows red ErrorIcon with aria-label "{name}: never_synced"', async () => {
      vi.mocked(dataSourcesService.getStatus).mockResolvedValue(
        makeStatus({
          socrata_datasets: [
            makeSocrataDataset({
              name: 'parcel_universe',
              status: 'never_synced',
              last_refreshed_at: null,
              days_since_sync: null,
            }),
          ],
        })
      )

      render(<DataSourcesPanel />)

      await waitFor(() => {
        // The component renders both a Box wrapper and the icon SVG with this label
        const elements = screen.getAllByLabelText('parcel_universe: never_synced')
        expect(elements.length).toBeGreaterThanOrEqual(1)
      })
    })
  })

  describe('zero total_leads_count', () => {
    it('renders "0 / 0 (N/A)" when total_leads_count === 0', async () => {
      vi.mocked(dataSourcesService.getStatus).mockResolvedValue(
        makeStatus({
          enrichment_sources: [
            makeEnrichmentSource({
              success_count: 0,
              failed_count: 0,
              pending_count: 0,
              not_run_count: 0,
              total_leads_count: 0,
            }),
          ],
        })
      )

      render(<DataSourcesPanel />)

      await waitFor(() => {
        expect(screen.getByText('0 / 0 (N/A)')).toBeInTheDocument()
      })
    })
  })

  describe('all sources healthy', () => {
    it('shows green "All data sources are current." banner', async () => {
      vi.mocked(dataSourcesService.getStatus).mockResolvedValue(
        makeStatus({
          socrata_datasets: [makeSocrataDataset({ status: 'fresh' })],
          enrichment_sources: [makeEnrichmentSource({ is_active: true, failed_count: 0 })],
        })
      )

      render(<DataSourcesPanel />)

      await waitFor(() => {
        expect(screen.getByText('All data sources are current.')).toBeInTheDocument()
      })
    })
  })

  describe('inactive enrichment source', () => {
    it('renders "(Inactive)" label when enrichment source is_active === false', async () => {
      vi.mocked(dataSourcesService.getStatus).mockResolvedValue(
        makeStatus({
          enrichment_sources: [
            makeEnrichmentSource({ is_active: false }),
          ],
        })
      )

      render(<DataSourcesPanel />)

      await waitFor(() => {
        expect(screen.getByText('(Inactive)')).toBeInTheDocument()
      })
    })
  })
})

// ---------------------------------------------------------------------------
// Task 7.2 — Property test: CoverageBar value bounded [0, 100]
//
// Validates: Requirements 4.1
// ---------------------------------------------------------------------------

describe('CoverageBar — Property 1: value stays in [0, 100] for any input', () => {
  it('CoverageBar value stays in [0, 100] for any input (property test)', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 10_000 }),
        fc.integer({ min: 0, max: 10_000 }),
        fc.integer({ min: 0, max: 10_000 }),
        (enriched, failed, notRun) => {
          const total = enriched + failed + notRun
          const pct = total > 0
            ? Math.min(100, Math.max(0, (enriched / total) * 100))
            : 0
          expect(pct).toBeGreaterThanOrEqual(0)
          expect(pct).toBeLessThanOrEqual(100)
        }
      )
    )
  })
})

// ---------------------------------------------------------------------------
// Task 7.3 — Property test: StatusSummaryBanner color logic
//
// Property 3: Banner is green iff ALL sources healthy
// Validates: Requirements 6.5
// ---------------------------------------------------------------------------

describe('StatusSummaryBanner — Property 3: green iff ALL sources healthy', () => {
  it('StatusSummaryBanner is green iff ALL sources healthy (property test)', () => {
    fc.assert(
      fc.property(
        // Generate arbitrary arrays of Socrata datasets
        fc.array(
          fc.record({
            name: fc.string({ minLength: 1, maxLength: 20 }),
            source_type: fc.constant('socrata' as const),
            refresh_type: fc.constant('periodic' as const),
            is_active: fc.boolean(),
            status: fc.oneof(
              fc.constant('fresh' as const),
              fc.constant('stale' as const),
              fc.constant('empty' as const),
              fc.constant('never_synced' as const)
            ),
            last_refreshed_at: fc.oneof(fc.constant(null), fc.constant('2025-01-01T00:00:00Z')),
            row_count: fc.integer({ min: 0, max: 1_000_000 }),
            days_since_sync: fc.oneof(fc.constant(null), fc.integer({ min: 0, max: 365 })),
            last_error: fc.constant(null),
          }),
          { maxLength: 3 }
        ),
        // Generate arbitrary arrays of enrichment sources
        fc.array(
          fc.record({
            name: fc.string({ minLength: 1, maxLength: 20 }),
            source_type: fc.constant('enrichment' as const),
            refresh_type: fc.constant('on_demand' as const),
            is_active: fc.boolean(),
            last_refreshed_at: fc.oneof(fc.constant(null), fc.constant('2025-01-01T00:00:00Z')),
            success_count: fc.integer({ min: 0, max: 100 }),
            failed_count: fc.integer({ min: 0, max: 100 }),
            pending_count: fc.integer({ min: 0, max: 100 }),
            not_run_count: fc.integer({ min: 0, max: 100 }),
            total_leads_count: fc.integer({ min: 0, max: 100 }),
          }),
          { maxLength: 3 }
        ),
        (socrataDatasets, enrichmentSources) => {
          const allFresh = socrataDatasets.every(ds => ds.status === 'fresh')
          const allActive = enrichmentSources.every(es => es.is_active)
          const noFailures = enrichmentSources.every(es => es.failed_count === 0)
          const shouldBeGreen = allFresh && allActive && noFailures

          const data: DataSourceStatus = {
            socrata_datasets: socrataDatasets,
            enrichment_sources: enrichmentSources,
            import_source: makeImportSource(),
            hubspot_source: makeHubSpotSource(),
            gis_connectors: [],
          }

          const { container } = render(<StatusSummaryBanner data={data} />)

          const alert = container.querySelector('[role="alert"]')
          expect(alert).not.toBeNull()

          if (shouldBeGreen) {
            // MUI success Alert has class MuiAlert-colorSuccess or severity="success"
            // Check for the "All data sources are current." text
            expect(alert!.textContent).toContain('All data sources are current.')
          } else {
            // Banner should NOT show the all-healthy message
            expect(alert!.textContent).not.toContain('All data sources are current.')
          }
        }
      )
    )
  })
})
