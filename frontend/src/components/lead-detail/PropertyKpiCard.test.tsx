import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider, createTheme } from '@mui/material'
import {
  buildAtAGlanceRows,
  buildMetricGridCells,
  PropertyKpiCard,
} from './PropertyKpiCard'
import type { CommandCenterPayload } from '@/types'

const theme = createTheme()

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

describe('buildAtAGlanceRows', () => {
  it('includes beds/baths, sqft, year, tax, and deal when present (no type — lives in Quick Stats; mail history is MailHistorySection)', () => {
    const rows = buildAtAGlanceRows(
      basePayload({
        units: 4,
        property_type: 'fourplex',
        bedrooms: 8,
        bathrooms: 4,
        square_footage: 7120,
        year_built: 1925,
        deal_source: 'Driving for Dollars',
        deal_description: 'Saw for-sale sign',
        mailer_history_summary: {
          count: 2,
          last_sent_at: '01/15/2024',
          rows: [
            {
              id: 'mail-0',
              sent_at: '01/15/2024',
              label: 'Letter A',
              creative: null,
              template_name: null,
              campaign_id: 1,
              olc_order_id: null,
              address_feedback: null,
              cancelled: false,
              source: 'olc',
            },
          ],
        },
      }),
      { tax_bill_2021: 4200 } as never,
    )
    const byId = Object.fromEntries(rows.map((r) => [r.id, r.value]))
    expect(byId.type).toBeUndefined()
    expect(byId['beds-baths']).toBe('8 bd / 4 ba')
    expect(byId.sqft).toBe('7,120 SF')
    expect(byId['year-built']).toBe('1925')
    expect(byId.tax).toBe('$4,200')
    expect(byId['deal-source']).toBe('Driving for Dollars')
    expect(byId['deal-description']).toBe('Saw for-sale sign')
    expect(byId['mailer-history']).toBeUndefined()
  })
})

describe('buildMetricGridCells', () => {
  it('appends See more and pads to a full 3-column row', () => {
    const rows = buildAtAGlanceRows(
      basePayload({
        units: 2,
        property_type: 'duplex',
        bedrooms: 4,
        bathrooms: 2,
        square_footage: 2000,
        year_built: 1910,
      }),
    ).filter((r) => !r.wide)
    const cells = buildMetricGridCells(rows)
    expect(cells.length % 3).toBe(0)
    expect(cells.some((c) => c.kind === 'see-more')).toBe(true)
  })
})

describe('PropertyKpiCard', () => {
  it('renders At a glance rows from command-center data', () => {
    render(
      <ThemeProvider theme={theme}>
        <PropertyKpiCard
          commandCenterData={basePayload({
            units: 2,
            property_type: 'duplex',
            bedrooms: 4,
            bathrooms: 2,
            year_built: 1910,
          })}
        />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('property-kpi-card')).toBeInTheDocument()
    expect(screen.queryByTestId('kpi-type')).not.toBeInTheDocument()
    expect(screen.getByTestId('kpi-beds-baths')).toHaveTextContent('4 bd / 2 ba')
    expect(screen.getByTestId('kpi-year-built')).toHaveTextContent('1910')
    expect(screen.getByTestId('kpi-see-more')).toHaveTextContent('See more')
  })

  it('shows empty copy when nothing is available but still offers See more', () => {
    render(
      <ThemeProvider theme={theme}>
        <PropertyKpiCard commandCenterData={basePayload()} />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('kpi-empty')).toHaveTextContent('No summary metrics on file')
    expect(screen.getByTestId('kpi-see-more')).toHaveTextContent('See more')
  })

  it('scrolls to Deep Dive Details when See more is clicked', async () => {
    const user = userEvent.setup()
    const scrollIntoView = vi.fn()
    const el = document.createElement('div')
    el.id = 'deep-dive-details'
    el.scrollIntoView = scrollIntoView
    document.body.appendChild(el)
    try {
      render(
        <ThemeProvider theme={theme}>
          <PropertyKpiCard
            commandCenterData={basePayload({ units: 2, property_type: 'duplex' })}
          />
        </ThemeProvider>,
      )
      await user.click(screen.getByRole('link', { name: 'See more' }))
      expect(scrollIntoView).toHaveBeenCalled()
    } finally {
      el.remove()
    }
  })

  it('mounts MailHistorySection under At a glance after deal description', () => {
    render(
      <ThemeProvider theme={theme}>
        <PropertyKpiCard
          commandCenterData={basePayload({
            deal_description: 'Corner lot',
            mailer_history_summary: {
              count: 1,
              last_sent_at: '01/15/2024',
              rows: [
                {
                  id: 'mail-0',
                  sent_at: '01/15/2024',
                  label: 'Letter A',
                  creative: null,
                  template_name: null,
                  campaign_id: 1,
                  olc_order_id: null,
                  address_feedback: null,
                  cancelled: false,
                  source: 'olc',
                },
              ],
            },
          })}
        />
      </ThemeProvider>,
    )
    expect(screen.getByTestId('kpi-deal-description')).toHaveTextContent('Corner lot')
    expect(screen.queryByTestId('kpi-mailer-history')).not.toBeInTheDocument()
    const deal = screen.getByTestId('kpi-deal-description')
    const mail = screen.getByTestId('mail-history-section')
    expect(mail).toBeInTheDocument()
    expect(mail).toHaveTextContent('Letter A')
    expect(screen.getByTestId('property-kpi-card').contains(mail)).toBe(true)
    // Mail history must follow At a glance wide rows (deal description).
    expect(deal.compareDocumentPosition(mail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
