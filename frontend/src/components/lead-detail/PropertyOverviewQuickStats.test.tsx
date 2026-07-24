import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import {
  formatLastSaleCell,
  formatMoneyValue,
  formatUnitsDetailsCell,
  resolveLastSaleCell,
  PropertyOverviewQuickStats,
} from './PropertyOverviewQuickStats'
import type { CommandCenterPayload } from '@/types'

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

describe('PropertyOverviewQuickStats formatters', () => {
  it('formats money and last sale with date + amount', () => {
    expect(formatMoneyValue(520000)).toBe('$520,000')
    expect(formatMoneyValue(null)).toBeNull()
    expect(formatLastSaleCell(310000, '1993-04-15')).toBe('04/15/1993\n$310,000')
    expect(formatLastSaleCell(310000, '1/3/1989')).toBe('1/3/1989\n$310,000')
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
    ).toBe('10/07/2008\n$425,000')
  })

  it('formats units · type', () => {
    expect(formatUnitsDetailsCell(3, 'triplex')).toBe('3 Units · Triplex')
    expect(formatUnitsDetailsCell(1, null)).toBe('1 Unit')
    expect(formatUnitsDetailsCell(null, 'duplex')).toBe('Duplex')
    expect(formatUnitsDetailsCell(null, null)).toBeNull()
  })
})

describe('PropertyOverviewQuickStats', () => {
  it('renders value / sale / units cells and omits Est. rent until a source exists', () => {
    render(<PropertyOverviewQuickStats commandCenterData={basePayload()} />)
    expect(screen.getByTestId('quick-stat-est-value')).toHaveTextContent('—')
    expect(screen.queryByTestId('quick-stat-est-rent')).not.toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-last-sale')).toHaveTextContent('—')
    expect(screen.getByTestId('quick-stat-units-details')).toHaveTextContent('—')
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
})
