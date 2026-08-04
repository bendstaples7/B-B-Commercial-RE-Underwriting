/**
 * Unit tests for UnifiedLeadCommandCenter
 *
 * Covers:
 * - Structural presence: sticky header, tab panel with six tabs in order,
 *   property sidebar, activity panel, tasks panel
 * - Error state for invalid ID renders data-testid="invalid-id-error"
 * - Back button calls navigate(-1)
 * - Sidebar is hidden below lg breakpoint via sx display prop
 *
 * Requirements: 5.1, 5.4, 5.5, 5.6, 5.7, 10.1, 10.2, 11.5
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import { MemoryRouter, Route, Routes, useParams } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { UnifiedLeadCommandCenter } from './UnifiedLeadCommandCenter'
import { QUEUE_ADVANCE_HOLD_MS } from '@/components/lead-detail/QueueAdvanceHoldBanner'
import type { CommandCenterPayload, PropertyDetail } from '@/types'
import { callLogService } from '@/services/api'

// ---------------------------------------------------------------------------
// Mock all services used by UnifiedLeadCommandCenter and its children
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  commandCenterService: {
    getCommandCenter: vi.fn(),
    updateStatus: vi.fn(),
    moveToSkipTrace: vi.fn(),
    getTimeline: vi.fn(),
  },
  leadTaskService: {
    createTask: vi.fn(),
    completeTask: vi.fn(),
    snoozeTask: vi.fn(),
    updateTask: vi.fn(),
  },
  callLogService: {
    logNote: vi.fn(),
    logCall: vi.fn(),
  },
  leadScoreService: {
    getLeadScore: vi.fn().mockResolvedValue({ data: { latest: null, history: [] } }),
  },
  multifamilyService: {
    createDeal: vi.fn(),
    linkDealToLead: vi.fn(),
  },
  contactService: {
    listContacts: vi.fn().mockResolvedValue([]),
    createContact: vi.fn(),
    updateContact: vi.fn(),
    deleteContact: vi.fn(),
  },
  queueService: {
    getNavigation: vi.fn(),
  },
}))

vi.mock('@/services/leadApi', () => ({
  leadService: {
    getLeadDetail: vi.fn(),
    analyzeLead: vi.fn(),
  },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {
    enqueue: vi.fn(),
  },
}))

// Mock useNavigate so we can spy on it
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

// ---------------------------------------------------------------------------
// Test data factories
// ---------------------------------------------------------------------------

function makeCommandCenterPayload(
  overrides: Partial<CommandCenterPayload> = {}
): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: 'Jane',
    owner_last_name: 'Doe',
    property_street: '456 Oak Ave',
    property_city: 'Naperville',
    property_state: 'IL',
    property_zip: '60540',
    lead_score: 82,
    lead_status: 'mailing_no_contact_made',
    has_property_match: false,
    analysis_session_id: null,
    recommended_action: {
      value: 'ready_for_outreach',
      label: 'Ready for Outreach',
      explanation: 'No contact made yet.',
      signals: {},
    },
    open_tasks: [],
    timeline: {
      entries: [],
      total: 0,
      page: 1,
      per_page: 20,
    },
    ...overrides,
  }
}

function makePropertyDetail(overrides: Partial<PropertyDetail> = {}): PropertyDetail {
  return {
    id: 1,
    property_street: '456 Oak Ave',
    property_city: 'Naperville',
    property_state: 'IL',
    property_zip: '60540',
    property_type: null,
    bedrooms: null,
    bathrooms: null,
    square_footage: null,
    lot_size: null,
    year_built: null,
    owner_first_name: 'Jane',
    owner_last_name: 'Doe',
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
    lead_score: 82,
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
    source_type: null,
    tax_distress_data: null,
    manual_priority: null,
    enrichment_records: [],
    marketing_lists: [],
    analysis_session: null,
    contacts: [],
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

let commandCenterService: typeof import('@/services/api')['commandCenterService']
let leadService: typeof import('@/services/leadApi')['leadService']

beforeEach(async () => {
  vi.clearAllMocks()
  mockNavigate.mockClear()

  const api = await import('@/services/api')
  commandCenterService = api.commandCenterService

  const leadApi = await import('@/services/leadApi')
  leadService = leadApi.leadService

  vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(makeCommandCenterPayload())
  vi.mocked(leadService.getLeadDetail).mockResolvedValue(makePropertyDetail())
})

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------

function renderComponent(leadId = 1) {
  return render(
    <MemoryRouter>
      <UnifiedLeadCommandCenter leadId={leadId} />
    </MemoryRouter>
  )
}

/**
 * Renders the App.tsx route wrapper (UnifiedLeadCommandCenterRoute) so we can
 * test the invalid-ID error path.  We inline a minimal version of the route
 * guard here to avoid importing all of App.tsx (which has many side effects).
 */
function InvalidLeadIdErrorInline() {
  return (
    <div data-testid="invalid-id-error">
      <span>Invalid lead ID</span>
    </div>
  )
}

function UnifiedLeadCommandCenterRouteLocal({ id }: { id: string }) {
  const numericId = Number(id)
  if (!id || !Number.isInteger(numericId) || numericId <= 0) {
    return <InvalidLeadIdErrorInline />
  }
  return <UnifiedLeadCommandCenter leadId={numericId} />
}

function renderWithRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/leads/:id"
          element={
            // Extract :id and delegate to our local route wrapper
            <RouteParamExtractor />
          }
        />
      </Routes>
    </MemoryRouter>
  )
}

function RouteParamExtractor() {
  // We can't use useParams directly in a helper outside the component tree,
  // so we use a wrapper component instead.
  const { id } = useParams<{ id: string }>()
  return <UnifiedLeadCommandCenterRouteLocal id={id ?? ''} />
}

// ---------------------------------------------------------------------------
// 1. Structural presence
// ---------------------------------------------------------------------------

describe('UnifiedLeadCommandCenter — structural presence', () => {
  it('renders the back button in the sticky header', async () => {
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('back-button')).toBeInTheDocument()
    })
  })

  it('renders the tab panel', async () => {
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('tab-panel')).toBeInTheDocument()
    })
  })

  it('renders all six tabs in order: Info, Score, Enrichment, Marketing, Analysis, Contacts', async () => {
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('tab-panel')).toBeInTheDocument()
    })

    const tabPanel = screen.getByTestId('tab-panel')
    const tabs = tabPanel.querySelectorAll('[role="tab"]')

    expect(tabs).toHaveLength(6)
    expect(tabs[0]).toHaveTextContent('Info')
    expect(tabs[1]).toHaveTextContent('Score')
    expect(tabs[2]).toHaveTextContent('Enrichment')
    expect(tabs[3]).toHaveTextContent('Marketing')
    expect(tabs[4]).toHaveTextContent('Analysis')
    expect(tabs[5]).toHaveTextContent('Contacts')
  })

  it('renders the property sidebar (mobile accordion below lg)', async () => {
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('property-sidebar-mobile')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('property-sidebar')).not.toBeInTheDocument()
  })

  it('renders Key Contact, Action Center tiles, and Deep Dive Details', async () => {
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('key-contact-card')).toBeInTheDocument()
    })
    expect(screen.getByTestId('action-center-tiles')).toBeInTheDocument()
    expect(screen.getByTestId('deep-dive-details')).toBeInTheDocument()
    expect(screen.getByTestId('property-kpi-card')).toBeInTheDocument()
    expect(screen.getByTestId('lead-briefing-ai-badge')).toBeInTheDocument()
  })

  it('renders work-queue membership chips without alert banners', async () => {
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        work_queues: [
          { key: 'needs-review', label: 'Needs Review', path: '/queues/needs-review' },
          { key: 'follow-up-overdue', label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue' },
          { key: 'previously-warm', label: 'Previously Warm', path: '/queues/previously-warm' },
        ],
        review_reason: 'Manual review needed',
      }),
    )

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('work-queue-membership-strip')).toBeInTheDocument()
    })
    expect(screen.getByTestId('work-queue-strip-needs-review')).toBeInTheDocument()
    expect(screen.getByTestId('work-queue-strip-follow-up-overdue')).toBeInTheDocument()
    expect(screen.getByTestId('work-queue-strip-previously-warm')).toBeInTheDocument()
    expect(screen.queryByTestId('work-queue-banner-needs-review')).not.toBeInTheDocument()
    expect(screen.queryByTestId('work-queue-banner-follow-up-overdue')).not.toBeInTheDocument()
  })

  it('shows a tight Property Overview header with address, owner link, status, quick stats, and score panel', async () => {
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        units: 3,
        property_type: 'triplex',
        assessed_value: 520000,
        most_recent_sale_price: 310000,
        most_recent_sale_display: '1993-04-15',
        county_assessor_pin: '14211234560000',
        lead_score: 87,
      }),
    )
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('property-overview-address')).toBeInTheDocument()
    })
    expect(screen.getByTestId('property-overview-address')).toHaveTextContent('456 Oak Ave, Naperville, IL 60540')
    expect(screen.getByTestId('property-overview-owner-link')).toHaveTextContent('Jane Doe')
    expect(screen.getByTestId('property-overview-pin')).toHaveTextContent(/Parcel ID \/ PIN/)
    expect(screen.getByTestId('property-overview-badges')).toBeInTheDocument()
    expect(screen.queryByTestId('property-overview-units-chip')).not.toBeInTheDocument()
    expect(screen.queryByTestId('property-type-chip')).not.toBeInTheDocument()
    expect(screen.getByTestId('property-overview-quick-stats')).toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-est-value')).toHaveTextContent('$520,000')
    expect(screen.queryByTestId('quick-stat-est-rent')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-last-sale')).toHaveTextContent('$310,000')
    expect(screen.getByTestId('quick-stat-last-sale')).toHaveTextContent(/1993|04/)
    expect(screen.getByTestId('quick-stat-units-details')).toHaveTextContent(/3 Units/)
    expect(screen.getByTestId('header-lead-score')).toBeInTheDocument()
    expect(screen.getByTestId('header-lead-score')).toHaveTextContent('87')
  })

  it('focuses Key Contact from the owner link', async () => {
    const user = userEvent.setup()
    const scrollIntoView = vi.fn()
    const originalScroll = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = scrollIntoView as typeof Element.prototype.scrollIntoView
    try {
      vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
        makeCommandCenterPayload({ units: 2 }),
      )
      renderComponent()
      await waitFor(() => {
        expect(screen.getByTestId('property-overview-owner-link')).toBeInTheDocument()
      })
      await waitFor(() => {
        expect(screen.getByTestId('key-contact-card')).toBeInTheDocument()
      })
      await user.click(screen.getByTestId('property-overview-owner-link'))
      expect(scrollIntoView).toHaveBeenCalled()
      expect(screen.getByTestId('key-contact-card')).toHaveFocus()
    } finally {
      Element.prototype.scrollIntoView = originalScroll
    }
  })

  it('shows PIN as dash when missing and keeps units only in quick stats', async () => {
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        county_assessor_pin: null,
        units: null,
        property_type: 'duplex',
      }),
    )
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('property-overview-address')).toBeInTheDocument()
    })
    expect(screen.getByTestId('property-overview-pin')).toHaveTextContent(/Parcel ID \/ PIN: —/)
    expect(screen.getByTestId('property-overview-look-up-pin')).toBeInTheDocument()
    expect(screen.getByTestId('property-overview-enter-pin')).toBeInTheDocument()
    expect(screen.queryByTestId('property-overview-units-chip')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-units-details')).toHaveTextContent(/Duplex/)
  })

  it('shows Also known as when assessor AKA differs from lead street', async () => {
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        property_street: '3715-3721 N Leavitt St',
        county_assessor_pin: '14-19-122-001-0000',
        assessor_aka_street: '2155 W Bradley Pl',
      }),
    )
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('property-overview-aka')).toBeInTheDocument()
    })
    expect(screen.getByTestId('property-overview-aka')).toHaveTextContent(
      /Also known as:\s*2155 W Bradley Pl/,
    )
  })

  it('auto-previews Cook missing PIN and shows tax-situs AKA banner', async () => {
    const { propertyMatchService } = await import('@/services/propertyMatchApi')
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        property_street: '3715-3721 N Leavitt St',
        property_city: 'Chicago',
        property_state: 'IL',
        property_zip: '60618',
        county_assessor_pin: null,
        is_cook_county_eligible: true,
      }),
    )
    vi.spyOn(propertyMatchService, 'preview').mockResolvedValue({
      found: true,
      pin: null,
      pin_count: 4,
      require_explicit_apply: true,
      tax_situs_street: '2155 W BRADLEY PL',
      tax_situs_pin_count: 4,
      assessor_aka: { property_street: '2155 W BRADLEY PL' },
      candidates: [
        { pin: '14-19-122-001-0000', property_street: '2155 W BRADLEY PL' },
        { pin: '14-19-122-002-0000', property_street: '2153 W BRADLEY PL' },
        { pin: '14-19-122-003-0000', property_street: '2151 W BRADLEY PL' },
        { pin: '14-19-122-004-0000', property_street: '2149 W BRADLEY PL' },
      ],
    } as never)

    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('property-overview-pin-lookup-aka-banner')).toBeInTheDocument()
    })
    expect(screen.getByTestId('property-overview-pin-lookup-aka-banner')).toHaveTextContent(
      /Also known as \(tax situs\).*Bradley/i,
    )
    expect(screen.getByTestId('property-overview-analyze-tax-situs')).toBeInTheDocument()
    expect(screen.getByTestId('property-overview-apply-closest-pin')).toBeInTheDocument()
    expect(screen.getByTestId('property-overview-pin-deprioritize-cta')).toBeInTheDocument()
    expect(screen.getByTestId('property-overview-deprioritize-multi-pin')).toHaveTextContent(
      /Deprioritize — likely condos/i,
    )
  })

  it('renders the activity panel', async () => {
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('activity-panel')).toBeInTheDocument()
    })
  })

  it('opens activity in a full-screen dialog from the Activity header', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('activity-fullscreen-btn')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('activity-fullscreen-btn'))
    expect(screen.getByTestId('activity-fullscreen-dialog')).toBeInTheDocument()
    expect(screen.getByTestId('activity-fullscreen-dialog')).toHaveTextContent('Activity')
    await user.click(screen.getByTestId('activity-fullscreen-close'))
    await waitFor(() => {
      expect(screen.queryByTestId('activity-fullscreen-dialog')).not.toBeInTheDocument()
    })
  })

  it('renders the tasks panel', async () => {
    renderComponent()
    await waitFor(() => {
      expect(screen.getByTestId('tasks-panel')).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// 2. Tab deep-linking via ?tab= query param
// ---------------------------------------------------------------------------

function renderComponentAtSearch(search: string, leadId = 1) {
  return render(
    <MemoryRouter initialEntries={[`/leads/${leadId}${search}`]}>
      <UnifiedLeadCommandCenter leadId={leadId} />
    </MemoryRouter>
  )
}

describe('UnifiedLeadCommandCenter — tab deep-linking', () => {
  async function getTabs() {
    await waitFor(() => {
      expect(screen.getByTestId('tab-panel')).toBeInTheDocument()
    })
    return screen.getByTestId('tab-panel').querySelectorAll('[role="tab"]')
  }

  it('selects the Analysis tab when ?tab=analysis is present', async () => {
    renderComponentAtSearch('?tab=analysis')
    const tabs = await getTabs()
    expect(tabs[4]).toHaveAttribute('aria-selected', 'true')
  })

  it('selects the Score tab when ?tab=score is present', async () => {
    renderComponentAtSearch('?tab=score')
    const tabs = await getTabs()
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true')
  })

  it('defaults to the Info tab when no tab param is present', async () => {
    renderComponentAtSearch('')
    const tabs = await getTabs()
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
  })

  it('falls back to the Info tab for an unknown tab param such as timeline', async () => {
    // The activity timeline is not a tab (it lives in the always-visible
    // ActivityPanel), so ?tab=timeline falls back to the default Info tab.
    renderComponentAtSearch('?tab=timeline')
    const tabs = await getTabs()
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
  })
})

// ---------------------------------------------------------------------------
// 2b. Timeline deep-link scrolls the always-visible ActivityPanel into view
// ---------------------------------------------------------------------------

describe('UnifiedLeadCommandCenter — ?tab=timeline scrolls ActivityPanel into view', () => {
  it('selects the Analysis tab (no scroll) when ?tab=analysis is present', async () => {
    // jsdom does not implement scrollIntoView — stub it so we can assert it is
    // NOT triggered by a plain tab deep-link.
    const scrollIntoViewMock = vi.fn()
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = scrollIntoViewMock as typeof Element.prototype.scrollIntoView
    try {
      renderComponentAtSearch('?tab=analysis')
      await waitFor(() => {
        expect(screen.getByTestId('tab-panel')).toBeInTheDocument()
      })
      const tabs = screen.getByTestId('tab-panel').querySelectorAll('[role="tab"]')
      expect(tabs[4]).toHaveAttribute('aria-selected', 'true')
      expect(scrollIntoViewMock).not.toHaveBeenCalled()
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })

  it('invokes scrollIntoView on the ActivityPanel when ?tab=timeline is present', async () => {
    const scrollIntoViewMock = vi.fn()
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = scrollIntoViewMock as typeof Element.prototype.scrollIntoView
    try {
      renderComponentAtSearch('?tab=timeline')

      // The panel must render (data loaded) before the scroll effect can fire.
      await waitFor(() => {
        expect(screen.getByTestId('activity-panel')).toBeInTheDocument()
      })
      await waitFor(() => {
        expect(scrollIntoViewMock).toHaveBeenCalled()
      })
      expect(scrollIntoViewMock).toHaveBeenCalledWith(
        expect.objectContaining({ behavior: 'smooth', block: 'start' })
      )
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })
})

// ---------------------------------------------------------------------------
// 2c. Activity logging modals
// ---------------------------------------------------------------------------

const mockLogNote = callLogService.logNote as ReturnType<typeof vi.fn>

describe('UnifiedLeadCommandCenter — activity logging modals', () => {
  beforeEach(() => {
    mockLogNote.mockReset()
  })

  it('opens the log note modal when RA Log Note is clicked without scrolling', async () => {
    const scrollIntoViewMock = vi.fn()
    const original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = scrollIntoViewMock as typeof Element.prototype.scrollIntoView
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    try {
      renderComponent()
      await waitFor(() => {
        expect(screen.getByTestId('action-center-tile-log_note')).toBeInTheDocument()
      })

      await user.click(screen.getByTestId('action-center-tile-log_note'))

      expect(screen.getByTestId('log-activity-modal-note')).toBeInTheDocument()
      expect(scrollIntoViewMock).not.toHaveBeenCalled()
    } finally {
      Element.prototype.scrollIntoView = original
    }
  })

  it('moves the lead and current task to skip trace from quick actions', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const scrollIntoViewMock = vi.fn()
    const originalScrollIntoView = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView =
      scrollIntoViewMock as typeof Element.prototype.scrollIntoView
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_status: 'mailing_no_contact_made',
        recommended_action: {
          value: 'nurture',
          label: 'Nurture',
          explanation: null,
          signals: {},
        },
        open_tasks: [{
          id: 17,
          lead_id: 1,
          task_type: 'custom',
          title: 'Manually skip trace returned letter',
          status: 'open',
          due_date: '2023-01-27',
          created_at: '2023-01-01T00:00:00Z',
          completed_at: null,
          created_by: 'user',
          source: 'native',
        }],
      }),
    )
    vi.mocked(commandCenterService.moveToSkipTrace).mockResolvedValue({
      lead_id: 1,
      lead_status: 'skip_trace',
      completed_task_id: 17,
      skip_trace_task_id: 18,
      changed: true,
      already_done: false,
      reason_code: null,
    })

    try {
      renderComponent()
      await user.click(
        await screen.findByTestId('action-center-tile-move_to_skip_trace'),
      )

      expect(commandCenterService.moveToSkipTrace).toHaveBeenCalledWith(1, 17)
      expect(
        await screen.findByText(
          'Current task completed and lead moved to Skip Trace',
        ),
      ).toBeInTheDocument()
      await waitFor(() => {
        expect(screen.getByTestId('lead-status-selector')).toHaveTextContent('Skip Trace')
        expect(screen.getAllByText('Awaiting skip trace').length).toBeGreaterThan(0)
        expect(
          screen.queryByText('Manually skip trace returned letter'),
        ).not.toBeInTheDocument()
      })
      expect(scrollIntoViewMock).not.toHaveBeenCalled()
    } finally {
      Element.prototype.scrollIntoView = originalScrollIntoView
    }
  })

  it('does not send undated skip-trace handoff task id as complete_task_id', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_status: 'mailing_no_contact_made',
        recommended_action: {
          value: 'nurture',
          label: 'Nurture',
          explanation: null,
          signals: {},
        },
        open_tasks: [{
          id: 99,
          lead_id: 1,
          task_type: 'skip_trace_owner',
          title: 'Awaiting skip trace',
          status: 'open',
          due_date: null,
          created_at: '2023-01-01T00:00:00Z',
          completed_at: null,
          created_by: 'system',
          source: 'native',
        }],
      }),
    )
    vi.mocked(commandCenterService.moveToSkipTrace).mockResolvedValue({
      lead_id: 1,
      lead_status: 'skip_trace',
      completed_task_id: null,
      skip_trace_task_id: 99,
      changed: true,
      already_done: false,
    })

    renderComponent()
    await user.click(
      await screen.findByTestId('action-center-tile-move_to_skip_trace'),
    )

    expect(commandCenterService.moveToSkipTrace).toHaveBeenCalledWith(1, undefined)
  })

  it('completes dated recent-sale verify task when moving to skip trace', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_status: 'mailing_no_contact_made',
        recommended_action: {
          value: 'nurture',
          label: 'Nurture',
          explanation: null,
          signals: {},
        },
        open_tasks: [{
          id: 188,
          lead_id: 1,
          task_type: 'skip_trace_owner',
          title: 'Recent-sale hold ended — verify new owner and contact information',
          status: 'open',
          due_date: '2026-07-17',
          created_at: '2023-01-01T00:00:00Z',
          completed_at: null,
          created_by: 'system',
          source: 'native',
        }],
      }),
    )
    vi.mocked(commandCenterService.moveToSkipTrace).mockResolvedValue({
      lead_id: 1,
      lead_status: 'skip_trace',
      completed_task_id: 188,
      skip_trace_task_id: 189,
      changed: true,
      already_done: false,
    })

    renderComponent()
    await user.click(
      await screen.findByTestId('action-center-tile-move_to_skip_trace'),
    )

    expect(commandCenterService.moveToSkipTrace).toHaveBeenCalledWith(1, 188)
    await waitFor(() => {
      expect(screen.queryByText(/Recent-sale hold ended/i)).not.toBeInTheDocument()
      expect(screen.getAllByText('Awaiting skip trace').length).toBeGreaterThan(0)
    })
  })

  it('shows already-done snackbar when skip-trace pipeline is unchanged', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_status: 'mailing_no_contact_made',
        recommended_action: {
          value: 'nurture',
          label: 'Nurture',
          explanation: null,
          signals: {},
        },
        open_tasks: [],
      }),
    )
    vi.mocked(commandCenterService.moveToSkipTrace).mockResolvedValue({
      lead_id: 1,
      lead_status: 'skip_trace',
      completed_task_id: null,
      skip_trace_task_id: 42,
      changed: false,
      already_done: true,
      reason_code: 'already_skip_trace',
    })

    renderComponent()
    await user.click(
      await screen.findByTestId('action-center-tile-move_to_skip_trace'),
    )

    expect(
      await screen.findByText('Already in Skip Trace pipeline'),
    ).toBeInTheDocument()
  })

  it('shows success snackbar and timeline entry text after saving a note', async () => {
    mockLogNote.mockResolvedValue({
      id: 42,
      lead_id: 1,
      event_type: 'note_added',
      occurred_at: '2024-06-01T12:00:00Z',
      source: 'manual',
      actor: 'user',
      summary: 'Followed up with owner',
      metadata: { body: 'Followed up with owner' },
      hubspot_activity_id: null,
      is_deleted: false,
      created_at: '2024-06-01T12:00:00Z',
    })

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('action-center-tile-log_note')).toBeInTheDocument()
    })

    expect(screen.queryByTestId('activity-log-actions')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('action-center-tile-log_note'))
    await user.type(screen.getByTestId('note-body-input'), 'Followed up with owner')
    await user.click(screen.getByTestId('note-save-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('activity-success-alert')).toHaveTextContent('Note saved.')
    })
    expect(screen.getByTestId('entry-summary-42')).toHaveTextContent('Followed up with owner')
    expect(screen.queryByTestId('log-activity-modal-note')).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// 2d. Score flash + optimistic task/timeline updates after logging a call
//     (user 8A: score + Not Interested during hold; lead 10737: timeline race)
// ---------------------------------------------------------------------------

function makeScoreRecord(overrides: Partial<import('@/types').PropertyScoreRecord> = {}) {
  return {
    id: 1,
    property_id: 1,
    score_version: 'residential_v1_internal_data',
    total_score: 40,
    score_tier: 'C' as const,
    data_quality_score: 80,
    recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
    top_signals: [],
    score_details: {},
    missing_data: [],
    created_at: '2026-07-01T00:00:00Z',
    ...overrides,
  }
}

describe('UnifiedLeadCommandCenter — score flash and optimistic updates after call log', () => {
  it('flashes the score delta and optimistically drops the completed task without waiting for refetch', async () => {
    const api = await import('@/services/api')
    const mockLogCall = api.callLogService.logCall as ReturnType<typeof vi.fn>
    const mockGetScore = api.leadScoreService.getLeadScore as ReturnType<typeof vi.fn>

    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_score: 40,
        open_tasks: [{
          id: 55,
          lead_id: 1,
          task_type: 'call_owner_today',
          title: 'Call owner today',
          status: 'open',
          due_date: null,
          created_at: '2026-01-01T00:00:00Z',
          completed_at: null,
          created_by: 'system',
          source: 'native',
        }],
      }),
    )

    let releaseCcRefetch: (() => void) | undefined
    let ccCallCount = 0
    vi.mocked(commandCenterService.getCommandCenter).mockImplementation(async () => {
      ccCallCount += 1
      if (ccCallCount === 1) {
        return makeCommandCenterPayload({
          lead_score: 40,
          open_tasks: [{
            id: 55,
            lead_id: 1,
            task_type: 'call_owner_today',
            title: 'Call owner today',
            status: 'open',
            due_date: null,
            created_at: '2026-01-01T00:00:00Z',
            completed_at: null,
            created_by: 'system',
            source: 'native',
          }],
        })
      }
      // Refetch triggered by the activity save — held open on purpose so the
      // test can prove the task row disappears *before* this resolves.
      return new Promise((resolve) => {
        releaseCcRefetch = () => resolve(makeCommandCenterPayload({ lead_score: 48, open_tasks: [] }))
      })
    })

    let resolveNextScore: (() => void) | undefined
    let scoreCallCount = 0
    mockGetScore.mockImplementation(async () => {
      scoreCallCount += 1
      if (scoreCallCount === 1) {
        return { data: { latest: makeScoreRecord({ total_score: 40 }), history: [] } }
      }
      return new Promise((resolve) => {
        resolveNextScore = () => resolve({ data: { latest: makeScoreRecord({ total_score: 48 }), history: [] } })
      })
    })

    mockLogCall.mockResolvedValue({
      id: 900,
      lead_id: 1,
      event_type: 'call_logged',
      occurred_at: '2026-07-30T12:00:00Z',
      source: 'manual',
      actor: 'user',
      summary: 'Outbound call: answered',
      metadata: { outcome: 'answered' },
      hubspot_activity_id: null,
      is_deleted: false,
      created_at: '2026-07-30T12:00:00Z',
    })

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('header-lead-score-value')).toHaveTextContent('40')
    })
    expect(screen.getByTestId('task-item-55')).toBeInTheDocument()

    await user.click(await screen.findByTestId('action-center-tile-log_call'))
    await user.click(screen.getByTestId('call-outcome-answered'))
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('activity-success-alert')).toHaveTextContent('Call logged.')
    })

    // Optimistic — the commandCenter refetch above is still pending.
    expect(screen.queryByTestId('task-item-55')).not.toBeInTheDocument()

    // Release the held score + commandCenter refetches and confirm the flash.
    resolveNextScore?.()
    await waitFor(() => {
      expect(screen.getByTestId('header-lead-score-flash')).toHaveTextContent('+8')
    })

    releaseCcRefetch?.()
    await waitFor(() => {
      expect(ccCallCount).toBeGreaterThanOrEqual(2)
    })
  })

  it('flashes "Score unchanged" when the post-call score delta is zero', async () => {
    const api = await import('@/services/api')
    const mockLogCall = api.callLogService.logCall as ReturnType<typeof vi.fn>
    const mockGetScore = api.leadScoreService.getLeadScore as ReturnType<typeof vi.fn>

    let scoreCallCount = 0
    mockGetScore.mockImplementation(async () => {
      scoreCallCount += 1
      return { data: { latest: makeScoreRecord({ total_score: 40 }), history: [] } }
    })

    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({ lead_score: 40, open_tasks: [] }),
    )

    mockLogCall.mockResolvedValue({
      id: 902,
      lead_id: 1,
      event_type: 'call_logged',
      occurred_at: '2026-07-30T12:00:00Z',
      source: 'manual',
      actor: 'user',
      summary: 'Outbound call: no_answer',
      metadata: { outcome: 'no_answer' },
      hubspot_activity_id: null,
      is_deleted: false,
      created_at: '2026-07-30T12:00:00Z',
    })

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('header-lead-score-value')).toHaveTextContent('40')
    })

    await user.click(await screen.findByTestId('action-center-tile-log_call'))
    await user.click(screen.getByTestId('call-outcome-no_answer'))
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('header-lead-score-flash')).toHaveTextContent('Score unchanged')
    })
    expect(scoreCallCount).toBeGreaterThanOrEqual(2)
  })

  it('keeps a logged call at the top of Activity when the refetch briefly omits its id (lead 10737)', async () => {
    const api = await import('@/services/api')
    const mockLogCall = api.callLogService.logCall as ReturnType<typeof vi.fn>

    // Every refetch — including the one `handleActivitySaved` triggers —
    // returns a timeline that never contains the new entry's id, simulating
    // a race where the server read lags behind the write.
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        timeline: { entries: [], total: 0, page: 1, per_page: 20 },
      }),
    )

    mockLogCall.mockResolvedValue({
      id: 901,
      lead_id: 1,
      event_type: 'call_logged',
      occurred_at: '2026-07-30T12:00:00Z',
      source: 'manual',
      actor: 'user',
      summary: 'Outbound call: answered',
      metadata: { outcome: 'answered' },
      hubspot_activity_id: null,
      is_deleted: false,
      created_at: '2026-07-30T12:00:00Z',
    })

    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderComponent()

    await user.click(await screen.findByTestId('action-center-tile-log_call'))
    await user.click(screen.getByTestId('call-outcome-answered'))
    await user.click(screen.getByTestId('call-save-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('activity-success-alert')).toHaveTextContent('Call logged.')
    })
    expect(screen.getByTestId('entry-summary-901')).toBeInTheDocument()

    // Let the (id-omitting) refetch that `handleActivitySaved` triggers
    // actually land — the row must survive the resulting cache sync instead
    // of being dropped because the server payload doesn't contain its id yet.
    await waitFor(() => {
      expect(vi.mocked(commandCenterService.getCommandCenter).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
    expect(screen.getByTestId('entry-summary-901')).toBeInTheDocument()

    // It is the newest (first) row, not merely present somewhere in the feed.
    const timeline = screen.getByTestId('lead-timeline')
    const rows = timeline.querySelectorAll('[data-testid^="entry-summary-"]')
    expect(rows[0]).toHaveAttribute('data-testid', 'entry-summary-901')
  })
})

// ---------------------------------------------------------------------------
// 3. Error state for invalid ID
// ---------------------------------------------------------------------------

describe('UnifiedLeadCommandCenter — invalid ID error state', () => {
  it('renders invalid-id-error for a non-numeric ID string', () => {
    renderWithRoute('/leads/abc')
    expect(screen.getByTestId('invalid-id-error')).toBeInTheDocument()
  })

  it('renders invalid-id-error for ID "0"', () => {
    renderWithRoute('/leads/0')
    expect(screen.getByTestId('invalid-id-error')).toBeInTheDocument()
  })

  it('renders invalid-id-error for a negative ID', () => {
    renderWithRoute('/leads/-5')
    expect(screen.getByTestId('invalid-id-error')).toBeInTheDocument()
  })

  it('renders invalid-id-error for a decimal ID', () => {
    renderWithRoute('/leads/1.5')
    expect(screen.getByTestId('invalid-id-error')).toBeInTheDocument()
  })

  it('does NOT render invalid-id-error for a valid positive integer ID', async () => {
    renderWithRoute('/leads/1')
    // Give the component time to settle
    await waitFor(() => {
      // Either the loading spinner or the back-button should appear,
      // but NOT the invalid-id-error element
      expect(screen.queryByTestId('invalid-id-error')).not.toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// 3. Back button calls navigate(-1)
// ---------------------------------------------------------------------------

describe('UnifiedLeadCommandCenter — back button', () => {
  it('calls navigate(-1) when the back button is clicked', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('back-button')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('back-button'))

    expect(mockNavigate).toHaveBeenCalledWith(-1)
  })
})

// ---------------------------------------------------------------------------
// 4. Contact / secondary surfaces (card redesign)
// ---------------------------------------------------------------------------

describe('UnifiedLeadCommandCenter — contact and secondary surfaces', () => {
  it('shows preferred phone on primary follow-up task while Key Contact stays as directory', async () => {
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        recommended_action: {
          value: 'call_ready',
          recommended_contact_method: 'phone',
          label: 'Call Now',
          explanation: 'Ready for phone outreach.',
          signals: {},
        },
        phones: [{ value: '(630) 202-3839', confidence_score: 80 }],
        open_tasks: [
          {
            id: 99,
            lead_id: 1,
            task_type: 'custom',
            title: 'Follow up with Gilberto Olivares',
            status: 'open',
            due_date: '2026-06-30',
            created_at: '2026-01-01T00:00:00Z',
            completed_at: null,
            created_by: 'HubSpot',
            source: 'hubspot',
          },
        ],
      }),
    )

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('key-contact-card')).toBeInTheDocument()
    })

    expect(screen.getByTestId('key-contact-phone')).toHaveTextContent('(630) 202-3839')
    expect(screen.getByTestId('outreach-contact-inline')).toBeInTheDocument()
    expect(screen.getByTestId('task-item-99')).toHaveTextContent('(630) 202-3839')
    expect(screen.queryByTestId('outreach-contact-callout')).not.toBeInTheDocument()
    expect(screen.getByTestId('recommended-action-panel')).not.toHaveTextContent('(630) 202-3839')
  })

  it('shows missing-phone hint on follow-up task when no number resolves', async () => {
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        recommended_action: {
          value: 'call_ready',
          recommended_contact_method: 'phone',
          label: 'Call Now',
          explanation: 'Ready for phone outreach.',
          signals: {},
        },
        phones: [],
        open_tasks: [
          {
            id: 100,
            lead_id: 1,
            task_type: 'custom',
            title: 'Follow up',
            status: 'open',
            due_date: '2026-06-30',
            created_at: '2026-01-01T00:00:00Z',
            completed_at: null,
            created_by: 'HubSpot',
            source: 'hubspot',
          },
        ],
      }),
    )

    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('key-contact-card')).toBeInTheDocument()
    })

    expect(screen.getByTestId('key-contact-phone-empty')).toBeInTheDocument()
    expect(screen.getByTestId('outreach-contact-missing')).toBeInTheDocument()
    expect(screen.getByTestId('task-item-100')).toHaveTextContent('No phone number on file')
  })

  it('keeps secondary property details reachable in the mobile accordion', async () => {
    renderComponent()

    await waitFor(() => {
      expect(screen.getByTestId('property-sidebar-mobile')).toBeInTheDocument()
    })

    expect(screen.getByTestId('property-sidebar-mobile')).toHaveTextContent('More property details')
  })
})

describe('UnifiedLeadCommandCenter — queue advance', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not auto-advance after status change when lead leaves the queue', async () => {
    const api = await import('@/services/api')
    vi.mocked(api.commandCenterService.updateStatus).mockResolvedValue({
      lead_status: 'do_not_contact',
    } as never)
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: null,
      total: 5,
      prev_id: null,
      next_id: 99,
    })

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('lead-status-selector')).toBeInTheDocument()
    })
    const commandCenterFetchCount =
      vi.mocked(api.commandCenterService.getCommandCenter).mock.calls.length
    mockNavigate.mockClear()

    await userEvent.click(screen.getByTestId('lead-status-selector'))
    await waitFor(() => {
      expect(screen.getByTestId('lead-status-option-do_not_contact')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByTestId('lead-status-option-do_not_contact'))
    await waitFor(() => {
      expect(screen.getByTestId('status-submit-btn')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByTestId('status-submit-btn'))

    await waitFor(() => {
      expect(api.commandCenterService.updateStatus).toHaveBeenCalled()
    })

    // Status PATCH must not trigger Command Center GET: that GET performs
    // HubSpot task reconciliation and previously closed unrelated open tasks.
    expect(api.commandCenterService.getCommandCenter).toHaveBeenCalledTimes(
      commandCenterFetchCount,
    )

    // Previously position===null triggered advance to next_id; status change must stay put.
    await new Promise((r) => setTimeout(r, 50))
    expect(mockNavigate).not.toHaveBeenCalledWith(
      expect.stringContaining('/leads/99'),
      expect.anything(),
    )
  })

  it('advances to the next Today\'s Action lead after Move to Skip Trace', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const api = await import('@/services/api')
    const user = userEvent.setup({
      pointerEventsCheck: 0,
      advanceTimers: vi.advanceTimersByTime,
    })

    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_status: 'mailing_no_contact_made',
        recommended_action: {
          value: 'nurture',
          label: 'Nurture',
          explanation: null,
          signals: {},
        },
        open_tasks: [{
          id: 17,
          lead_id: 1,
          task_type: 'custom',
          title: 'Call owner for mailing address',
          status: 'open',
          due_date: '2026-07-20',
          created_at: '2023-01-01T00:00:00Z',
          completed_at: null,
          created_by: 'user',
          source: 'native',
        }],
      }),
    )
    vi.mocked(api.commandCenterService.moveToSkipTrace).mockResolvedValue({
      lead_id: 1,
      lead_status: 'skip_trace',
      completed_task_id: 17,
      skip_trace_task_id: 18,
      changed: true,
      already_done: false,
      reason_code: null,
      lead_score: 70,
      recommended_action: null,
    })
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: null,
      total: 4,
      prev_id: null,
      next_id: 4405,
    })

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    await user.click(
      await screen.findByTestId('action-center-tile-move_to_skip_trace'),
    )

    await waitFor(() => {
      expect(api.commandCenterService.moveToSkipTrace).toHaveBeenCalledWith(1, 17)
    })
    expect(await screen.findByTestId('queue-advance-hold')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(QUEUE_ADVANCE_HOLD_MS + 50)
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        '/leads/4405?queue=todays-action',
        { state: { fromQueue: { ...fromQueue, visitedHistory: [1], forwardStack: [] } } },
      )
    })
  }, 20000)

  it('does not advance after Move to Skip Trace when already in the pipeline', async () => {
    const api = await import('@/services/api')
    const user = userEvent.setup({ pointerEventsCheck: 0 })

    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_status: 'mailing_no_contact_made',
        recommended_action: {
          value: 'nurture',
          label: 'Nurture',
          explanation: null,
          signals: {},
        },
        open_tasks: [],
      }),
    )
    vi.mocked(api.commandCenterService.moveToSkipTrace).mockResolvedValue({
      lead_id: 1,
      lead_status: 'skip_trace',
      completed_task_id: null,
      skip_trace_task_id: 42,
      changed: false,
      already_done: true,
      reason_code: 'already_skip_trace',
    })
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: 1,
      total: 5,
      prev_id: null,
      next_id: 99,
    })

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    mockNavigate.mockClear()
    await user.click(
      await screen.findByTestId('action-center-tile-move_to_skip_trace'),
    )

    expect(
      await screen.findByText('Already in Skip Trace pipeline'),
    ).toBeInTheDocument()
    expect(api.commandCenterService.moveToSkipTrace).toHaveBeenCalled()
    expect(mockNavigate).not.toHaveBeenCalledWith(
      expect.stringContaining('/leads/99'),
      expect.anything(),
    )
  })

  it('cancels pending queue advance when unmounted', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const api = await import('@/services/api')
    const user = userEvent.setup({
      pointerEventsCheck: 0,
      advanceTimers: vi.advanceTimersByTime,
    })

    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_status: 'mailing_no_contact_made',
        recommended_action: {
          value: 'nurture',
          label: 'Nurture',
          explanation: null,
          signals: {},
        },
        open_tasks: [{
          id: 17,
          lead_id: 1,
          task_type: 'custom',
          title: 'Call owner for mailing address',
          status: 'open',
          due_date: '2026-07-20',
          created_at: '2023-01-01T00:00:00Z',
          completed_at: null,
          created_by: 'user',
          source: 'native',
        }],
      }),
    )
    vi.mocked(api.commandCenterService.moveToSkipTrace).mockResolvedValue({
      lead_id: 1,
      lead_status: 'skip_trace',
      completed_task_id: 17,
      skip_trace_task_id: 18,
      changed: true,
      already_done: false,
      reason_code: null,
      lead_score: 70,
      recommended_action: null,
    })
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: null,
      total: 4,
      prev_id: null,
      next_id: 4405,
    })

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    const { unmount } = render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    await user.click(
      await screen.findByTestId('action-center-tile-move_to_skip_trace'),
    )
    expect(await screen.findByTestId('queue-advance-hold')).toBeInTheDocument()

    mockNavigate.mockClear()
    unmount()
    await vi.advanceTimersByTimeAsync(QUEUE_ADVANCE_HOLD_MS + 100)

    expect(mockNavigate).not.toHaveBeenCalledWith(
      '/leads/4405?queue=todays-action',
      expect.anything(),
    )
  })
})

describe('UnifiedLeadCommandCenter — mail stage advances queue', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('toasts staged confirmation and auto-advances to the next Today’s Action lead', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const openLetterService = (await import('@/services/openLetterApi')).default
    const api = await import('@/services/api')
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

    vi.mocked(openLetterService.enqueue).mockResolvedValue({
      attempt_id: 42,
      added: 1,
      skipped: 0,
      invalid: 0,
      queued_count: 1,
      batch_minimum: 1,
      allow_send_below_minimum: true,
      can_send: true,
      results: [{ lead_id: 1, status: 'queued', owner_name: 'Jane', property_street: '456 Oak Ave' }],
    })
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: 2,
      total: 10,
      prev_id: null,
      next_id: 55,
    })
    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        is_mailable: true,
        mail_eligible: true,
        mail_queue_status: null,
      }),
    )

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('action-center-tile-add_to_mail_batch')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('action-center-tile-add_to_mail_batch'))

    await waitFor(() => {
      expect(openLetterService.enqueue).toHaveBeenCalled()
    })

    expect(screen.queryByText('Direct mail results')).not.toBeInTheDocument()
    expect(screen.queryByTestId('mail-continue-banner')).not.toBeInTheDocument()
    expect(await screen.findByTestId('queue-advance-hold')).toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(QUEUE_ADVANCE_HOLD_MS + 50)
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        '/leads/55?queue=todays-action',
        expect.objectContaining({
          state: expect.objectContaining({
            fromQueue: { ...fromQueue, visitedHistory: [1], forwardStack: [] },
            flashSnackbar: expect.objectContaining({
              linkTo: '/queues/ready-to-mail',
              linkLabel: 'View staged batch',
            }),
          }),
        }),
      )
    })
  }, 20000)

  it('does not auto-advance when queue navigation is still loading', async () => {
    const openLetterService = (await import('@/services/openLetterApi')).default
    const api = await import('@/services/api')

    vi.mocked(openLetterService.enqueue).mockResolvedValue({
      attempt_id: 42,
      added: 1,
      skipped: 0,
      invalid: 0,
      queued_count: 1,
      batch_minimum: 1,
      allow_send_below_minimum: true,
      can_send: true,
      results: [{ lead_id: 1, status: 'queued', owner_name: 'Jane', property_street: '456 Oak Ave' }],
    })
    // Never resolve navigation → isLoading stays true
    vi.mocked(api.queueService.getNavigation).mockImplementation(
      () => new Promise(() => {}),
    )
    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        is_mailable: true,
        mail_eligible: true,
        mail_queue_status: null,
      }),
    )

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('action-center-tile-add_to_mail_batch')).toBeInTheDocument()
    })
    await userEvent.click(screen.getByTestId('action-center-tile-add_to_mail_batch'))
    await waitFor(() => {
      expect(openLetterService.enqueue).toHaveBeenCalled()
    })
    expect(await screen.findByTestId('activity-success-alert')).toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalledWith(
      expect.stringContaining('/leads/'),
      expect.anything(),
    )
  })

  it('exits queue when next_id is null (end of queue)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const openLetterService = (await import('@/services/openLetterApi')).default
    const api = await import('@/services/api')
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

    vi.mocked(openLetterService.enqueue).mockResolvedValue({
      attempt_id: 42,
      added: 1,
      skipped: 0,
      invalid: 0,
      queued_count: 1,
      batch_minimum: 1,
      allow_send_below_minimum: true,
      can_send: true,
      results: [{ lead_id: 1, status: 'queued', owner_name: 'Jane', property_street: '456 Oak Ave' }],
    })
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: 10,
      total: 10,
      prev_id: 99,
      next_id: null,
    })
    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        is_mailable: true,
        mail_eligible: true,
        mail_queue_status: null,
      }),
    )

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('action-center-tile-add_to_mail_batch')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('action-center-tile-add_to_mail_batch'))
    expect(await screen.findByTestId('queue-advance-hold')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(QUEUE_ADVANCE_HOLD_MS + 50)
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        '/queues/todays-action',
        expect.objectContaining({
          state: expect.objectContaining({
            flashSnackbar: expect.objectContaining({
              linkTo: '/queues/ready-to-mail',
            }),
          }),
        }),
      )
    })
  }, 20000)

  it('Pause cancels mail-stage hold and stays on the current lead', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const openLetterService = (await import('@/services/openLetterApi')).default
    const api = await import('@/services/api')
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

    vi.mocked(openLetterService.enqueue).mockResolvedValue({
      attempt_id: 42,
      added: 1,
      skipped: 0,
      invalid: 0,
      queued_count: 1,
      batch_minimum: 1,
      allow_send_below_minimum: true,
      can_send: true,
      results: [{ lead_id: 1, status: 'queued', owner_name: 'Jane', property_street: '456 Oak Ave' }],
    })
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: 2,
      total: 10,
      prev_id: null,
      next_id: 55,
    })
    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        is_mailable: true,
        mail_eligible: true,
        mail_queue_status: null,
      }),
    )

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    await user.click(await screen.findByTestId('action-center-tile-add_to_mail_batch'))
    expect(await screen.findByTestId('queue-advance-hold')).toBeInTheDocument()
    mockNavigate.mockClear()
    await user.click(screen.getByTestId('queue-advance-pause'))
    expect(screen.queryByTestId('queue-advance-hold')).not.toBeInTheDocument()
    expect(screen.getByText('Staying on this lead.')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(QUEUE_ADVANCE_HOLD_MS + 100)
    expect(mockNavigate).not.toHaveBeenCalledWith(
      expect.stringContaining('/leads/55'),
      expect.anything(),
    )
  })
})

describe('UnifiedLeadCommandCenter — deprioritize queue hold', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('holds then advances after Confirm deprioritize from Today\'s Action', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const api = await import('@/services/api')
    const user = userEvent.setup({
      pointerEventsCheck: 0,
      advanceTimers: vi.advanceTimersByTime,
    })

    vi.mocked(api.commandCenterService.getCommandCenter).mockResolvedValue(
      makeCommandCenterPayload({
        lead_category: 'commercial',
        condo_risk_status: 'likely_condo',
        recommended_action: {
          value: 'needs_manual_review',
          label: 'Confirm deprioritize?',
          explanation: 'Multi-PIN tax situs',
          winning_rule: 'likely_condo',
          winning_rule_label: 'Likely condo',
          recommended_contact_method: null,
          outreach_contact: null,
          signals: { confirm_deprioritize: true },
        },
      }),
    )
    vi.mocked(api.commandCenterService.updateStatus).mockResolvedValue({
      lead_status: 'deprioritize',
      lead_score: 40,
      recommended_action: 'suppress',
    } as never)
    vi.mocked(api.queueService.getNavigation).mockResolvedValue({
      queue_key: 'todays-action',
      lead_id: 1,
      position: 1,
      total: 3,
      prev_id: null,
      next_id: 99,
    })

    const fromQueue = { key: 'todays-action', label: "Today's Action" }
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: '/leads/1',
            search: '?queue=todays-action',
            state: { fromQueue },
          },
        ]}
      >
        <UnifiedLeadCommandCenter leadId={1} />
      </MemoryRouter>,
    )

    const tile = await screen.findByTestId('action-center-tile-deprioritize', {}, { timeout: 10000 })
    await user.click(tile)
    const confirm = await screen.findByTestId('deprioritize-confirm', {}, { timeout: 10000 })
    await user.click(confirm)

    await waitFor(() => {
      expect(api.commandCenterService.updateStatus).toHaveBeenCalledWith(
        1,
        'deprioritize',
        expect.any(String),
      )
    }, { timeout: 10000 })
    expect(await screen.findByTestId('queue-advance-hold', {}, { timeout: 10000 })).toBeInTheDocument()
    expect(screen.getByTestId('queue-advance-hold')).toHaveTextContent('Lead deprioritized')

    await vi.advanceTimersByTimeAsync(QUEUE_ADVANCE_HOLD_MS + 50)
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        '/leads/99?queue=todays-action',
        expect.objectContaining({
          state: expect.objectContaining({
            flashSnackbar: expect.objectContaining({
              message: 'Lead deprioritized',
            }),
          }),
        }),
      )
    }, { timeout: 10000 })
  }, 30000)
})

describe('UnifiedLeadCommandCenter — timeline does not bleed across leads', () => {
  it('drops prior lead Activity rows when leadId changes without remounting', async () => {
    const api = await import('@/services/api')
    const leadApi = await import('@/services/leadApi')

    vi.mocked(api.commandCenterService.getCommandCenter).mockImplementation(async (id: number) => {
      if (id === 3415) {
        return makeCommandCenterPayload({
          id: 3415,
          owner_first_name: 'Gilberto',
          owner_last_name: 'Olivares',
          property_street: '2553 N Drake Ave 1',
          timeline: {
            entries: [
              {
                id: 9001,
                lead_id: 3415,
                event_type: 'call_logged',
                occurred_at: '2026-07-14T20:10:50.648867Z',
                source: 'manual',
                actor: 'Ben',
                summary: 'Call with Gilberto Olivares ((630) 202-3839, mobile): voicemail',
                metadata: null,
                hubspot_activity_id: null,
                is_deleted: false,
                created_at: '2026-07-14T20:10:50.648867Z',
              },
            ],
            total: 1,
            page: 1,
            per_page: 25,
          },
        })
      }
      return makeCommandCenterPayload({
        id: 4404,
        owner_first_name: 'Andiamo',
        owner_last_name: null,
        property_street: '4507 N Keystone',
        timeline: {
          entries: [
            {
              id: 161610,
              lead_id: 4404,
              event_type: 'recommended_action_changed',
              occurred_at: '2026-07-07T22:54:46.417209Z',
              source: 'system',
              actor: 'System',
              summary: "Recommended action changed from 'analyze_property' to 'call_ready'.",
              metadata: null,
              hubspot_activity_id: null,
              is_deleted: false,
              created_at: '2026-07-07T22:54:46.417209Z',
            },
          ],
          total: 1,
          page: 1,
          per_page: 25,
        },
      })
    })
    vi.mocked(leadApi.leadService.getLeadDetail).mockImplementation(async (id: number) =>
      makePropertyDetail({
        id,
        owner_first_name: id === 3415 ? 'Gilberto' : 'Andiamo',
        owner_last_name: id === 3415 ? 'Olivares' : null,
        property_street: id === 3415 ? '2553 N Drake Ave 1' : '4507 N Keystone',
      }),
    )

    const { rerender } = render(
      <MemoryRouter>
        <UnifiedLeadCommandCenter leadId={3415} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('lead-timeline')).toHaveTextContent('Gilberto Olivares')
    })

    // Same instance pattern as queue advance (prop change, no remount key).
    rerender(
      <MemoryRouter>
        <UnifiedLeadCommandCenter leadId={4404} />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('lead-timeline')).toHaveTextContent('call_ready')
    })
    expect(screen.getByTestId('lead-timeline')).not.toHaveTextContent('Gilberto Olivares')
  })
})
