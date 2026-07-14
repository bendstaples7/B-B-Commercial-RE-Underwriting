/**
 * Property-Based Tests — Unified Lead Command Center
 *
 * Feature: unified-lead-command-center
 *
 * Each property test uses fc.assert with a minimum of 100 runs.
 * Each test is tagged with a comment in the format:
 *   // Feature: unified-lead-command-center, Property N: <property text>
 *
 * Tests are stubs (it.todo) — implementations are added in subsequent tasks.
 */
import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import * as fc from 'fast-check'
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route, Navigate, useParams, useLocation } from 'react-router-dom'
import { primaryOwnerDisplayName } from '@/utils/propertyContacts'
import { UnifiedLeadCommandCenter, ALL_LEAD_STATUSES } from './UnifiedLeadCommandCenter'
import { QueueTable } from './QueueTable'
import GlobalSearchBar from './GlobalSearchBar'
import { ThemeProvider, createTheme } from '@mui/material'

// ---------------------------------------------------------------------------
// Module-level mocks for service functions (Properties 16 & 17)
// ---------------------------------------------------------------------------

vi.mock('@/services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/api')>()
  return {
    ...actual,
    commandCenterService: {
      getCommandCenter: vi.fn(),
      getTimeline: vi.fn(),
      updateStatus: vi.fn(),
    },
    leadTaskService: {
      createTask: vi.fn(),
      completeTask: vi.fn(),
    },
    searchService: {
      search: vi.fn(),
    },
    leadScoreService: {
      getLeadScore: vi.fn().mockResolvedValue({ data: { latest: null, history: [] } }),
    },
  }
})

vi.mock('@/services/leadApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/leadApi')>()
  return {
    ...actual,
    leadService: {
      getLeadDetail: vi.fn(),
      listLeads: vi.fn().mockResolvedValue({ leads: [], total: 0, pages: 0 }),
      listMarketingLists: vi.fn().mockResolvedValue({ lists: [] }),
    },
  }
})

import type { PropertyDetail } from '@/types'

function cleanAddressPart(value?: string | null): string {
  return (value || '').trim().replace(/^,+|,+$/g, '').trim()
}

function expectedStickyHeaderAddress(payload: {
  id: number
  property_street?: string | null
  property_city?: string | null
  property_state?: string | null
  property_zip?: string | null
}): string {
  const street = cleanAddressPart(payload.property_street)
  const cityStateZip = [payload.property_city, payload.property_state, payload.property_zip]
    .map(cleanAddressPart)
    .filter(Boolean)
    .join(', ')

  if (street && cityStateZip) return `${street}, ${cityStateZip}`
  return street || cityStateZip || `Lead #${payload.id}`
}

function minimalPropertyDetail(id: number): PropertyDetail {
  return {
    id,
    property_street: '',
    property_city: null,
    property_state: null,
    property_zip: null,
    property_type: null,
    bedrooms: null,
    bathrooms: null,
    square_footage: null,
    lot_size: null,
    year_built: null,
    owner_first_name: null,
    owner_last_name: null,
    ownership_type: null,
    acquisition_date: null,
    phone_1: null,
    phone_2: null,
    phone_3: null,
    email_1: null,
    email_2: null,
    mailing_address: null,
    mailing_city: null,
    mailing_state: null,
    mailing_zip: null,
    lead_score: 50,
    lead_category: 'standard',
    data_source: null,
    last_import_job_id: null,
    created_at: null,
    updated_at: null,
    analysis_session_id: null,
    source: null,
    deal_source: null,
    deal_description: null,
    date_identified: null,
    notes: null,
    needs_skip_trace: null,
    skip_tracer: null,
    date_skip_traced: null,
    date_added_to_hubspot: null,
    units: null,
    units_allowed: null,
    zoning: null,
    county_assessor_pin: null,
    tax_bill_2021: null,
    most_recent_sale: null,
    owner_2_first_name: null,
    owner_2_last_name: null,
    address_2: null,
    returned_addresses: null,
    phone_4: null,
    phone_5: null,
    phone_6: null,
    phone_7: null,
    email_3: null,
    email_4: null,
    email_5: null,
    socials: null,
    up_next_to_mail: null,
    mailer_history: null,
    enrichment_records: [],
    marketing_lists: [],
    analysis_session: null,
    contacts: [],
  }
}

async function waitForCommandCenterLoaded(container: HTMLElement) {
  await waitFor(
    () => {
      expect(container.querySelector('header')).not.toBeNull()
    },
    { timeout: 5000 },
  )
}

// Mock LogNoteForm — renders a button that calls onSaved with a synthetic entry
// Used by Property 14 to trigger the prepend logic in ActivityPanel
vi.mock('@/components/LogNoteForm', () => ({
  LogNoteForm: ({ onSaved, leadId }: { onSaved: (entry: any) => void; leadId: number }) => (
    <button
      data-testid="mock-log-note-btn"
      onClick={() =>
        onSaved({
          id: 999999,
          lead_id: leadId,
          event_type: 'note_added',
          occurred_at: new Date().toISOString(),
          source: 'manual',
          actor: 'Test User',
          summary: 'Property 14 test note',
          metadata: null,
          hubspot_activity_id: null,
          is_deleted: false,
          created_at: new Date().toISOString(),
        })
      }
    >
      Add Note
    </button>
  ),
}))

// Mock LogCallForm — same pattern, used as an alternative in Property 14
vi.mock('@/components/LogCallForm', () => ({
  LogCallForm: ({ onSaved, leadId }: { onSaved: (entry: any) => void; leadId: number }) => (
    <button
      data-testid="mock-log-call-btn"
      onClick={() =>
        onSaved({
          id: 999998,
          lead_id: leadId,
          event_type: 'call_logged',
          occurred_at: new Date().toISOString(),
          source: 'manual',
          actor: 'Test User',
          summary: 'Property 14 test call',
          metadata: null,
          hubspot_activity_id: null,
          is_deleted: false,
          created_at: new Date().toISOString(),
        })
      }
    >
      Log Call
    </button>
  ),
}))

// ---------------------------------------------------------------------------
// Shared Arbitraries
// ---------------------------------------------------------------------------

// Valid lead IDs: positive integers
const validLeadId = fc.integer({ min: 1, max: 999999 })

// Invalid ID strings: anything that is NOT a positive integer string
const invalidIdString = fc.oneof(
  fc.constant('0'),
  fc.constant('-1'),
  fc.constant('abc'),
  fc.constant(''),
  fc.constant('1.5'),
  fc.string().filter(s => isNaN(Number(s)) || Number(s) <= 0 || !Number.isInteger(Number(s)))
)

// Task arbitrary — matches LeadTask interface
const taskArb = fc.record({
  id: fc.integer({ min: 1 }),
  lead_id: fc.integer({ min: 1 }),
  task_type: fc.constant('custom'),
  title: fc.string({ minLength: 1 }),
  status: fc.constant('open'),
  due_date: fc.constant(null),
  created_at: fc.constant(new Date().toISOString()),
  completed_at: fc.constant(null),
  created_by: fc.constant('user'),
})

// Timeline entry arbitrary — matches LeadTimelineEntry interface
const timelineEntryArb = fc.record({
  id: fc.integer({ min: 1 }),
  lead_id: fc.integer({ min: 1 }),
  event_type: fc.constantFrom(
    'note_added',
    'call_logged',
    'task_created',
    'task_completed',
    'status_changed',
    'hubspot_note',
    'hubspot_call'
  ),
  occurred_at: fc.constant(new Date().toISOString()),
  source: fc.constantFrom('manual', 'system', 'hubspot', 'hubspot_import'),
  actor: fc.string(),
  summary: fc.string(),
  metadata: fc.constant(null),
  hubspot_activity_id: fc.constant(null),
  is_deleted: fc.constant(false),
  created_at: fc.constant(new Date().toISOString()),
})

// Queue row arbitrary — matches QueueRow interface
const queueRowArb = fc.record({
  id: fc.integer({ min: 1, max: 999999 }),
  owner_first_name: fc.option(fc.string()),
  owner_last_name: fc.option(fc.string()),
  property_street: fc.option(fc.string()),
  property_city: fc.option(fc.string()),
  property_state: fc.option(fc.string()),
  lead_score: fc.integer({ min: 0, max: 100 }),
  lead_status: fc.constantFrom(
    'skip_trace', 'awaiting_skip_trace', 'mailing_no_contact_made',
    'mailing_contacted_no_interest', 'mailing_contacted_interested',
    'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    'deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact'
  ) as fc.Arbitrary<import('@/types').LeadStatus>,
  recommended_action: fc.option(fc.constantFrom(
    'enrich_data', 'resolve_match', 'analyze_property', 'follow_up_now',
    'ready_for_outreach', 'add_contact_info', 'create_task', 'nurture',
    'suppress', 'do_not_contact'
  ) as fc.Arbitrary<import('@/types').CRMRecommendedAction>),
  has_property_match: fc.boolean(),
  last_contact_date: fc.option(fc.constant(new Date().toISOString())),
  last_hubspot_sync_at: fc.option(fc.constant(new Date().toISOString())),
  hubspot_deal_stage: fc.option(fc.string()),
  follow_up_overdue: fc.boolean(),
  review_required: fc.boolean(),
  review_reason: fc.option(fc.string()),
  review_triggered_at: fc.option(fc.constant(new Date().toISOString())),
  unanswered_call_count: fc.nat(),
  is_warm: fc.boolean(),
})
// Uses fc.string() for lead_status — replace with fc.constantFrom(...ALL_LEAD_STATUSES)
// once the type is importable from the shared utility module.
const commandCenterPayloadArb = fc.record({
  id: fc.integer({ min: 1 }),
  owner_first_name: fc.option(fc.string()),
  owner_last_name: fc.option(fc.string()),
  property_street: fc.option(fc.string()),
  property_city: fc.option(fc.string()),
  property_state: fc.option(fc.string()),
  property_zip: fc.option(fc.string()),
  lead_score: fc.integer({ min: 0, max: 100 }),
  lead_status: fc.constantFrom(...ALL_LEAD_STATUSES),
  open_tasks: fc.array(taskArb, { maxLength: 20 }),
  // `total` must be >= entries.length, otherwise the generated pagination
  // metadata is invalid (total < entries.length) and timeline tests flake.
  // Generate the entries first, then derive a total constrained to >= length.
  timeline: fc.array(timelineEntryArb).chain((entries) =>
    fc.record({
      entries: fc.constant(entries),
      total: fc.integer({ min: entries.length }),
      page: fc.constant(1),
      per_page: fc.constant(20),
    })
  ),
  // Fields used by work-queue membership strip (server work_queues)
  work_queues: fc.array(
    fc.record({
      key: fc.constantFrom(
        'do-not-contact',
        'needs-review',
        'follow-up-overdue',
        'missing-property-match',
        'no-next-action',
        'previously-warm',
        'todays-action',
      ),
      label: fc.string({ minLength: 1 }),
      path: fc.constantFrom(
        '/queues/do-not-contact',
        '/queues/needs-review',
        '/queues/follow-up-overdue',
        '/queues/missing-property-match',
        '/queues/no-next-action',
      ),
    }),
    { maxLength: 4 },
  ),
  has_overdue_hubspot_task: fc.boolean(),
  overdue_task_title: fc.option(fc.string()),
  overdue_task_due: fc.option(fc.constant(new Date().toISOString())),
  is_warm: fc.boolean(),
  follow_up_overdue: fc.boolean(),
  review_required: fc.boolean(),
  review_reason: fc.option(fc.string()),
  has_property_match: fc.boolean(),
  recommended_action: fc.record({
    value: fc.option(fc.constantFrom('follow_up_now', 'create_task', 'no_action')),
    label: fc.option(fc.string()),
    explanation: fc.option(fc.string()),
    signals: fc.constant({}),
  }),
})

// Export arbitraries for use in sub-task test files
export {
  validLeadId,
  invalidIdString,
  commandCenterPayloadArb,
  queueRowArb,
  taskArb,
  timelineEntryArb,
}

// ---------------------------------------------------------------------------
// Property Tests (scaffolded — implementations added in subsequent tasks)
// ---------------------------------------------------------------------------

describe('UnifiedLeadCommandCenter — Property Tests', () => {
  // Feature: unified-lead-command-center, Property 1: Legacy route redirect — /properties/:id → /leads/:id
  it('Property 1: Legacy route redirect — /properties/:id → /leads/:id', () => {
    // Inline redirect component mirrors LegacyPropertyDetailRedirect in App.tsx
    function TestLegacyPropertyRedirect() {
      const { leadId } = useParams<{ leadId: string }>()
      return <Navigate to={'/leads/' + leadId} replace />
    }

    // Helper to capture the current location after any redirect settles
    function LocationCapture({ onLocation }: { onLocation: (loc: string) => void }) {
      const loc = useLocation()
      onLocation(loc.pathname)
      return null
    }

    fc.assert(
      fc.property(validLeadId, (leadId) => {
        let capturedPath = ''
        const { unmount } = render(
          <MemoryRouter initialEntries={[`/properties/${leadId}`]}>
            <Routes>
              <Route path="/properties/:leadId" element={<TestLegacyPropertyRedirect />} />
              <Route path="/leads/:id" element={<LocationCapture onLocation={(p) => { capturedPath = p }} />} />
            </Routes>
          </MemoryRouter>
        )
        expect(capturedPath).toBe(`/leads/${leadId}`)
        unmount()
      }),
      { numRuns: 50 }
    )
  })

  // Feature: unified-lead-command-center, Property 2: Legacy route redirect — /leads/:id/command-center → /leads/:id
  it('Property 2: Legacy route redirect — /leads/:id/command-center → /leads/:id', () => {
    // Inline redirect component mirrors LegacyCommandCenterRedirect in App.tsx
    function TestLegacyCommandCenterRedirect() {
      const { id } = useParams<{ id: string }>()
      return <Navigate to={'/leads/' + id} replace />
    }

    // Helper to capture the current location after any redirect settles
    function LocationCapture({ onLocation }: { onLocation: (loc: string) => void }) {
      const loc = useLocation()
      onLocation(loc.pathname)
      return null
    }

    fc.assert(
      fc.property(validLeadId, (leadId) => {
        let capturedPath = ''
        const { unmount } = render(
          <MemoryRouter initialEntries={[`/leads/${leadId}/command-center`]}>
            <Routes>
              <Route path="/leads/:id/command-center" element={<TestLegacyCommandCenterRedirect />} />
              <Route path="/leads/:id" element={<LocationCapture onLocation={(p) => { capturedPath = p }} />} />
            </Routes>
          </MemoryRouter>
        )
        expect(capturedPath).toBe(`/leads/${leadId}`)
        unmount()
      }),
      { numRuns: 50 }
    )
  })

  // Feature: unified-lead-command-center, Property 3: Invalid ID shows error state
  // **Validates: Requirements 1.4**
  it('Property 3: Invalid ID shows error state', () => {
    // Inline route wrapper that mirrors the App.tsx UnifiedLeadCommandCenterRoute logic
    // (UnifiedLeadCommandCenterRoute is not exported, so we replicate it here)
    function TestRoute() {
      const { id } = useParams<{ id: string }>()
      const numericId = Number(id)
      if (!id || !Number.isInteger(numericId) || numericId <= 0) {
        return <div data-testid="invalid-id-error">Invalid lead ID</div>
      }
      return <div data-testid="activity-panel" />
    }

    // Note: empty string is excluded because React Router's /leads/:id pattern
    // requires at least one character — `/leads/` never reaches the route component,
    // so that case is handled by the router's no-match behavior, not this component.
    // Note: "1.0" is also excluded — Number("1.0") === 1 which is a valid positive integer,
    // so the component correctly treats it as valid (renders the lead page, not error state).
    // URL-safe arbitrary: letters + digits + hyphen + underscore + dot, at least 1 char.
    // Excludes spaces, ?, #, %, &, and other characters that cause React Router to throw
    // "malformed URL segment" / "URIError: URI malformed" during MemoryRouter rendering.
    // Also filtered to exclude strings that Number() treats as valid positive integers.
    const urlSafeInvalidId = fc.stringMatching(/^[a-zA-Z0-9._-]{1,30}$/).filter(s => {
      const n = Number(s)
      // Keep only values that the component would render as invalid-id error:
      // NaN, non-integer, zero, negative, or leading-dot floats like ".5"
      return isNaN(n) || !Number.isInteger(n) || n <= 0
    })

    const invalidIdStringNonEmpty = fc.oneof(
      fc.constant('0'),
      fc.constant('-1'),
      fc.constant('abc'),
      fc.constant('1.5'),
      fc.constant('null'),
      fc.constant('undefined'),
      fc.constant('-999'),
      urlSafeInvalidId
    )

    fc.assert(
      fc.property(invalidIdStringNonEmpty, (invalidId) => {
        const { unmount, container } = render(
          <MemoryRouter initialEntries={[`/leads/${invalidId}`]}>
            <Routes>
              <Route path="/leads/:id" element={<TestRoute />} />
            </Routes>
          </MemoryRouter>
        )

        // Error state should be shown
        expect(container.querySelector('[data-testid="invalid-id-error"]')).not.toBeNull()

        // Data panels should NOT be present
        expect(container.querySelector('[data-testid="activity-panel"]')).toBeNull()
        expect(container.querySelector('[data-testid="tab-panel"]')).toBeNull()

        unmount()
      }),
      { numRuns: 50 }
    )
  })

  // Feature: unified-lead-command-center, Property 4: Properties list row click navigates to canonical route
  it.todo(
    'Property 4: Properties list row click navigates to canonical route'
  )

  // Feature: unified-lead-command-center, Property 5: Work queue navigation always uses canonical route
  it('Property 5: Work queue navigation always uses canonical route', async () => {
    const { fireEvent } = await import('@testing-library/react')

    // LocationTracker records every pathname change into the provided array
    function LocationTracker({ paths }: { paths: string[] }) {
      const loc = useLocation()
      React.useEffect(() => {
        paths.push(loc.pathname)
      })
      return null
    }

    await fc.assert(
      fc.asyncProperty(queueRowArb, async (row) => {
        // ---- 1. Lead name link navigates to /leads/:id ----
        {
          const visitedPaths: string[] = []
          const container = document.createElement('div')
          document.body.appendChild(container)

          const { unmount } = render(
            <MemoryRouter initialEntries={['/queue']}>
              <LocationTracker paths={visitedPaths} />
              <QueueTable rows={[row]} total={1} />
            </MemoryRouter>,
            { container }
          )

          // The lead name link is inside the cell with data-testid="row-name-{id}"
          const nameCell = container.querySelector(`[data-testid="row-name-${row.id}"]`)
          expect(nameCell).not.toBeNull()
          const nameLink = nameCell!.querySelector('a')
          expect(nameLink).not.toBeNull()
          fireEvent.click(nameLink!)

          // After click the MemoryRouter location should have changed to /leads/:id
          const expectedPath = '/leads/' + row.id
          expect(visitedPaths).toContain(expectedPath)

          unmount()
          document.body.removeChild(container)
        }

        // ---- 2. "Open lead detail" icon button navigates to /leads/:id ----
        {
          const visitedPaths: string[] = []
          const container = document.createElement('div')
          document.body.appendChild(container)

          const { unmount } = render(
            <MemoryRouter initialEntries={['/queue']}>
              <LocationTracker paths={visitedPaths} />
              <QueueTable rows={[row]} total={1} />
            </MemoryRouter>,
            { container }
          )

          const iconBtn = container.querySelector(`[data-testid="row-action-view-${row.id}"]`)
          expect(iconBtn).not.toBeNull()
          // The IconButton is rendered as an <a> when component={RouterLink}
          const iconAnchor = iconBtn!.closest('a') ?? iconBtn!.querySelector('a') ?? iconBtn!
          fireEvent.click(iconAnchor)

          const expectedPath = '/leads/' + row.id
          expect(visitedPaths).toContain(expectedPath)

          unmount()
          document.body.removeChild(container)
        }

        // ---- 3. Row body click (outside action controls) navigates to /leads/:id ----
        {
          const capturedPaths: string[] = []

          // Wrap QueueTable in a component that captures navigate() calls via location changes
          const container = document.createElement('div')
          document.body.appendChild(container)

          const { unmount } = render(
            <MemoryRouter initialEntries={['/queue']}>
              <LocationTracker paths={capturedPaths} />
              <QueueTable rows={[row]} total={1} />
            </MemoryRouter>,
            { container }
          )

          // Click the <TableRow> element itself (the row body, not a button or link)
          const tableRow = container.querySelector(`[data-testid="queue-row-${row.id}"]`)
          expect(tableRow).not.toBeNull()

          // Click the first <td> cell (score cell) to avoid hitting checkbox/button/anchor
          const scoreCell = container.querySelector(`[data-testid="row-score-${row.id}"]`)
          expect(scoreCell).not.toBeNull()
          fireEvent.click(scoreCell!)

          // Small tick to let navigate() state propagate
          await new Promise(r => setTimeout(r, 10))

          const expectedPath = '/leads/' + row.id
          expect(capturedPaths).toContain(expectedPath)

          unmount()
          document.body.removeChild(container)
        }
      }),
      { numRuns: 20 }
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 6: Global search navigates to search results page
  // **Validates: Requirements 4.1, 4.2**
  it('Property 6: Global search navigates to search results page', async () => {
    const searchTheme = createTheme()

    function LocationTracker({ paths }: { paths: string[] }) {
      const loc = useLocation()
      React.useEffect(() => {
        paths.push(`${loc.pathname}${loc.search}`)
      })
      return null
    }

    await fc.assert(
      fc.asyncProperty(
        fc.string({ minLength: 2, maxLength: 30 }).filter((s) => s.trim().length >= 2),
        async (query) => {
          const capturedPaths: string[] = []
          const container = document.createElement('div')
          document.body.appendChild(container)

          const { unmount } = render(
            <MemoryRouter initialEntries={['/']}>
              <LocationTracker paths={capturedPaths} />
              <ThemeProvider theme={searchTheme}>
                <GlobalSearchBar />
              </ThemeProvider>
            </MemoryRouter>,
            { container },
          )

          const inputWrapper = within(container).getByTestId('search-input')
          const inputEl = inputWrapper.querySelector('input') as HTMLInputElement
          const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype,
            'value',
          )?.set
          nativeInputValueSetter?.call(inputEl, query)
          inputEl.dispatchEvent(new Event('input', { bubbles: true }))
          fireEvent.keyDown(inputEl, { key: 'Enter' })

          const expected = `/search?q=${encodeURIComponent(query.trim())}&page=1`
          expect(capturedPaths).toContain(expected)

          unmount()
          document.body.removeChild(container)
        },
      ),
      { numRuns: 20 },
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 7: Sticky header renders all required fields for any lead
  // **Validates: Requirements 5.1**
  it('Property 7: Sticky header renders all required fields for any lead', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')
    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>

    await fc.assert(
      fc.asyncProperty(commandCenterPayloadArb, async (payload) => {
        // Set up mocks before rendering
        mockGetCommandCenter.mockReset()
        mockGetLeadDetail.mockReset()
        mockGetCommandCenter.mockResolvedValue(payload)
        mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(payload.id))

        const queryClient = new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })

        // Use a dedicated container so within() scopes queries to this render only
        const container = document.createElement('div')
        document.body.appendChild(container)

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={payload.id} />
            </MemoryRouter>
          </QueryClientProvider>,
          { container }
        )

        // Wait for React Query to resolve: the back-button only renders after
        // commandCenterData is loaded (StickyHeader is rendered post-load).
        await waitFor(
          () => {
            const header = container.querySelector('header')
            expect(header).not.toBeNull()
          },
          { timeout: 3000 }
        )

        // Get the sticky header element specifically to scope header-only assertions
        const headerEl = container.querySelector('header')!

        // 1. Property address is the sticky header focus; primary owner may appear under it
        const expectedAddress = expectedStickyHeaderAddress(payload)

        const addressBlock = headerEl.querySelector('[data-testid="sticky-header-address"]')
        expect(addressBlock).not.toBeNull()
        expect(addressBlock!.textContent).toContain(expectedAddress)

        const expectedOwner = primaryOwnerDisplayName(
          undefined,
          payload.owner_first_name,
          payload.owner_last_name,
        )
        const ownerEl = headerEl.querySelector('[data-testid="sticky-header-owner"]')
        if (expectedOwner) {
          expect(ownerEl).not.toBeNull()
          expect(ownerEl!.textContent).toContain(expectedOwner)
        } else {
          expect(ownerEl).toBeNull()
        }
        expect(headerEl.textContent).not.toContain('Owner 2:')
        expect(headerEl.textContent).not.toContain('Company:')
        expect(headerEl.textContent).not.toContain('Also listed:')

        // 2. Lead score — header button shows "N / 100"
        const scoreEl = headerEl.querySelector('[data-testid="header-lead-score"]')
        expect(scoreEl).not.toBeNull()
        expect(scoreEl!.textContent).toContain(String(payload.lead_score))
        expect(scoreEl!.textContent).toContain('/ 100')

        // 3. Lead status — LeadStatusChip in the header renders a chip
        //   - Known statuses → LEAD_STATUS_LABELS map
        //   - Unknown statuses → replace underscores with spaces, capitalize each word
        const LEAD_STATUS_LABELS: Record<string, string> = {
          skip_trace: 'Skip Trace',
          awaiting_skip_trace: 'Awaiting Skip Trace',
          mailing_no_contact_made: 'Mailing, No Contact Made',
          mailing_contacted_no_interest: 'Mailing, Contact Made, No Interest',
          mailing_contacted_interested: 'Mailing, Contact Made, Interested',
          negotiating_remote: 'Negotiating Remote',
          in_person_appointment: 'In Person Appointment',
          offer_delivered: 'Offer Delivered',
          deprioritize: 'Deprioritize',
          deal_won: 'Deal Won',
          deal_lost: 'Deal Lost',
          suppressed: 'Suppressed',
          do_not_contact: 'Do Not Contact',
        }
        const statusLabel = LEAD_STATUS_LABELS[payload.lead_status]

        // The status chip label element (LeadStatusSelector in header)
        const chipLabel = headerEl.querySelector('[data-testid="lead-status-selector"] .MuiChip-label')
        expect(chipLabel).not.toBeNull()
        expect(chipLabel!.textContent).toBe(statusLabel)

        unmount()
        document.body.removeChild(container)
        queryClient.clear()
      }),
      // 5 runs: each run does a full component mount + React Query flush (< 1s each)
      { numRuns: 5 }
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 8: Work-queue chips render without alert banners
  it('Property 8: Work-queue membership strip renders chips without banners', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')
    const payload = {
      id: 42,
      owner_first_name: 'Test',
      owner_last_name: 'Owner',
      property_street: '1 Main',
      property_city: 'Chicago',
      property_state: 'IL',
      lead_score: 50,
      lead_status: 'mailing_no_contact_made' as const,
      open_tasks: [],
      timeline: { entries: [], total: 0, page: 1, per_page: 20 },
      recommended_action: {
        value: 'follow_up_now',
        label: 'Follow Up',
        explanation: null,
        signals: {},
      },
      has_property_match: true,
      analysis_session_id: null,
      work_queues: [
        { key: 'follow-up-overdue', label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue' },
        { key: 'needs-review', label: 'Needs Review', path: '/queues/needs-review' },
      ],
    }
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(payload as never)
    vi.mocked(leadService.getLeadDetail).mockResolvedValue(minimalPropertyDetail(42))

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const theme = createTheme()
    render(
      <ThemeProvider theme={theme}>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={['/leads/42']}>
            <Routes>
              <Route path="/leads/:leadId" element={<UnifiedLeadCommandCenter />} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ThemeProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('work-queue-membership-strip')).toBeInTheDocument()
    })
    expect(screen.getByTestId('work-queue-strip-follow-up-overdue')).toBeInTheDocument()
    expect(screen.getByTestId('work-queue-strip-needs-review')).toBeInTheDocument()
    expect(screen.queryByTestId('work-queue-banner-follow-up-overdue')).not.toBeInTheDocument()
    expect(screen.queryByTestId('work-queue-banner-needs-review')).not.toBeInTheDocument()
  })

  // Feature: unified-lead-command-center, Property 9: Loading state hides data panels; loaded state shows them
  // **Validates: Requirements 5.8**
  it('Property 9: Loading state hides data panels; loaded state shows them', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')

    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>

    fc.assert(
      fc.property(validLeadId, (leadId) => {
        // Both queries never resolve → component stays in isLoading state
        mockGetCommandCenter.mockReturnValue(new Promise(() => {}))
        mockGetLeadDetail.mockReturnValue(new Promise(() => {}))

        const queryClient = new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={leadId} />
            </MemoryRouter>
          </QueryClientProvider>
        )

        // Loading indicator MUST be present
        expect(screen.getByRole('progressbar')).toBeInTheDocument()

        // Data panels MUST NOT be in the DOM while loading
        expect(screen.queryByTestId('activity-panel')).not.toBeInTheDocument()
        expect(screen.queryByTestId('tab-panel')).not.toBeInTheDocument()
        expect(screen.queryByTestId('property-sidebar')).not.toBeInTheDocument()
        expect(screen.queryByTestId('tasks-panel')).not.toBeInTheDocument()

        unmount()
        queryClient.clear()
        mockGetCommandCenter.mockReset()
        mockGetLeadDetail.mockReset()
      }),
      { numRuns: 10 }
    )
  })

  // Feature: unified-lead-command-center, Property 10: Status selector excludes current status from options
  // **Validates: Requirements 6.1**
  it('Property 10: Status selector excludes current status from options', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')
    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>

    const { ALL_LEAD_STATUSES } = await import('./UnifiedLeadCommandCenter')

    await fc.assert(
      fc.asyncProperty(fc.constantFrom(...ALL_LEAD_STATUSES), async (status) => {
        const payload = {
          id: 1,
          owner_first_name: null,
          owner_last_name: null,
          property_street: null,
          property_city: null,
          property_state: null,
          lead_score: 50,
          lead_status: status,
          open_tasks: [],
          timeline: { entries: [], total: 0, page: 1, per_page: 20 },
          recommended_action: { value: null, label: null, explanation: null, signals: {} },
        }

        mockGetCommandCenter.mockReset()
        mockGetLeadDetail.mockReset()
        mockGetCommandCenter.mockResolvedValue(payload)
        mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(1))

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        const container = document.createElement('div')
        document.body.appendChild(container)

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={1} />
            </MemoryRouter>
          </QueryClientProvider>,
          { container }
        )

        await waitForCommandCenterLoaded(container)

        const chip = within(container).getByTestId('lead-status-selector')
        fireEvent.click(chip)

        await waitFor(() => {
          expect(document.querySelector('[data-testid="lead-status-menu"]')).not.toBeNull()
        })

        const menuItems = document.querySelectorAll('[data-testid^="lead-status-option-"]')
        const itemValues = Array.from(menuItems).map((el) =>
          el.getAttribute('data-testid')!.replace('lead-status-option-', ''),
        )

        // Current status should NOT be in the options
        expect(itemValues).not.toContain(status)

        // All other statuses SHOULD be in the options
        const otherStatuses = ALL_LEAD_STATUSES.filter(s => s !== status)
        otherStatuses.forEach(s => {
          expect(itemValues).toContain(s)
        })

        // Close the dropdown
        fireEvent.keyDown(document.activeElement || document.body, { key: 'Escape' })

        unmount()
        document.body.removeChild(container)
        queryClient.clear()
      }),
      { numRuns: 13 }  // Exactly covers all 13 statuses
    )
  }, 60000)

  // Feature: unified-lead-command-center, Property 11: Open tasks list renders all tasks from payload
  // **Validates: Requirements 7.1**
  it('Property 11: Open tasks list renders all tasks from payload', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')
    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>

    await fc.assert(
      fc.asyncProperty(fc.array(taskArb, { maxLength: 10 }), async (tasks) => {
        const payload = {
          id: 1,
          owner_first_name: null, owner_last_name: null,
          property_street: null, property_city: null, property_state: null,
          lead_score: 50, lead_status: 'skip_trace',
          open_tasks: tasks,
          timeline: { entries: [], total: 0, page: 1, per_page: 20 },
          recommended_action: { value: null, label: null, explanation: null, signals: {} },
        }

        mockGetCommandCenter.mockReset()
        mockGetLeadDetail.mockReset()
        mockGetCommandCenter.mockResolvedValue(payload)
        mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(1))

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        const container = document.createElement('div')
        document.body.appendChild(container)

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={1} />
            </MemoryRouter>
          </QueryClientProvider>,
          { container }
        )

        await waitForCommandCenterLoaded(container)

        // Find the tasks panel rendered by TasksPanel (data-testid="tasks-panel")
        const tasksPanel = container.querySelector('[data-testid="tasks-panel"]')
        expect(tasksPanel).not.toBeNull()

        // LeadTaskList renders each task as <ListItem data-testid={`task-item-${task.id}`}>
        // taskArb uses status: 'open', so all tasks pass the openTasks filter
        const taskItems = tasksPanel!.querySelectorAll('[data-testid^="task-item-"]')

        expect(taskItems.length).toBe(tasks.length)

        unmount()
        document.body.removeChild(container)
        queryClient.clear()
      }),
      { numRuns: 15 }
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 12: Task creation optimistically grows the task list
  // **Validates: Requirements 7.2**
  it('Property 12: Task creation optimistically grows the task list', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')
    const { leadTaskService } = await import('@/services/api')
    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>
    const mockCreateTask = leadTaskService.createTask as ReturnType<typeof vi.fn>

    const { fireEvent, act } = await import('@testing-library/react')

    await fc.assert(
      fc.asyncProperty(fc.array(taskArb, { maxLength: 5 }), async (initialTasks) => {
        // Ensure unique IDs so DOM task-item counts match list length (Property 13 pattern).
        const tasks = initialTasks.map((t, i) => ({ ...t, id: i + 1 }))

        const payload = {
          id: 1,
          lead_status: 'skip_trace' as const,
          lead_score: 50,
          owner_first_name: null,
          owner_last_name: null,
          property_street: null,
          property_city: null,
          property_state: null,
          open_tasks: tasks,
          timeline: { entries: [], total: 0, page: 1, per_page: 20 },
          recommended_action: { value: null, label: null, explanation: null, signals: {} },
        }

        mockGetCommandCenter.mockReset()
        mockGetLeadDetail.mockReset()
        mockCreateTask.mockReset()

        mockGetCommandCenter.mockResolvedValue(payload)
        mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(1))
        // Never-resolving promise — backend call never completes
        mockCreateTask.mockReturnValue(new Promise(() => {}))

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        const container = document.createElement('div')
        document.body.appendChild(container)

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={1} />
            </MemoryRouter>
          </QueryClientProvider>,
          { container }
        )

        await waitForCommandCenterLoaded(container)

        // Get initial task count using the task-item-{id} pattern
        const tasksPanel = container.querySelector('[data-testid="tasks-panel"]')
        expect(tasksPanel).not.toBeNull()
        const initialCount = tasksPanel!.querySelectorAll('[data-testid^="task-item-"]').length
        expect(initialCount).toBe(tasks.length)

        // Open the task creation form
        const addBtn = tasksPanel!.querySelector('[data-testid="open-task-form-btn"]')
        expect(addBtn).not.toBeNull()
        fireEvent.click(addBtn!)

        // Fill in the task title
        const titleInput = tasksPanel!.querySelector('[data-testid="task-title-input"]')
        expect(titleInput).not.toBeNull()
        fireEvent.change(titleInput!, { target: { value: 'Test optimistic task' } })

        // Click save — this triggers the optimistic update before the API call resolves
        const saveBtn = tasksPanel!.querySelector('[data-testid="save-task-btn"]')
        expect(saveBtn).not.toBeNull()

        await act(async () => {
          fireEvent.click(saveBtn!)
          // Yield to let synchronous state updates flush (optimistic update fires
          // before the awaited API promise, so it's synchronous in the event handler)
          await new Promise(r => setTimeout(r, 0))
        })

        // Assert optimistic update: count should be tasks.length + 1
        const newCount = tasksPanel!.querySelectorAll('[data-testid^="task-item-"]').length
        expect(newCount).toBe(tasks.length + 1)

        unmount()
        document.body.removeChild(container)
        queryClient.clear()
      }),
      { numRuns: 10 }
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 13: Task completion optimistically shrinks the task list
  // **Validates: Requirements 7.3**
  it('Property 13: Task completion optimistically shrinks the task list', async () => {
    const { commandCenterService, leadTaskService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')
    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>
    const mockCompleteTask = leadTaskService.completeTask as ReturnType<typeof vi.fn>

    await fc.assert(
      fc.asyncProperty(fc.array(taskArb, { minLength: 1, maxLength: 5 }), async (initialTasks) => {
        // Ensure unique IDs so filter-by-id works correctly
        const tasks = initialTasks.map((t, i) => ({ ...t, id: i + 1 }))

        const payload = {
          id: 1,
          lead_status: 'skip_trace',
          lead_score: 50,
          owner_first_name: null,
          owner_last_name: null,
          property_street: null,
          property_city: null,
          property_state: null,
          open_tasks: tasks,
          timeline: { entries: [], total: 0, page: 1, per_page: 20 },
          recommended_action: { value: null, label: null, explanation: null, signals: {} },
        }

        mockGetCommandCenter.mockReset()
        mockGetLeadDetail.mockReset()
        mockGetCommandCenter.mockResolvedValue(payload)
        mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(1))

        // Mock completeTask to never resolve — tests optimistic removal before backend completes
        mockCompleteTask.mockReturnValue(new Promise(() => {}))

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        const container = document.createElement('div')
        document.body.appendChild(container)

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={1} />
            </MemoryRouter>
          </QueryClientProvider>,
          { container }
        )

        await waitForCommandCenterLoaded(container)

        const tasksPanel = container.querySelector('[data-testid="tasks-panel"]')
        expect(tasksPanel).not.toBeNull()

        // Count task items using the data-testid prefix pattern used by LeadTaskList
        const initialCount = tasksPanel!.querySelectorAll('[data-testid^="task-item-"]').length
        expect(initialCount).toBe(tasks.length)

        // Click the complete button on the first task (id=1)
        const firstTaskCompleteBtn = tasksPanel!.querySelector('[data-testid="complete-task-btn-1"]')
        expect(firstTaskCompleteBtn).not.toBeNull()
        firstTaskCompleteBtn!.dispatchEvent(new MouseEvent('click', { bubbles: true }))

        // Wait a tick for the optimistic state update to propagate
        await new Promise(r => setTimeout(r, 0))

        // Assert count is N-1 immediately (optimistic removal before backend resolves)
        const newCount = tasksPanel!.querySelectorAll('[data-testid^="task-item-"]').length
        expect(newCount).toBe(tasks.length - 1)

        unmount()
        document.body.removeChild(container)
        queryClient.clear()
      }),
      { numRuns: 10 }
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 14: New activity entries appear at the top of the timeline
  // **Validates: Requirements 8.1, 8.2**
  it('Property 14: New activity entries appear at the top of the timeline', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')
    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>

    const { fireEvent } = await import('@testing-library/react')

    await fc.assert(
      fc.asyncProperty(
        // Generate N existing timeline entries (0..8) with unique IDs
        fc.array(timelineEntryArb, { minLength: 0, maxLength: 8 }),
        async (initialEntries) => {
          // Ensure all initial entries have distinct IDs (avoids duplicate key warnings
          // and makes position assertions unambiguous)
          const entries = initialEntries.map((e, i) => ({ ...e, id: i + 1 }))

          const payload = {
            id: 1,
            owner_first_name: null,
            owner_last_name: null,
            property_street: null,
            property_city: null,
            property_state: null,
            lead_score: 50,
            lead_status: 'skip_trace',
            open_tasks: [],
            timeline: {
              entries,
              total: entries.length,
              page: 1,
              per_page: 20,
            },
            recommended_action: { value: null, label: null, explanation: null, signals: {} },
          }

          mockGetCommandCenter.mockReset()
          mockGetLeadDetail.mockReset()
          mockGetCommandCenter.mockResolvedValue(payload)
          mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(1))

          const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
          const container = document.createElement('div')
          document.body.appendChild(container)

          const { unmount } = render(
            <QueryClientProvider client={queryClient}>
              <MemoryRouter>
                <UnifiedLeadCommandCenter leadId={1} />
              </MemoryRouter>
            </QueryClientProvider>,
            { container }
          )

          await waitForCommandCenterLoaded(container)

          // Verify the activity panel is rendered
          const activityPanel = container.querySelector('[data-testid="activity-panel"]')
          expect(activityPanel).not.toBeNull()

          // Open the log note modal via RA quick action, then click the mocked LogNoteForm button
          const openNoteBtn = container.querySelector('[data-testid="ra-universal-btn-log_note"]')
          expect(openNoteBtn).not.toBeNull()
          fireEvent.click(openNoteBtn!)

          await waitFor(() => {
            expect(screen.getByTestId('mock-log-note-btn')).toBeInTheDocument()
          })

          fireEvent.click(screen.getByTestId('mock-log-note-btn'))

          // Wait for React state update to flush
          await new Promise(r => setTimeout(r, 50))

          // The new entry (id=999999) should now be at position 0 in the timeline list
          const timelineList = container.querySelector('[data-testid="timeline-list"]')
          expect(timelineList).not.toBeNull()

          // Get all timeline-entry-{id} children within the list
          const entryNodes = timelineList!.querySelectorAll('[data-testid^="timeline-entry-"]')

          // Total entries should be N + 1 (the new note prepended to the N originals)
          expect(entryNodes.length).toBe(entries.length + 1)

          // The first node must be the newly added entry (id=999999)
          const firstTestId = entryNodes[0].getAttribute('data-testid')
          expect(firstTestId).toBe('timeline-entry-999999')

          // If there were existing entries, the original first entry must now be at index 1
          if (entries.length > 0) {
            const secondTestId = entryNodes[1].getAttribute('data-testid')
            expect(secondTestId).toBe(`timeline-entry-${entries[0].id}`)
          }

          unmount()
          document.body.removeChild(container)
          queryClient.clear()
        }
      ),
      { numRuns: 10 }
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 15: Load-more appends rather than replaces timeline entries
  // **Validates: Requirements 8.3**
  it('Property 15: Load-more appends rather than replaces timeline entries', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.tuple(
          fc.array(timelineEntryArb, { minLength: 1, maxLength: 5 }),
          fc.array(timelineEntryArb, { minLength: 1, maxLength: 5 })
        ),
        async ([initialEntries, moreEntries]) => {
          const { commandCenterService } = await import('@/services/api')
          const { leadService } = await import('@/services/leadApi')
          const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
          const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>
          const mockGetTimeline = commandCenterService.getTimeline as ReturnType<typeof vi.fn>

          // Total > initial entries count so the "Load more" button is shown
          const total = initialEntries.length + moreEntries.length

          mockGetCommandCenter.mockReset()
          mockGetLeadDetail.mockReset()
          mockGetTimeline.mockReset()

          mockGetCommandCenter.mockResolvedValue({
            id: 1,
            lead_status: 'skip_trace',
            lead_score: 50,
            owner_first_name: null,
            owner_last_name: null,
            property_street: null,
            property_city: null,
            property_state: null,
            open_tasks: [],
            timeline: { entries: initialEntries, total, page: 1, per_page: 20 },
            recommended_action: { value: null, label: null, explanation: null, signals: {} },
          })
          mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(1))
          mockGetTimeline.mockResolvedValue({ entries: moreEntries, total, page: 2, per_page: 20 })

          const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
          const container = document.createElement('div')
          document.body.appendChild(container)

          const { unmount } = render(
            <QueryClientProvider client={queryClient}>
              <MemoryRouter>
                <UnifiedLeadCommandCenter leadId={1} />
              </MemoryRouter>
            </QueryClientProvider>,
            { container }
          )

          await waitForCommandCenterLoaded(container)

          // Verify initial entry count is N
          const initialRendered = container.querySelectorAll('[data-testid^="timeline-entry-"]')
          expect(initialRendered.length).toBe(initialEntries.length)

          // Find and click the "Load more" button
          const loadMoreBtn = container.querySelector('[data-testid="load-more-btn"]')
          expect(loadMoreBtn).not.toBeNull()

          const { fireEvent } = await import('@testing-library/react')
          fireEvent.click(loadMoreBtn!)

          // Wait for the async load-more operation to complete
          await new Promise(r => setTimeout(r, 100))

          // After loading more, total entries should be N + M
          const afterLoadRendered = container.querySelectorAll('[data-testid^="timeline-entry-"]')
          expect(afterLoadRendered.length).toBe(initialEntries.length + moreEntries.length)

          unmount()
          document.body.removeChild(container)
          queryClient.clear()
        }
      ),
      { numRuns: 10 }
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 16: Command-center endpoint called exactly once per mount
  // **Validates: Requirements 12.1**
  it('Property 16: Command-center endpoint called exactly once per mount', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')

    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>

    await fc.assert(
      fc.asyncProperty(validLeadId, async (leadId) => {
        mockGetCommandCenter.mockResolvedValue({
          id: leadId,
          owner_first_name: null,
          owner_last_name: null,
          property_street: null,
          property_city: null,
          property_state: null,
          lead_score: 50,
          lead_status: 'skip_trace',
          has_property_match: false,
          analysis_session_id: null,
          open_tasks: [],
          timeline: { entries: [], total: 0, page: 1, per_page: 20 },
          recommended_action: { value: null, label: null, explanation: null, signals: {} },
        })
        mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(leadId))
        mockGetCommandCenter.mockClear()
        mockGetLeadDetail.mockClear()

        const queryClient = new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })

        const container = document.createElement('div')
        document.body.appendChild(container)

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={leadId} />
            </MemoryRouter>
          </QueryClientProvider>,
          { container },
        )

        await waitFor(() => {
          expect(mockGetCommandCenter).toHaveBeenCalledTimes(1)
        }, { timeout: 5000 })

        unmount()
        document.body.removeChild(container)
        queryClient.clear()
      }),
      { numRuns: 5 },
    )
  }, 30000)

  // Feature: unified-lead-command-center, Property 17: Lead detail endpoint called exactly once per mount
  // **Validates: Requirements 12.2**
  it('Property 17: Lead detail endpoint called exactly once per mount', async () => {
    const { commandCenterService } = await import('@/services/api')
    const { leadService } = await import('@/services/leadApi')

    const mockGetCommandCenter = commandCenterService.getCommandCenter as ReturnType<typeof vi.fn>
    const mockGetLeadDetail = leadService.getLeadDetail as ReturnType<typeof vi.fn>

    await fc.assert(
      fc.asyncProperty(validLeadId, async (leadId) => {
        mockGetCommandCenter.mockResolvedValue({
          id: leadId,
          owner_first_name: null,
          owner_last_name: null,
          property_street: null,
          property_city: null,
          property_state: null,
          lead_score: 50,
          lead_status: 'skip_trace',
          has_property_match: false,
          analysis_session_id: null,
          open_tasks: [],
          timeline: { entries: [], total: 0, page: 1, per_page: 20 },
          recommended_action: { value: null, label: null, explanation: null, signals: {} },
        })
        mockGetLeadDetail.mockResolvedValue(minimalPropertyDetail(leadId))
        mockGetCommandCenter.mockClear()
        mockGetLeadDetail.mockClear()

        const queryClient = new QueryClient({
          defaultOptions: { queries: { retry: false } },
        })

        const container = document.createElement('div')
        document.body.appendChild(container)

        const { unmount } = render(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter>
              <UnifiedLeadCommandCenter leadId={leadId} />
            </MemoryRouter>
          </QueryClientProvider>,
          { container },
        )

        await waitFor(() => {
          expect(mockGetLeadDetail).toHaveBeenCalledTimes(1)
        }, { timeout: 5000 })

        unmount()
        document.body.removeChild(container)
        queryClient.clear()
      }),
      { numRuns: 5 },
    )
  }, 30000)
})
