/**
 * Header packing contracts — structure + forbid (wiring).
 * Geometry ALIGNED requires scripts/cc-header-packing-geometry.mjs (Playwright).
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  ccHeaderAddressColumnSx,
  ccHeaderPrimaryClusterSx,
  ccHeaderQuickStatsSx,
  ccHeaderTrailingPanelsSx,
} from '@/components/lead-detail/commandCenterChrome'

const ROOT = resolve(__dirname, '../../..')

function readSrc(rel: string): string {
  return readFileSync(resolve(ROOT, rel), 'utf8')
}

describe('header packing contracts (structure + forbid)', () => {
  it('keeps one md+ fluid header bar — clamp slots, no fixed trail width', () => {
    expect(ccHeaderPrimaryClusterSx).toBeTruthy()
    expect(ccHeaderTrailingPanelsSx).toBeTruthy()
    expect(ccHeaderQuickStatsSx).toBeTruthy()
    const trail = JSON.stringify(ccHeaderTrailingPanelsSx)
    const address = JSON.stringify(ccHeaderAddressColumnSx)
    const stats = JSON.stringify(ccHeaderQuickStatsSx)
    const chrome = readSrc('src/components/lead-detail/commandCenterChrome.ts')
    const ulcc = readSrc('src/components/UnifiedLeadCommandCenter.tsx')

    // FORBID full-width trail row (stacks Last sale above condo).
    expect(trail).not.toMatch(/"md":"1 1 100%"/)
    expect(trail).not.toMatch(/"minWidth":"100%"/)
    // Fluid trail grows to fill slack; no fixed pair width.
    expect(trail).toMatch(/"md":"1 1 auto"/)
    expect(trail).toMatch(/"ml":0/)
    expect(trail).not.toMatch(/"flexShrink":0/)
    expect(trail).not.toMatch(/"md":368/)
    expect(trail).not.toMatch(/"0 0 180px"/)
    expect(trail).toMatch(/clamp\(10rem,\s*13vw,\s*260px\)/)
    expect(trail).toMatch(/"md":"none"/)

    // Address/KPI hug; trail panels grow to fill slack (no gap left of condo).
    expect(address).toMatch(/"md":"0 0 auto"/)
    expect(address).toMatch(/"md":"none"/)
    expect(address).not.toMatch(/"md":"14rem"/)
    expect(JSON.stringify(ccHeaderPrimaryClusterSx)).toMatch(/"md":"1 1 auto"/)
    expect(stats).toMatch(/"md":"1 1 auto"/)
    expect(stats).toMatch(/repeat\(2,\s*auto\)/)
    expect(trail).toMatch(/"md":"1 1 auto"/)

    // Header row nowrap on md; primary cluster stacks address above KPIs on xs.
    expect(ulcc).toMatch(/flexWrap:\s*\{\s*xs:\s*['"]wrap['"],\s*md:\s*['"]nowrap['"]/)
    expect(JSON.stringify(ccHeaderPrimaryClusterSx)).toMatch(/"xs":"wrap"/)
    expect(JSON.stringify(ccHeaderPrimaryClusterSx)).toMatch(/"md":"nowrap"/)
    expect(JSON.stringify(ccHeaderAddressColumnSx)).toMatch(/"xs":"1 1 100%"/)
    expect(JSON.stringify(ccHeaderAddressColumnSx)).toMatch(/"xs":"100%"/)

    // 2×2 KPI grid preserved.
    expect(stats).toMatch(/repeat\(2/)
    expect(address).not.toMatch(/42%/)
    expect(JSON.stringify(ccHeaderPrimaryClusterSx)).toMatch(/nowrap/)
    expect(chrome).toMatch(/ccHeaderPaperSx/)
  })

  it('forbids overflowWrap anywhere on the hero address (glyph-stack regression)', () => {
    const ulcc = readSrc('src/components/UnifiedLeadCommandCenter.tsx')
    const addressBlock = ulcc.slice(
      ulcc.indexOf('property-overview-address-line'),
      ulcc.indexOf('property-overview-address-line') + 900,
    )
    expect(addressBlock).not.toMatch(/overflowWrap:\s*\{\s*xs:\s*['"]anywhere['"]/)
    expect(addressBlock).toMatch(/overflowWrap:\s*\{\s*xs:\s*['"]break-word['"]/)
  })

  it('forbids address maxWidth 42% and KPIs inside trailing pack', () => {
    const ulcc = readSrc('src/components/UnifiedLeadCommandCenter.tsx')
    const lookbook = readSrc('src/pages/lookbook/CcPinDeprioritizeLookbookPage.tsx')
    const chrome = readSrc('src/components/lead-detail/commandCenterChrome.ts')

    expect(ulcc).toContain('ccHeaderPrimaryClusterSx')
    expect(ulcc).toContain('ccHeaderTrailingPanelsSx')
    expect(ulcc).not.toContain('ccHeaderTrailingPanelsHugSx')
    expect(ulcc).toContain('ccHeaderPaperSx')
    expect(ulcc).toContain('PropertyOverviewQuickStats')
    expect(ulcc).toContain('centerInGap')
    expect(ulcc).toContain('shouldShowCondoCheckCell')
    expect(chrome).toContain('ccHeaderQuickStatsCenteredSx')
    expect(chrome).not.toContain('ccHeaderTrailingPanelsHugSx')
    expect(ulcc).not.toMatch(/maxWidth:\s*\{\s*[^}]*md:\s*['"]42%['"]/)
    expect(lookbook).not.toMatch(/maxWidth:\s*['"]42%['"]/)
    expect(chrome).not.toMatch(/maxWidth:\s*\{\s*[^}]*md:\s*['"]42%['"]/)
    expect(chrome).toMatch(/overflow:\s*['"]visible['"]/)

    const trailJsx = ulcc.indexOf('data-testid="cc-header-trailing-panels"')
    expect(trailJsx).toBeGreaterThan(-1)
    const trailEnd = ulcc.indexOf('</Box>', trailJsx)
    const trailSlice = ulcc.slice(trailJsx, trailEnd)
    expect(trailSlice).not.toContain('PropertyOverviewQuickStats')
    expect(trailSlice).toContain('HeaderCondoCheckPanel')
    expect(trailSlice).toContain('HeaderLeadScorePanel')

    const primaryJsx = ulcc.indexOf('data-testid="cc-header-primary-cluster"')
    expect(primaryJsx).toBeGreaterThan(-1)
    const primaryEnd = ulcc.indexOf('data-testid="cc-header-trailing-panels"')
    const primarySlice = ulcc.slice(primaryJsx, primaryEnd)
    expect(primarySlice).toContain('PropertyOverviewQuickStats')
  })

  it('keeps 2-col quick-stats grid (user 1B)', () => {
    expect(JSON.stringify(ccHeaderQuickStatsSx)).toMatch(/repeat\(2/)
  })

  it('left-aligns KPI columns with a wider inter-column gap', () => {
    const stats = JSON.stringify(ccHeaderQuickStatsSx)
    const centered = readSrc('src/components/lead-detail/commandCenterChrome.ts')
    expect(stats).toMatch(/justifyItems['"]?\s*:\s*['"]start['"]/)
    expect(stats).toMatch(/textAlign['"]?\s*:\s*['"]left['"]/)
    expect(stats).toMatch(/"columnGap":\{"xs":2,"md":2\.5\}/)
    // Residential centering must not re-center items inside columns.
    expect(centered).toMatch(
      /ccHeaderQuickStatsCenteredSx[\s\S]{0,200}justifyItems:\s*['"]start['"]/,
    )
    expect(centered).not.toMatch(
      /ccHeaderQuickStatsCenteredSx[\s\S]{0,200}justifyItems:\s*['"]center['"]/,
    )
  })

  it('forbids nowrap on Units/details (spill into Category)', () => {
    const src = readSrc('src/components/lead-detail/PropertyOverviewQuickStats.tsx')
    expect(src).toMatch(/id:\s*'units-details'[\s\S]*?allowWrap:\s*true/)
    expect(src).toMatch(/id:\s*'category'[\s\S]*?allowWrap:\s*true/)
    expect(src).toMatch(/contain:\s*'layout style'/)
    expect(src).toMatch(/overflow:\s*'hidden'/)
  })

  it('packing tokens set contain + isolation', () => {
    const trail = JSON.stringify(ccHeaderTrailingPanelsSx)
    const stats = JSON.stringify(ccHeaderQuickStatsSx)
    expect(stats).toMatch(/contain/)
    expect(stats).toMatch(/isolate/)
    expect(trail).toMatch(/contain/)
  })

  it('requires one-line md address + forbids wrap clamps; score drivers no ellipsis', () => {
    const ulcc = readSrc('src/components/UnifiedLeadCommandCenter.tsx')
    const score = readSrc('src/components/lead-detail/HeaderLeadScorePanel.tsx')
    const condo = readSrc('src/components/lead-detail/HeaderCondoCheckPanel.tsx')
    const chrome = readSrc('src/components/lead-detail/commandCenterChrome.ts')
    expect(ulcc).toContain('property-overview-address-line')
    expect(ulcc).toMatch(/md:\s*['"]nowrap['"]/)
    expect(JSON.stringify(ccHeaderAddressColumnSx)).not.toMatch(/42%/)
    // FORBID address maxWidth rem ceilings that force early ellipsis.
    expect(chrome).not.toMatch(
      /ccHeaderAddressColumnSx[\s\S]{0,400}maxWidth:\s*\{\s*[^}]*md:\s*['"]\d+rem['"]/,
    )
    expect(chrome).not.toMatch(/ml:\s*\{\s*md:\s*['"]auto['"]\s*\}/)
    expect(chrome).not.toMatch(/ccHeaderTrailingPanelsSx[\s\S]{0,200}flexShrink:\s*0/)
    expect(chrome).not.toMatch(/ccHeaderTrailingPanelsSx[\s\S]{0,300}width:\s*\{\s*md:\s*368/)
    expect(score).toMatch(/clamp\(10rem,\s*13vw,\s*260px\)/)
    expect(condo).toMatch(/clamp\(10rem,\s*13vw,\s*260px\)/)
    expect(score).toMatch(/py:\s*1/)
    expect(score).toMatch(/px:\s*1\.75/)
    expect(score).toMatch(/limit\s*=\s*2/)
    expect(score).not.toMatch(
      /header-score-drivers[\s\S]{0,1200}textOverflow:\s*['"]ellipsis['"]/,
    )
  })
})
