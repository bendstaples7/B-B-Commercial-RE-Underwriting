import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import type { CommandCenterPayload } from '@/types'
import { commandCenterService } from '@/services/api'

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    commandCenterService: {
      ...actual.commandCenterService,
      verifySaleDate: vi.fn(),
    },
  }
})

vi.stubGlobal('navigator', {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
})

function renderSidebar(payload: CommandCenterPayload) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PropertySidebar commandCenterData={payload} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function makePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: 'Flat',
    owner_last_name: 'Owner',
    property_street: '123 Test St',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made',
    contacts: [
      {
        id: 10,
        first_name: 'Hilberto',
        last_name: 'Olivier',
        role: 'owner',
        is_primary: true,
        phones: [
          {
            id: 99,
            value: '(630) 202-3839',
            label: 'mobile',
            confidence_score: 80,
            notes: 'CONFIRMED',
          },
        ],
        emails: [],
      },
    ],
    phones: [{ value: '(630) 999-0000', confidence_score: 50 }],
    ...overrides,
  } as CommandCenterPayload
}

describe('PropertySidebar phone confidence', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(commandCenterService.verifySaleDate).mockResolvedValue({
      lead_id: 1,
      queued: false,
      ran_sync: true,
      message: 'Verification checked.',
    })
  })

  it('shows confidence chip from contacts[].phones when contacts exist', () => {
    renderSidebar(makePayload())

    expect(screen.getByTestId('property-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Owner')
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Hilberto Olivier')
    expect(screen.getByTestId('sidebar-phones')).toBeInTheDocument()
    expect(screen.getByTestId('phone-confidence-(630) 202-3839')).toHaveTextContent(
      '80% · CONFIRMED',
    )
    // Top-level phones[] must not be used when contacts exist
    expect(screen.queryByText('(630) 999-0000')).not.toBeInTheDocument()
  })

  it('collapses lower-confidence phones when a high-confidence phone exists', () => {
    renderSidebar(
      makePayload({
        contacts: [
          {
            id: 10,
            first_name: 'Bob',
            last_name: 'Weinstein',
            role: 'owner',
            is_primary: true,
            phones: [
              { id: 1, value: '(847) 707-9193', confidence_score: 90, notes: 'CONFIRMED' },
              { id: 2, value: '(206) 504-9119', confidence_score: 50 },
              { id: 3, value: '(206) 719-9119', confidence_score: 50 },
            ],
            emails: [],
          },
        ],
      }),
    )

    const phonesBlock = screen.getByTestId('sidebar-phones')
    expect(phonesBlock).toHaveTextContent('Phone')
    expect(phonesBlock.querySelectorAll('[data-testid^="phone-confidence-"]')).toHaveLength(3)
    const summary = screen.getByRole('button', { name: 'Other phone numbers (2)' })
    expect(summary).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(summary)
    expect(summary).toHaveAttribute('aria-expanded', 'true')
    // Label appears once for the group, not once per number
    expect(phonesBlock.textContent?.match(/\bPhone\b/g)).toHaveLength(1)
  })

  it('keeps every phone visible when none are high confidence', () => {
    renderSidebar(
      makePayload({
        contacts: [
          {
            id: 10,
            first_name: 'Bob',
            last_name: 'Weinstein',
            role: 'owner',
            is_primary: true,
            phones: [
              { id: 2, value: '(206) 504-9119', confidence_score: 50 },
              { id: 3, value: '(206) 719-9119', confidence_score: 10 },
            ],
            emails: [],
          },
        ],
      }),
    )

    expect(screen.queryByRole('button', { name: /Other phone numbers/i })).not.toBeInTheDocument()
    expect(screen.getByTestId('phone-confidence-(206) 504-9119')).toBeVisible()
    expect(screen.getByTestId('phone-confidence-(206) 719-9119')).toBeVisible()
  })

  it('labels flat owner name as Owner when contacts are empty', () => {
    renderSidebar(
      makePayload({
        contacts: [],
        owner_first_name: 'Joseph',
        owner_last_name: 'Kiferbaum',
      }),
    )

    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Owner')
    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Joseph Kiferbaum')
  })

  it('prefers person Owner, shows Company org, and Also listed for address-like', () => {
    renderSidebar(
      makePayload({
        owner_first_name: 'Joseph',
        owner_last_name: 'Kiferbaum',
        owner_2_first_name: 'Kdg Avondale LLC',
        owner_2_last_name: null,
        organizations: [
          {
            id: 10,
            name: 'Kdg Avondale LLC',
            org_type: 'llc',
            role: 'owner',
            link_id: 1,
          },
        ],
        contacts: [
          {
            id: 1,
            first_name: '3508SACRAMENTO',
            last_name: 'MAYNARD',
            role: 'owner',
            is_primary: true,
            phones: [],
            emails: [],
          },
          {
            id: 2,
            first_name: 'Joseph',
            last_name: 'Kiferbaum',
            role: 'owner',
            is_primary: false,
            phones: [],
            emails: [],
          },
        ],
      }),
    )

    expect(screen.getByTestId('sidebar-owner-name')).toHaveTextContent('Joseph Kiferbaum')
    expect(screen.getByTestId('sidebar-company-name')).toHaveTextContent('Kdg Avondale LLC')
    expect(screen.getByTestId('sidebar-also-listed-name')).toHaveTextContent(
      '3508SACRAMENTO MAYNARD',
    )
  })

  it('shows confidence from top-level phones[] when contacts are empty', () => {
    renderSidebar(
      makePayload({
        contacts: [],
        phones: [{ value: '(630) 430-5720', confidence_score: 90, notes: 'CONFIRMED' }],
      }),
    )

    expect(screen.getByTestId('phone-confidence-(630) 430-5720')).toHaveTextContent(
      '90% · CONFIRMED',
    )
  })

  it('does not render an empty phone group for blank values', () => {
    renderSidebar(
      makePayload({
        contacts: [],
        phones: [{ value: '   ', confidence_score: 50 }],
      }),
    )

    expect(screen.queryByTestId('sidebar-phones')).not.toBeInTheDocument()
  })

  it('shows work queue chips and data quality breakdown', () => {
    renderSidebar(
      makePayload({
        work_queues: [
          { key: 'previously-warm', label: 'Previously Warm', path: '/queues/previously-warm' },
          { key: 'follow-up-overdue', label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue' },
        ],
        data_completeness_score: 72.5,
        data_quality_breakdown: {
          total: 72.5,
          property: 40,
          contact: 32.5,
          best_phone_confidence: 90,
          has_email: true,
          missing: ['pin', 'units'],
        },
      }),
    )

    expect(screen.getByTestId('work-queue-previously-warm')).toHaveTextContent('Previously Warm')
    expect(screen.getByTestId('work-queue-follow-up-overdue')).toHaveTextContent('Follow-Up Overdue')
    expect(screen.getByText('73%')).toBeInTheDocument()
    expect(screen.getByText('90%')).toBeInTheDocument()
    expect(screen.getByTestId('data-quality-missing')).toBeInTheDocument()
  })

  it('shows empty work queue state', () => {
    renderSidebar(makePayload({ work_queues: [] }))
    expect(screen.getByTestId('work-queues-empty')).toHaveTextContent(
      'Not in an active work queue.',
    )
  })

  it('always shows Owner Mailing Address with Not on file when empty', () => {
    renderSidebar(
      makePayload({
        mailing_address: null,
        mailing_city: null,
        mailing_state: null,
        mailing_zip: null,
        recommended_action: {
          value: 'mail_ready',
          recommended_contact_method: 'direct_mail',
          label: 'Mail Ready',
          explanation: null,
          signals: {},
        },
        needs_skip_trace: false,
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByText('Owner Mailing Address')).toBeInTheDocument()
    expect(screen.getByTestId('owner-mailing-empty')).toHaveTextContent('Not on file')
    expect(screen.getByTestId('owner-mailing-missing-for-mail')).toBeInTheDocument()
    expect(screen.getByText('Needed (phone/email)')).toBeInTheDocument()
    expect(screen.getByTestId('skip-trace-needed-caption')).toBeInTheDocument()
  })

  it('treats whitespace-only owner mailing fields as missing for mail recommendations', () => {
    renderSidebar(
      makePayload({
        mailing_address: '   ',
        mailing_city: ' ',
        mailing_state: '\t',
        mailing_zip: '  ',
        recommended_action: {
          value: 'mail_ready',
          recommended_contact_method: 'direct_mail',
          label: 'Mail Ready',
          explanation: null,
          signals: {},
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('owner-mailing-empty')).toHaveTextContent('Not on file')
    expect(screen.getByTestId('owner-mailing-missing-for-mail')).toBeInTheDocument()
  })

  it('omits mail-missing warning when missing address is not recommended for mail', () => {
    renderSidebar(
      makePayload({
        mailing_address: null,
        mailing_city: null,
        mailing_state: null,
        mailing_zip: null,
        recommended_action: {
          value: 'call_ready',
          recommended_contact_method: 'phone',
          label: 'Call Ready',
          explanation: null,
          signals: {},
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('owner-mailing-empty')).toHaveTextContent('Not on file')
    expect(screen.queryByTestId('owner-mailing-missing-for-mail')).not.toBeInTheDocument()
  })

  it('shows owner mailing lines when present and omits mail-missing warning', () => {
    renderSidebar(
      makePayload({
        mailing_address: '100 Main St',
        mailing_city: 'Chicago',
        mailing_state: 'IL',
        mailing_zip: '60618',
        recommended_action: {
          value: 'mail_ready',
          recommended_contact_method: 'direct_mail',
          label: 'Mail Ready',
          explanation: null,
          signals: {},
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByText(/100 Main St/)).toBeInTheDocument()
    expect(screen.queryByTestId('owner-mailing-empty')).not.toBeInTheDocument()
    expect(screen.queryByTestId('owner-mailing-missing-for-mail')).not.toBeInTheDocument()
  })
})

describe('PropertySidebar always-visible sale and PIN', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(commandCenterService.verifySaleDate).mockResolvedValue({
      lead_id: 1,
      queued: false,
      ran_sync: true,
      message: 'Verification checked.',
    })
  })

  it('shows None for missing Most Recent Sale and PIN', () => {
    renderSidebar(
      makePayload({
        county_assessor_pin: null,
        most_recent_sale_display: null,
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-most-recent-sale')).toHaveTextContent('Most Recent Sale')
    expect(screen.getByTestId('sidebar-most-recent-sale')).toHaveTextContent('None')
    expect(screen.getByTestId('sidebar-county-assessor-pin')).toHaveTextContent('PIN')
    expect(screen.getByTestId('sidebar-county-assessor-pin')).toHaveTextContent('None')
  })

  it('shows sale date and PIN when present', () => {
    renderSidebar(
      makePayload({
        county_assessor_pin: '14-21-123-456-0000',
        most_recent_sale_display: '10/21/2015',
        most_recent_sale_price: 250000,
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-most-recent-sale')).toHaveTextContent('10/21/2015')
    expect(screen.getByTestId('sidebar-most-recent-sale')).toHaveTextContent('$250,000')
    expect(screen.getByTestId('sidebar-county-assessor-pin')).toHaveTextContent(
      '14-21-123-456-0000',
    )
  })

  it('offers on-demand verification when sale date is unverified', async () => {
    renderSidebar(
      makePayload({
        id: 643,
        most_recent_sale_display: '06/12/2018',
        sale_date_meta: {
          last_checked_at: null,
          last_updated_at: null,
          source: null,
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByText('Sale date not verified yet')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('sidebar-verify-sale-date'))

    await waitFor(() => {
      expect(commandCenterService.verifySaleDate).toHaveBeenCalledWith(643)
    })
    expect(await screen.findByText('Verification checked.')).toBeInTheDocument()
  })

  it('shows a spinner while sale-date verification is in flight', async () => {
    let resolveVerify: (value: {
      lead_id: number
      queued: boolean
      ran_sync: boolean
      message?: string
    }) => void = () => undefined
    vi.mocked(commandCenterService.verifySaleDate).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveVerify = resolve
        }),
    )

    renderSidebar(
      makePayload({
        id: 643,
        most_recent_sale_display: '06/12/2018',
        sale_date_meta: {
          last_checked_at: null,
          last_updated_at: null,
          source: null,
        },
      } as Partial<CommandCenterPayload>),
    )

    fireEvent.click(screen.getByTestId('sidebar-verify-sale-date'))
    expect(screen.getByTestId('sidebar-sale-verify-spinner')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-verify-sale-date')).toHaveTextContent('Verifying')

    resolveVerify({ lead_id: 643, queued: false, ran_sync: true, message: 'Verification checked.' })
    expect(await screen.findByText('Verification checked.')).toBeInTheDocument()
    expect(screen.queryByTestId('sidebar-sale-verify-spinner')).not.toBeInTheDocument()
  })

  it('shows a checkmark when sale date was verified within the last month', () => {
    const checkedAt = new Date()
    checkedAt.setDate(checkedAt.getDate() - 10)

    renderSidebar(
      makePayload({
        most_recent_sale_display: '06/12/2018',
        sale_date_meta: {
          last_checked_at: checkedAt.toISOString(),
          source: 'Cook County records',
          status: 'ok',
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-sale-verified-check')).toBeInTheDocument()
  })

  it('does not show a checkmark when verification is older than a month', () => {
    const checkedAt = new Date()
    checkedAt.setDate(checkedAt.getDate() - 45)

    renderSidebar(
      makePayload({
        most_recent_sale_display: '06/12/2018',
        sale_date_meta: {
          last_checked_at: checkedAt.toISOString(),
          source: 'Cook County records',
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.queryByTestId('sidebar-sale-verified-check')).not.toBeInTheDocument()
  })

  it('surfaces skip reason instead of checked when enrichment is skipped', async () => {
    vi.mocked(commandCenterService.verifySaleDate).mockResolvedValue({
      lead_id: 99,
      queued: false,
      ran_sync: true,
      message: 'Not eligible for Cook County enrichment.',
      summary: { skipped: true, skip_reason: 'not_eligible' },
    })

    renderSidebar(
      makePayload({
        id: 99,
        most_recent_sale_display: '06/12/2018',
        sale_date_meta: {
          last_checked_at: null,
          last_updated_at: null,
          source: null,
        },
      } as Partial<CommandCenterPayload>),
    )

    fireEvent.click(screen.getByTestId('sidebar-verify-sale-date'))
    expect(
      await screen.findByText('Not eligible for Cook County enrichment.'),
    ).toBeInTheDocument()
  })
})
