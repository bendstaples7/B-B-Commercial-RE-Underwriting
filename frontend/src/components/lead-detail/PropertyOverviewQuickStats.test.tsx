import { beforeEach, describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  formatLastSaleCell,
  formatMoneyValue,
  formatUnitsDetailsCell,
  resolveLastSaleCell,
  resolveLastSaleEditorFields,
  resolveNoSaleCopy,
  PropertyOverviewQuickStats,
} from './PropertyOverviewQuickStats'
import type { CommandCenterPayload } from '@/types'
import { commandCenterService } from '@/services/api'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    updateCategory: vi.fn(),
    updatePropertyOverview: vi.fn(),
  },
}))

function basePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: null,
    owner_last_name: null,
    property_street: '1 Main',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(commandCenterService.updatePropertyOverview).mockResolvedValue({
    assessed_value: null,
    most_recent_sale: null,
    acquisition_date: null,
    most_recent_sale_price: null,
    units: null,
    property_type: null,
    lead_score: null,
    timeline_entry: null,
  })
  vi.mocked(commandCenterService.updateCategory).mockResolvedValue({
    lead_category: 'residential',
    lead_category_locked: true,
    property_type: null,
    lead_score: null,
    timeline_entry: {} as never,
  })
})

describe('PropertyOverviewQuickStats formatters', () => {
  it('formats money and last sale with date + amount', () => {
    expect(formatMoneyValue(520000)).toBe('$520,000')
    expect(formatMoneyValue(null)).toBeNull()
    expect(formatLastSaleCell(310000, '1993-04-15')).toBe('04/15/1993 · $310,000')
    expect(formatLastSaleCell(310000, '1/3/1989')).toBe('1/3/1989 · $310,000')
    expect(formatLastSaleCell(null, '1/3/1989')).toBe('1/3/1989')
    expect(formatLastSaleCell(null, null)).toBeNull()
  })

  it('fills missing price from sale_history', () => {
    expect(
      resolveLastSaleCell(
        basePayload({
          most_recent_sale_display: '10/07/2008',
          most_recent_sale_price: null,
          sale_history: [{ sale_date: '2008-10-07', sale_price: 425000 }],
        }),
      ),
    ).toBe('10/07/2008 · $425,000')
  })

  it('resolves editor sale fields from the same display fallbacks', () => {
    expect(
      resolveLastSaleEditorFields(
        basePayload({
          acquisition_date: '2020-01-02',
          most_recent_sale_display: '01/02/2020',
          most_recent_sale: null,
        }),
      ),
    ).toMatchObject({
      mostRecentSale: '01/02/2020',
      saleDateField: 'acquisition_date',
    })
    expect(
      resolveLastSaleEditorFields(
        basePayload({
          most_recent_sale_price: null,
          sale_history: [{ sale_date: '2008-10-07', sale_price: 425000 }],
        }),
      ),
    ).toMatchObject({
      mostRecentSale: '2008-10-07',
      mostRecentSalePrice: 425000,
      saleDateField: 'most_recent_sale',
    })
  })

  it('formats units · type', () => {
    expect(formatUnitsDetailsCell(3, 'triplex')).toBe('3 Units · Triplex')
    expect(formatUnitsDetailsCell(1, null)).toBe('1 Unit')
    expect(formatUnitsDetailsCell(null, 'duplex')).toBe('Duplex')
    expect(formatUnitsDetailsCell(null, null)).toBeNull()
  })

  it('surfaces explicit no-sale copy when Assessor ran but found nothing (lead 10970 class)', () => {
    const payload = basePayload({
      most_recent_sale_display: null,
      most_recent_sale: null,
      most_recent_sale_price: null,
      sale_date_meta: {
        last_updated_at: null,
        last_checked_at: '2026-07-30T21:24:42.709208',
        source: 'Cook County records',
        status: 'no_sale',
      },
    })
    expect(resolveLastSaleCell(payload)).toBeNull()
    expect(resolveNoSaleCopy(payload)).toBe('No sale found as of Jul 2026')
  })

  it('does not show no-sale copy once a sale is actually resolved', () => {
    const payload = basePayload({
      most_recent_sale_display: '1993-04-01',
      most_recent_sale_price: 310000,
      sale_date_meta: {
        last_updated_at: null,
        last_checked_at: '2026-07-30T21:24:42.709208',
        source: 'Cook County records',
        status: 'success',
      },
    })
    expect(resolveNoSaleCopy(payload)).toBeNull()
  })
})

describe('PropertyOverviewQuickStats', () => {
  it('renders value / sale / units cells and omits Est. rent until a source exists', () => {
    render(<PropertyOverviewQuickStats commandCenterData={basePayload()} />)
    expect(screen.getByTestId('quick-stat-est-value')).toHaveTextContent('—')
    expect(screen.queryByTestId('quick-stat-est-rent')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-last-sale')).toHaveTextContent('—')
    expect(screen.getByTestId('quick-stat-units-details')).toHaveTextContent('—')
    expect(screen.queryByTestId('quick-stat-condo-check')).not.toBeInTheDocument()
  })

  it('fills cells from payload fields with last sale date and amount', () => {
    render(
      <PropertyOverviewQuickStats
        commandCenterData={basePayload({
          assessed_value: 520000,
          most_recent_sale_price: 310000,
          most_recent_sale_display: '1993-04-01',
          units: 3,
          property_type: 'triplex',
        })}
      />,
    )
    expect(screen.getByTestId('quick-stat-est-value')).toHaveTextContent('$520,000')
    expect(screen.queryByTestId('quick-stat-est-rent')).not.toBeInTheDocument()
    const lastSale = screen.getByTestId('quick-stat-last-sale')
    expect(lastSale).toHaveTextContent('04/01/1993')
    expect(lastSale).toHaveTextContent('$310,000')
    expect(screen.getByTestId('quick-stat-units-details')).toHaveTextContent(/3 Units/)
  })

  it('shows "No sale found" copy instead of a bare em-dash when Assessor ran empty', () => {
    render(
      <PropertyOverviewQuickStats
        commandCenterData={basePayload({
          county_assessor_pin: '13262150360000',
          sale_date_meta: {
            last_updated_at: null,
            last_checked_at: '2026-07-30T21:24:42.709208',
            source: 'Cook County records',
            status: 'no_sale',
          },
        })}
      />,
    )
    expect(screen.getByTestId('quick-stat-last-sale')).toHaveTextContent('No sale found as of Jul 2026')
  })

  it('does not embed Condo check in the KPI grid (lives in HeaderCondoCheckPanel)', () => {
    render(
      <PropertyOverviewQuickStats
        commandCenterData={basePayload({
          lead_category: 'commercial',
          condo_risk_status: 'needs_review',
          condo_confidence: 'low',
          condo_check_reason: 'Incomplete data',
          condo_analysis_id: 99,
        })}
      />,
    )
    expect(screen.queryByTestId('quick-stat-condo-check')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-est-value')).toBeInTheDocument()
  })

  it('updates acquisition_date when that field drives the displayed sale date', async () => {
    const user = userEvent.setup()
    render(
      <PropertyOverviewQuickStats
        commandCenterData={basePayload({
          acquisition_date: '2020-01-02',
          most_recent_sale_display: '01/02/2020',
          most_recent_sale_price: 425000,
        })}
        leadId={1}
      />,
    )

    await user.click(screen.getByTestId('quick-stat-last-sale-edit-trigger'))
    const dateInput = screen.getByTestId('quick-stat-last-sale-date-input')
    await user.clear(dateInput)
    await user.type(dateInput, '2021-03-04')
    await user.click(screen.getByTestId('quick-stat-last-sale-save'))

    await waitFor(() => {
      expect(commandCenterService.updatePropertyOverview).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          acquisition_date: '2021-03-04',
          most_recent_sale: '2021-03-04',
          most_recent_sale_price: 425000,
        }),
      )
    })
  })

  it('seeds the sale editor price from sale_history fallback', async () => {
    const user = userEvent.setup()
    render(
      <PropertyOverviewQuickStats
        commandCenterData={basePayload({
          most_recent_sale_price: null,
          sale_history: [{ sale_date: '2008-10-07', sale_price: 425000 }],
        })}
        leadId={1}
      />,
    )

    await user.click(screen.getByTestId('quick-stat-last-sale-edit-trigger'))

    expect(screen.getByTestId('quick-stat-last-sale-price-input')).toHaveValue('425000')
  })

  it('rejects marker-only prices and fractional units before saving', async () => {
    const user = userEvent.setup()
    render(<PropertyOverviewQuickStats commandCenterData={basePayload({ units: 1 })} leadId={1} />)

    await user.click(screen.getByTestId('quick-stat-last-sale-edit-trigger'))
    const priceInput = screen.getByTestId('quick-stat-last-sale-price-input')
    await user.type(priceInput, '$')
    await user.click(screen.getByTestId('quick-stat-last-sale-save'))
    expect(await screen.findByText('Enter a valid number.')).toBeInTheDocument()
    expect(commandCenterService.updatePropertyOverview).not.toHaveBeenCalled()

    await user.click(screen.getByTestId('quick-stat-last-sale-cancel'))
    await user.click(screen.getByTestId('quick-stat-units-details-edit-trigger'))
    const unitsInput = screen.getByTestId('quick-stat-units-input')
    await user.clear(unitsInput)
    await user.type(unitsInput, '1.5')
    await user.click(screen.getByTestId('quick-stat-units-details-save'))
    expect(await screen.findByText('Units must be a whole number.')).toBeInTheDocument()
    expect(commandCenterService.updatePropertyOverview).not.toHaveBeenCalled()
  })

  it('preserves an unparseable raw sale date when only price changes', async () => {
    const user = userEvent.setup()
    render(
      <PropertyOverviewQuickStats
        commandCenterData={basePayload({
          most_recent_sale: 'Recorded circa 2018',
          most_recent_sale_price: 300000,
        })}
        leadId={1}
      />,
    )

    await user.click(screen.getByTestId('quick-stat-last-sale-edit-trigger'))
    const priceInput = screen.getByTestId('quick-stat-last-sale-price-input')
    await user.clear(priceInput)
    await user.type(priceInput, '325000')
    await user.click(screen.getByTestId('quick-stat-last-sale-save'))

    await waitFor(() => {
      expect(commandCenterService.updatePropertyOverview).toHaveBeenCalledWith(
        1,
        expect.not.objectContaining({ most_recent_sale: expect.anything() }),
      )
    })
    expect(commandCenterService.updatePropertyOverview).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ most_recent_sale_price: 325000 }),
    )
  })

  it('shows Category as 4th KPI cell (user 12B)', () => {
    render(
      <PropertyOverviewQuickStats
        commandCenterData={basePayload({ lead_category: 'residential' })}
      />,
    )
    expect(screen.getByTestId('quick-stat-category')).toHaveTextContent('Residential')
  })
})
