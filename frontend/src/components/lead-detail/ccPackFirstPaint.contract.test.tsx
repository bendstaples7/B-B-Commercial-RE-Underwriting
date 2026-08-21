/**
 * First-paint settle contracts for Pack CC surfaces.
 * Landmark presence after render (spinner not the only UI).
 * Header packing geometry ALIGNED is Playwright: scripts/cc-header-packing-geometry.mjs
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { PropertyOverviewQuickStats } from '@/components/lead-detail/PropertyOverviewQuickStats'
import type { CommandCenterPayload } from '@/types'

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
    lead_category: 'commercial',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    ...overrides,
  }
}

describe('first-paint settle — CC packing / KPI / condo pending / no_sale', () => {
  it('property-overview-header packs with unique primary landmarks (structure)', () => {
    const ulcc = readFileSync(
      resolve(__dirname, '../UnifiedLeadCommandCenter.tsx'),
      'utf8',
    )
    const stats = readFileSync(
      resolve(__dirname, './PropertyOverviewQuickStats.tsx'),
      'utf8',
    )
    expect(ulcc).toContain('data-testid="property-overview-header"')
    expect(ulcc).toContain('ccHeaderPaperSx')
    expect(ulcc).toContain('data-testid="cc-header-primary-cluster"')
    expect(ulcc).toContain('data-testid="cc-header-trailing-panels"')
    expect(ulcc).toContain('PropertyOverviewQuickStats')
    expect(stats).toContain('data-testid="property-overview-quick-stats"')
    // One primary surface title landmark — address column, not duplicated breadcrumb.
    const addressTitleHits = (ulcc.match(/property-overview-address/g) || []).length
    expect(addressTitleHits).toBeGreaterThanOrEqual(1)
  })

  it('quick-stats settle with Category KPI landmark (primary title unique via testids)', () => {
    render(<PropertyOverviewQuickStats commandCenterData={payload()} />)
    expect(screen.getByTestId('property-overview-quick-stats')).toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-category')).toHaveTextContent('Commercial')
    expect(screen.getByTestId('quick-stat-est-value')).toBeInTheDocument()
  })

  it('category selector landmark is wired on the live header (primary title unique)', () => {
    const ulcc = readFileSync(
      resolve(__dirname, '../UnifiedLeadCommandCenter.tsx'),
      'utf8',
    )
    const stats = readFileSync(
      resolve(__dirname, './PropertyOverviewQuickStats.tsx'),
      'utf8',
    )
    const selector = readFileSync(
      resolve(__dirname, '../LeadCategorySelector.tsx'),
      'utf8',
    )
    const kpiEditor = readFileSync(
      resolve(__dirname, './PropertyOverviewKpiEditor.tsx'),
      'utf8',
    )
    expect(ulcc).toContain('data-testid="property-overview-address-line"')
    expect(ulcc).toContain('SameAddressMergeBanner')
    expect(ulcc).toContain('data-owner-link-highlight')
    expect(stats).toContain('LeadCategorySelector')
    expect(stats).toContain('PropertyOverviewKpiEditor')
    expect(selector).toContain('data-testid="lead-category-selector"')
    expect(kpiEditor).toContain('quick-stat-${kind}-edit-trigger')
    expect(kpiEditor).toContain("kind === 'est-value'")
    expect(kpiEditor).toContain("kind === 'last-sale'")
    expect(kpiEditor).toContain("kind === 'units-details'")
  })

  it('KPI edit affordances settle when leadId is wired (primary title unique)', () => {
    render(<PropertyOverviewQuickStats commandCenterData={payload()} leadId={1} />)
    expect(screen.getByTestId('quick-stat-est-value-edit-trigger')).toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-last-sale-edit-trigger')).toBeInTheDocument()
    expect(screen.getByTestId('quick-stat-units-details-edit-trigger')).toBeInTheDocument()
    expect(screen.getByTestId('lead-category-selector')).toBeInTheDocument()
  })

  it('category selector settles in the Category KPI cell when leadId is wired', () => {
    render(
      <PropertyOverviewQuickStats commandCenterData={payload()} leadId={1} />,
    )
    expect(screen.getByTestId('property-overview-quick-stats')).toBeInTheDocument()
    expect(screen.getByTestId('lead-category-selector')).toHaveTextContent('Commercial')
    expect(screen.getByTestId('quick-stat-category')).toContainElement(
      screen.getByTestId('lead-category-selector'),
    )
  })

  it('condo pending landmark: Checking… when building_ownership_pending', async () => {
    const { resolveCondoCheckLines } = await import(
      '@/components/lead-detail/PropertyOverviewQuickStats'
    )
    const lines = resolveCondoCheckLines(
      payload({ building_ownership_pending: true }),
    )
    expect(lines.verdict).toMatch(/Checking/)
  })

  it('no_sale landmark copy settles when Assessor empty', () => {
    render(
      <PropertyOverviewQuickStats
        commandCenterData={payload({
          sale_date_meta: {
            last_updated_at: null,
            last_checked_at: '2026-07-30T21:24:42.709208',
            source: 'Cook County records',
            status: 'no_sale',
          },
        })}
      />,
    )
    expect(screen.getByTestId('quick-stat-last-sale')).toHaveTextContent(/No sale found/)
  })

  it('settles one-line address + ≤2 score drivers structure', () => {
    const ulcc = readFileSync(
      resolve(__dirname, '../UnifiedLeadCommandCenter.tsx'),
      'utf8',
    )
    const score = readFileSync(
      resolve(__dirname, './HeaderLeadScorePanel.tsx'),
      'utf8',
    )
    const chrome = readFileSync(
      resolve(__dirname, './commandCenterChrome.ts'),
      'utf8',
    )
    expect(ulcc).toContain('data-testid="property-overview-address-line"')
    expect(ulcc).toMatch(/md:\s*['"]nowrap['"]/)
    expect(score).toMatch(/limit\s*=\s*2/)
    expect(score).toContain('header-score-drivers')
    // Fluid clamp slots — one primary header bar at any md+ width.
    expect(chrome).toMatch(/ccHeaderAddressColumnSx[\s\S]{0,250}md:\s*['"]0 0 auto['"]/)
    expect(chrome).toMatch(/ccHeaderPrimaryClusterSx[\s\S]{0,250}md:\s*['"]1 1 auto['"]/)
    expect(chrome).toMatch(/ccHeaderQuickStatsSx[\s\S]{0,250}md:\s*['"]1 1 auto['"]/)
    expect(chrome).toMatch(/ccHeaderTrailingPanelsSx[\s\S]{0,250}md:\s*['"]1 1 auto['"]/)
    expect(chrome).toMatch(/clamp\(10rem,\s*13vw,\s*260px\)/)
  })
})
