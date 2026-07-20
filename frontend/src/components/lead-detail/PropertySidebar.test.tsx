import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PropertySidebar, saleVerifyPollDelaysMs } from '@/components/lead-detail/PropertySidebar'
import type { CommandCenterPayload } from '@/types'
import { commandCenterService, leadTaskService } from '@/services/api'
import { propertyMatchService } from '@/services/propertyMatchApi'

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    commandCenterService: {
      ...actual.commandCenterService,
      verifySaleDate: vi.fn(),
      getCommandCenter: vi.fn(),
    },
    leadTaskService: {
      ...actual.leadTaskService,
      createTask: vi.fn(),
    },
  }
})

vi.mock('@/services/propertyMatchApi', () => ({
  propertyMatchService: {
    preview: vi.fn(),
    approve: vi.fn(),
  },
  buildingOwnershipService: {},
}))

vi.stubGlobal('navigator', {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
})

function renderSidebar(
  payload: CommandCenterPayload,
  options: { onViewSaleHistory?: () => void } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <PropertySidebar
          commandCenterData={payload}
          onViewSaleHistory={options.onViewSaleHistory}
        />
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
    is_cook_county_eligible: true,
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
      message: '',
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

  it('always shows Mailing under Contact Info with Not on file when empty', () => {
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

    expect(screen.getByText('Contact Info')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-owner-mailing')).toHaveTextContent('Mailing')
    expect(screen.getByTestId('sidebar-owner-mailing')).toHaveTextContent('Not on file')
    expect(screen.getByTestId('owner-mailing-missing-for-mail')).toBeInTheDocument()
    expect(screen.queryByText('Owner Mailing Address')).not.toBeInTheDocument()
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

    expect(screen.getByTestId('sidebar-owner-mailing')).toHaveTextContent('Not on file')
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

    expect(screen.getByTestId('sidebar-owner-mailing')).toHaveTextContent('Not on file')
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
    expect(screen.getByTestId('sidebar-owner-mailing')).not.toHaveTextContent('Not on file')
    expect(screen.queryByTestId('owner-mailing-missing-for-mail')).not.toBeInTheDocument()
  })
})

describe('PropertySidebar always-visible sale and PIN', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    vi.mocked(commandCenterService.verifySaleDate).mockResolvedValue({
      lead_id: 1,
      queued: false,
      ran_sync: true,
      message: '',
    })
  })

  afterEach(() => {
    vi.useRealTimers()
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

  it('formats condensed Cook County PINs with dashes', () => {
    renderSidebar(
      makePayload({
        county_assessor_pin: '14211234560000',
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-county-assessor-pin')).toHaveTextContent(
      '14-21-123-456-0000',
    )
  })

  it('copies the dashed PIN from the sidebar copy control', () => {
    const writeText = vi.mocked(navigator.clipboard.writeText)
    writeText.mockClear()

    renderSidebar(
      makePayload({
        county_assessor_pin: '14211234560000',
      } as Partial<CommandCenterPayload>),
    )

    fireEvent.click(screen.getByTestId('sidebar-pin-copy'))
    expect(writeText).toHaveBeenCalledWith('14-21-123-456-0000')
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
    expect(screen.getByTestId('sidebar-verify-sale-date')).toHaveTextContent('Verify')
    fireEvent.click(screen.getByTestId('sidebar-verify-sale-date'))

    await waitFor(() => {
      expect(commandCenterService.verifySaleDate).toHaveBeenCalledWith(643)
    })
    expect(screen.queryByText('Verification checked.')).not.toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByTestId('sidebar-sale-verify-spinner')).not.toBeInTheDocument()
    })
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
    expect(screen.queryByTestId('sidebar-verify-sale-date')).not.toBeInTheDocument()

    resolveVerify({ lead_id: 643, queued: false, ran_sync: true, message: '' })
    await waitFor(() => {
      expect(screen.queryByTestId('sidebar-sale-verify-spinner')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Verification checked.')).not.toBeInTheDocument()
  })

  it('keeps spinner through queued Celery poll and never shows Verification queued', async () => {
    const previousDelays = [...saleVerifyPollDelaysMs]
    saleVerifyPollDelaysMs.splice(0, saleVerifyPollDelaysMs.length, 0)

    try {
      vi.mocked(commandCenterService.verifySaleDate).mockResolvedValue({
        lead_id: 643,
        queued: true,
        ran_sync: false,
        message: 'Verification queued.',
      })
      vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(
        makePayload({
          id: 643,
          most_recent_sale_display: '06/12/2018',
          sale_date_meta: {
            last_checked_at: '2026-07-17T12:00:00Z',
            source: 'Cook County records',
            status: 'ok',
          },
        } as Partial<CommandCenterPayload>),
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
      expect(screen.queryByText('Verification queued.')).not.toBeInTheDocument()

      await waitFor(() => {
        expect(screen.queryByTestId('sidebar-sale-verify-spinner')).not.toBeInTheDocument()
      })
      expect(screen.queryByText('Verification checked.')).not.toBeInTheDocument()
      expect(screen.queryByText('Verification queued.')).not.toBeInTheDocument()
    } finally {
      saleVerifyPollDelaysMs.splice(0, saleVerifyPollDelaysMs.length, ...previousDelays)
    }
  })

  it('offers verify when sale is None and not yet checked', () => {
    renderSidebar(
      makePayload({
        most_recent_sale_display: null,
        sale_date_meta: {
          last_checked_at: null,
          last_updated_at: null,
          source: null,
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-most-recent-sale')).toHaveTextContent('None')
    expect(screen.getByText('Sale date not verified yet')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-verify-sale-date')).toHaveTextContent('Verify')
  })

  it('shows no-sale caption after no_sale verify for None sale', () => {
    renderSidebar(
      makePayload({
        most_recent_sale_display: null,
        sale_date_meta: {
          last_checked_at: '2026-07-01T00:00:00Z',
          source: 'Cook County records',
          status: 'no_sale',
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-sale-last-checked')).toHaveTextContent(
      'No sale found as of Jul 2026',
    )
    expect(screen.getByTestId('sidebar-sale-verified-check')).toBeInTheDocument()
  })

  it('keeps displayed sale without checkmark and says cannot confirm after no_sale probe', () => {
    renderSidebar(
      makePayload({
        most_recent_sale_display: '07/17/2024',
        sale_date_meta: {
          last_checked_at: '2026-07-17T18:46:01Z',
          source: 'Cook County records',
          status: 'no_sale',
        },
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-most-recent-sale')).toHaveTextContent('07/17/2024')
    expect(screen.queryByTestId('sidebar-sale-verified-check')).not.toBeInTheDocument()
    expect(screen.getByTestId('sidebar-sale-last-checked')).toHaveTextContent(
      'Cannot confirm as of Jul 2026',
    )
    expect(screen.getByTestId('sidebar-reverify-sale-date')).toBeInTheDocument()
    expect(screen.queryByTestId('sidebar-verify-sale-date')).not.toBeInTheDocument()
  })

  it('offers re-verify refresh between freshness and sale history after a successful check', () => {
    const onViewSaleHistory = vi.fn()
    renderSidebar(
      makePayload({
        most_recent_sale_display: '07/17/2024',
        most_recent_sale_price: 967000,
        sale_date_meta: {
          last_checked_at: '2026-07-17T18:46:01Z',
          source: 'Cook County records',
          status: 'success',
        },
      } as Partial<CommandCenterPayload>),
      { onViewSaleHistory },
    )

    expect(screen.getByTestId('sidebar-sale-verified-check')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-sale-last-checked')).toHaveTextContent(
      'Confirmed as of Jul 2026',
    )
    expect(screen.getByTestId('sidebar-reverify-sale-date')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-sale-history-link')).toBeInTheDocument()
    expect(screen.queryByTestId('sidebar-verify-sale-date')).not.toBeInTheDocument()
  })

  it('shows Look up PIN when PIN is missing and queues research when no match', async () => {
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

    renderSidebar(
      makePayload({
        county_assessor_pin: null,
      } as Partial<CommandCenterPayload>),
    )

    expect(screen.getByTestId('sidebar-look-up-pin')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('sidebar-look-up-pin'))

    await waitFor(() => {
      expect(propertyMatchService.preview).toHaveBeenCalledWith(1)
      expect(leadTaskService.createTask).toHaveBeenCalledWith(1, {
        title: 'Research missing PIN',
        task_type: 'research_missing_pin',
      })
    })
  })

  it('does not create research PIN task when address is incomplete', async () => {
    vi.mocked(propertyMatchService.preview).mockResolvedValue({
      found: false,
      entered_address: {
        property_street: '1239 N Hoyne',
        property_city: null,
        property_state: null,
        property_zip: null,
      },
      recommended_address: null,
      pin: null,
      connector: null,
      address_complete: false,
      reason: 'incomplete_address',
      message: 'Add city, state, and ZIP before looking up a PIN',
    })

    renderSidebar(
      makePayload({
        county_assessor_pin: null,
      } as Partial<CommandCenterPayload>),
    )

    fireEvent.click(screen.getByTestId('sidebar-look-up-pin'))

    await waitFor(() => {
      expect(propertyMatchService.preview).toHaveBeenCalledWith(1)
    })
    expect(leadTaskService.createTask).not.toHaveBeenCalled()
    expect(await screen.findByText(/Add city, state, and ZIP/i)).toBeInTheDocument()
  })

    it('shows Apply when Look up PIN finds a candidate', async () => {
    vi.mocked(propertyMatchService.preview).mockResolvedValue({
      found: true,
      entered_address: {
        property_street: '123 Test St',
        property_city: 'Chicago',
        property_state: 'IL',
        property_zip: null,
      },
      recommended_address: {
        property_street: '123 Test St',
        property_city: 'Chicago',
        property_state: 'IL',
        property_zip: '60601',
        county_assessor_pin: '14211234560000',
      },
      pin: '14211234560000',
      connector: 'cook_county',
    })
    vi.mocked(propertyMatchService.approve).mockResolvedValue({
      lead_id: 1,
      has_property_match: true,
      county_assessor_pin: '14-21-123-456-0000',
      recommended_action: 'call_ready',
      removed_from_queue: true,
    })

    renderSidebar(
      makePayload({
        county_assessor_pin: null,
      } as Partial<CommandCenterPayload>),
    )

    fireEvent.click(screen.getByTestId('sidebar-look-up-pin'))
    expect(await screen.findByTestId('sidebar-pin-candidate')).toHaveTextContent(
      '14-21-123-456-0000',
    )
    expect(screen.getByTestId('sidebar-apply-pin')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('sidebar-apply-pin'))
    await waitFor(() => {
      expect(propertyMatchService.approve).toHaveBeenCalledWith(1, {
        pin: '14-21-123-456-0000',
      })
    })
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
          status: 'success',
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

describe('PropertySidebar prior-owner stale contacts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('grays out contact info and mailing when contacts_likely_prior_owner', () => {
    renderSidebar(
      makePayload({
        contacts_likely_prior_owner: true,
        contacts_stale_since: '2024-07-17',
        mailing_address: '100 Prior Ln',
        mailing_city: 'Chicago',
        mailing_state: 'IL',
        mailing_zip: '60614',
        emails: undefined,
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
            emails: [{ id: 1, value: 'prior@example.com', label: 'personal' }],
          },
        ],
      }),
    )

    expect(screen.getByTestId('sidebar-likely-prior-owner')).toHaveTextContent(
      'Likely prior owner',
    )
    expect(screen.getByTestId('sidebar-contact-info')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-owner-mailing')).toHaveTextContent('100 Prior Ln')
    const wash = screen.getByTestId('sidebar-likely-prior-owner').parentElement
    expect(wash).toHaveStyle({ pointerEvents: 'none' })

    // Outreach disabled for likely prior-owner contacts (display only).
    expect(screen.getByTestId('sidebar-phones')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /prior@example.com/i })).not.toBeInTheDocument()
    expect(screen.getByText('prior@example.com')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /630.*202.*3839/i })).not.toBeInTheDocument()
  })

  it('does not show Past owners in the right rail when stale', () => {
    renderSidebar(
      makePayload({
        contacts_likely_prior_owner: true,
        past_owners: [
          {
            id: 7,
            captured_at: '2024-07-18T12:00:00+00:00',
            reason: 'recent_sale',
            sale_date: '2024-07-17',
            owner_names: [{ first_name: 'Prior', last_name: 'Seller', is_primary: true }],
            phones: [],
            emails: [],
          },
        ],
      }),
    )
    expect(screen.queryByTestId('sidebar-past-owners')).not.toBeInTheDocument()
  })

  it('does not show Past owners in the right rail', () => {
    renderSidebar(
      makePayload({
        contacts_likely_prior_owner: false,
        past_owners: [
          {
            id: 7,
            captured_at: '2024-07-18T12:00:00+00:00',
            reason: 'recent_sale',
            sale_date: '2024-07-17',
            owner_names: [
              {
                contact_id: 1,
                first_name: 'Prior',
                last_name: 'Seller',
                role: 'owner',
                is_primary: true,
              },
            ],
            phones: [{ value: '(312) 555-0100' }],
            emails: [{ value: 'old@example.com' }],
            mailing_address: '9 Old St',
            mailing_city: 'Chicago',
            mailing_state: 'IL',
            mailing_zip: '60610',
          },
        ],
      }),
    )

    expect(screen.queryByTestId('sidebar-past-owners')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Past owners/i })).not.toBeInTheDocument()
  })
})

describe('PropertySidebar Other Addresses placement', () => {
  it('does not render Other Addresses in the sidebar (lives on Info instead)', () => {
    renderSidebar(makePayload({ address_2: '456 Secondary Ave' }))

    expect(screen.getByText('Additional Address')).toBeInTheDocument()
    expect(screen.getByText('456 Secondary Ave')).toBeInTheDocument()
    expect(screen.queryByText('Other Addresses')).not.toBeInTheDocument()
  })
})
