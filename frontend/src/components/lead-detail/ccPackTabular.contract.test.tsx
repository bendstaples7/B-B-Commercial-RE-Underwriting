/**
 * Tabular-layout wiring for KPI band + PIN Address table.
 * Full CC header packing ALIGNED requires:
 *   node scripts/cc-header-packing-geometry.mjs  (Playwright)
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { PropertyOverviewQuickStats } from '@/components/lead-detail/PropertyOverviewQuickStats'
import type { CommandCenterPayload } from '@/types'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

function payload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: null,
    owner_last_name: null,
    property_street: '1 Main',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made',
    lead_category: 'residential',
    has_property_match: true,
    analysis_session_id: null,
    assessed_value: 100000,
    units: 2,
    property_type: 'duplex',
    recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    ...overrides,
  }
}

describe('tabular-layout — KPI band (wiring; packing ALIGNED is Playwright)', () => {
  it('renders four KPI cells with expected testids', () => {
    render(<PropertyOverviewQuickStats commandCenterData={payload()} />)
    const band = screen.getByTestId('property-overview-quick-stats')
    for (const id of ['est-value', 'last-sale', 'units-details', 'category'] as const) {
      expect(within(band).getByTestId(`quick-stat-${id}`)).toBeInTheDocument()
    }
  })
})

describe('tabular-layout — PIN Address column structure', () => {
  it('BuildingOwnershipSection header and body share PIN|Address|Class|Condo columns', () => {
    const src = readFileSync(
      resolve(__dirname, '../BuildingOwnershipSection.tsx'),
      'utf8',
    )
    expect(src).toMatch(/<TableCell>PIN<\/TableCell>/)
    expect(src).toMatch(/<TableCell>Address<\/TableCell>/)
    expect(src).toMatch(/<TableCell>Class<\/TableCell>/)
    expect(src).toMatch(/<TableCell>Condo signal<\/TableCell>/)
    expect(src).toContain('formatAssessorPinAddress')
  })
})
