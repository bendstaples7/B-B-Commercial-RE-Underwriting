/**
 * Tests for HubSpotLeadViews components
 *
 * Covers:
 * - Previously Warm Leads view calls getPreviouslyWarmLeads and renders lead list
 * - Needs Review view renders ReviewQueue (which calls hubSpotService.getReviewQueue)
 * - Follow-Up Overdue view calls getFollowUpOverdueLeads
 * - No Current Next Action view calls getNoNextActionLeads
 * - Do Not Contact view calls getDoNotContactLeads
 * - Missing Property Match view calls getMissingPropertyMatchLeads
 * - each view renders with correct page title/label
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import {
  PreviouslyWarmLeadsView,
  NeedsReviewView,
  FollowUpOverdueView,
  NoNextActionView,
  DoNotContactView,
  MissingPropertyMatchView,
} from './HubSpotLeadViews'
import { leadViewService, hubSpotService } from '@/services/api'
import type { PropertySummary } from '@/types'

// ---------------------------------------------------------------------------
// Mock the API services
// ---------------------------------------------------------------------------

vi.mock('@/services/api', () => ({
  leadViewService: {
    getPreviouslyWarmLeads: vi.fn(),
    getNeedsReviewLeads: vi.fn(),
    getFollowUpOverdueLeads: vi.fn(),
    getNoNextActionLeads: vi.fn(),
    getDoNotContactLeads: vi.fn(),
    getMissingPropertyMatchLeads: vi.fn(),
  },
  hubSpotService: {
    getHubSpotConfig: vi.fn(),
    saveHubSpotConfig: vi.fn(),
    testHubSpotConnection: vi.fn(),
    triggerHubSpotImport: vi.fn(),
    listImportRuns: vi.fn(),
    getImportRun: vi.fn(),
    getReviewQueue: vi.fn(),
    confirmMatch: vi.fn(),
    rejectMatch: vi.fn(),
    markMatchAsNewRecord: vi.fn(),
    triggerBackupExport: vi.fn(),
    downloadBackupExport: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const mockLeads: PropertySummary[] = [
  {
    id: 1,
    property_street: '123 Main St',
    property_city: 'Chicago',
    property_state: 'IL',
    property_zip: '60601',
    property_type: 'multi_family',
    bedrooms: 4,
    bathrooms: 2,
    square_footage: 2000,
    lot_size: 5000,
    year_built: 1950,
    units: 2,
    units_allowed: null,
    zoning: 'R-2',
    county_assessor_pin: '12-34-567-001',
    tax_bill_2021: null,
    most_recent_sale: null,
    owner_first_name: 'John',
    owner_last_name: 'Smith',
    owner_2_first_name: null,
    owner_2_last_name: null,
    ownership_type: null,
    acquisition_date: null,
    phone_1: '555-1234',
    phone_2: null,
    phone_3: null,
    phone_4: null,
    phone_5: null,
    phone_6: null,
    phone_7: null,
    email_1: 'john@example.com',
    email_2: null,
    email_3: null,
    email_4: null,
    email_5: null,
    socials: null,
    mailing_address: null,
    mailing_city: null,
    mailing_state: null,
    mailing_zip: null,
    address_2: null,
    returned_addresses: null,
    lead_score: 75,
    lead_category: 'residential',
    data_source: 'hubspot_import',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    source: 'hubspot_import',
    date_identified: null,
    notes: null,
    needs_skip_trace: false,
    skip_tracer: null,
    date_skip_traced: null,
    date_added_to_hubspot: null,
    up_next_to_mail: false,
    mailer_history: null,
  },
  {
    id: 2,
    property_street: '456 Oak Ave',
    property_city: 'Chicago',
    property_state: 'IL',
    property_zip: '60602',
    property_type: 'single_family',
    bedrooms: 3,
    bathrooms: 1,
    square_footage: 1500,
    lot_size: 4000,
    year_built: 1960,
    units: 1,
    units_allowed: null,
    zoning: 'R-1',
    county_assessor_pin: '12-34-567-002',
    tax_bill_2021: null,
    most_recent_sale: null,
    owner_first_name: 'Jane',
    owner_last_name: 'Doe',
    owner_2_first_name: null,
    owner_2_last_name: null,
    ownership_type: null,
    acquisition_date: null,
    phone_1: '555-5678',
    phone_2: null,
    phone_3: null,
    phone_4: null,
    phone_5: null,
    phone_6: null,
    phone_7: null,
    email_1: null,
    email_2: null,
    email_3: null,
    email_4: null,
    email_5: null,
    socials: null,
    mailing_address: null,
    mailing_city: null,
    mailing_state: null,
    mailing_zip: null,
    address_2: null,
    returned_addresses: null,
    lead_score: 45,
    lead_category: 'residential',
    data_source: 'hubspot_import',
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
    source: 'hubspot_import',
    date_identified: null,
    notes: null,
    needs_skip_trace: false,
    skip_tracer: null,
    date_skip_traced: null,
    date_added_to_hubspot: null,
    up_next_to_mail: false,
    mailer_history: null,
  },
]

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PreviouslyWarmLeadsView', () => {
  it('calls getPreviouslyWarmLeads on mount', async () => {
    vi.mocked(leadViewService.getPreviouslyWarmLeads).mockResolvedValue(mockLeads)

    render(<PreviouslyWarmLeadsView />)

    await waitFor(() => {
      expect(leadViewService.getPreviouslyWarmLeads).toHaveBeenCalledOnce()
    })
  })

  it('renders the correct page title', async () => {
    vi.mocked(leadViewService.getPreviouslyWarmLeads).mockResolvedValue(mockLeads)

    render(<PreviouslyWarmLeadsView />)

    await waitFor(() => {
      expect(screen.getByText('Previously Warm Properties')).toBeInTheDocument()
    })
  })

  it('renders the lead list with property streets', async () => {
    vi.mocked(leadViewService.getPreviouslyWarmLeads).mockResolvedValue(mockLeads)

    render(<PreviouslyWarmLeadsView />)

    await waitFor(() => {
      expect(screen.getByText('123 Main St')).toBeInTheDocument()
      expect(screen.getByText('456 Oak Ave')).toBeInTheDocument()
    })
  })

  it('shows "No leads found" when list is empty', async () => {
    vi.mocked(leadViewService.getPreviouslyWarmLeads).mockResolvedValue([])

    render(<PreviouslyWarmLeadsView />)

    await waitFor(() => {
      expect(screen.getByText('No properties found.')).toBeInTheDocument()
    })
  })
})

describe('NeedsReviewView', () => {
  it('calls getReviewQueue on mount (via ReviewQueue component)', async () => {
    vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
      matches: [],
      total: 0,
      page: 1,
      per_page: 20,
    })

    render(<NeedsReviewView />)

    await waitFor(() => {
      expect(hubSpotService.getReviewQueue).toHaveBeenCalled()
    })
  })

  it('renders the Review Queue heading', async () => {
    vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
      matches: [],
      total: 0,
      page: 1,
      per_page: 20,
    })

    render(<NeedsReviewView />)

    await waitFor(() => {
      expect(screen.getByText('Review Queue')).toBeInTheDocument()
    })
  })

  it('renders empty queue message when no matches', async () => {
    vi.mocked(hubSpotService.getReviewQueue).mockResolvedValue({
      matches: [],
      total: 0,
      page: 1,
      per_page: 20,
    })

    render(<NeedsReviewView />)

    await waitFor(() => {
      expect(
        screen.getByText(/No items in the review queue matching the current filters/)
      ).toBeInTheDocument()
    })
  })
})

describe('FollowUpOverdueView', () => {
  it('calls getFollowUpOverdueLeads on mount', async () => {
    vi.mocked(leadViewService.getFollowUpOverdueLeads).mockResolvedValue(mockLeads)

    render(<FollowUpOverdueView />)

    await waitFor(() => {
      expect(leadViewService.getFollowUpOverdueLeads).toHaveBeenCalledOnce()
    })
  })

  it('renders the correct page title', async () => {
    vi.mocked(leadViewService.getFollowUpOverdueLeads).mockResolvedValue(mockLeads)

    render(<FollowUpOverdueView />)

    await waitFor(() => {
      expect(screen.getByText('Follow-Up Overdue')).toBeInTheDocument()
    })
  })

  it('renders lead scores', async () => {
    vi.mocked(leadViewService.getFollowUpOverdueLeads).mockResolvedValue(mockLeads)

    render(<FollowUpOverdueView />)

    await waitFor(() => {
      expect(screen.getByText('75')).toBeInTheDocument()
      expect(screen.getByText('45')).toBeInTheDocument()
    })
  })
})

describe('NoNextActionView', () => {
  it('calls getNoNextActionLeads on mount', async () => {
    vi.mocked(leadViewService.getNoNextActionLeads).mockResolvedValue(mockLeads)

    render(<NoNextActionView />)

    await waitFor(() => {
      expect(leadViewService.getNoNextActionLeads).toHaveBeenCalledOnce()
    })
  })

  it('renders the correct page title', async () => {
    vi.mocked(leadViewService.getNoNextActionLeads).mockResolvedValue(mockLeads)

    render(<NoNextActionView />)

    await waitFor(() => {
      expect(screen.getByText('No Current Next Action')).toBeInTheDocument()
    })
  })
})

describe('DoNotContactView', () => {
  it('calls getDoNotContactLeads on mount', async () => {
    vi.mocked(leadViewService.getDoNotContactLeads).mockResolvedValue(mockLeads)

    render(<DoNotContactView />)

    await waitFor(() => {
      expect(leadViewService.getDoNotContactLeads).toHaveBeenCalledOnce()
    })
  })

  it('renders the correct page title', async () => {
    vi.mocked(leadViewService.getDoNotContactLeads).mockResolvedValue(mockLeads)

    render(<DoNotContactView />)

    await waitFor(() => {
      expect(screen.getByText('Do Not Contact')).toBeInTheDocument()
    })
  })

  it('shows error when API call fails', async () => {
    vi.mocked(leadViewService.getDoNotContactLeads).mockRejectedValue(
      new Error('Failed to load leads')
    )

    render(<DoNotContactView />)

    await waitFor(() => {
      expect(screen.getByText('Failed to load leads')).toBeInTheDocument()
    })
  })
})

describe('MissingPropertyMatchView', () => {
  it('calls getMissingPropertyMatchLeads on mount', async () => {
    vi.mocked(leadViewService.getMissingPropertyMatchLeads).mockResolvedValue(mockLeads)

    render(<MissingPropertyMatchView />)

    await waitFor(() => {
      expect(leadViewService.getMissingPropertyMatchLeads).toHaveBeenCalledOnce()
    })
  })

  it('renders the correct page title', async () => {
    vi.mocked(leadViewService.getMissingPropertyMatchLeads).mockResolvedValue(mockLeads)

    render(<MissingPropertyMatchView />)

    await waitFor(() => {
      expect(screen.getByText('Missing Property Match')).toBeInTheDocument()
    })
  })

  it('renders lead list with owner names', async () => {
    vi.mocked(leadViewService.getMissingPropertyMatchLeads).mockResolvedValue(mockLeads)

    render(<MissingPropertyMatchView />)

    await waitFor(() => {
      expect(screen.getByText('Smith')).toBeInTheDocument()
      expect(screen.getByText('Doe')).toBeInTheDocument()
    })
  })
})
