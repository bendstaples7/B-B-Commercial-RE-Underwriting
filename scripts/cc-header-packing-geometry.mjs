#!/usr/bin/env node
/**
 * Hostile CC header packing geometry gate — REAL React/MUI harness (Vite).
 *
 * Runs at multiple viewport widths (1280 / 1440 / 1600 / 1920) and fails if:
 * - address → Est. value gap is a dead middle ( > GAP_MAX_PX )
 * - KPI band → condo/score canyon ( > GAP_MAX_PX ) from ml:auto park
 * - back / address / KPIs / condo / score are not on one horizontal row (md+)
 * - address / KPIs / condo / score boxes pairwise overlap
 * - Units/details paints over Category (boxes + elementFromPoint)
 * - trail panels clip past the header card edge
 * - address is ellipsized at 1440+
 * - header screenshot is vacuous / missing
 * - all measured boxes are vacuous zeros
 *
 * Usage:
 *   node scripts/cc-header-packing-geometry.mjs
 *
 * Requires: playwright + vite under frontend/; chromium installed.
 */
import { createRequire } from 'node:module'
import { mkdirSync, existsSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, '..')
const FRONTEND = resolve(REPO_ROOT, 'frontend')
const ARTIFACT_DIR = resolve(REPO_ROOT, 'artifacts')
const require = createRequire(resolve(FRONTEND, 'package.json'))

const GAP_MAX_PX = 48
const ROW_TOP_EPS = 28
const OVERLAP_EPS = 1
const VIEWPORTS = [
  { width: 1280, height: 900 },
  { width: 1440, height: 900 },
  { width: 1600, height: 900 },
  { width: 1920, height: 900 },
]

function overlaps(a, b) {
  const x = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return x > OVERLAP_EPS && y > OVERLAP_EPS
}

function fail(viewport, msg, detail) {
  console.error(`[${viewport.width}x${viewport.height}] ${msg}`, detail ?? '')
  process.exit(1)
}

function assertScreenshot(viewport, path, label) {
  if (!existsSync(path)) {
    fail(viewport, `Screenshot veto: missing ${path}`)
  }
  const bytes = statSync(path).size
  if (bytes < 4000) {
    fail(viewport, `Screenshot veto: ${label} PNG too small (${bytes} bytes) — likely blank`)
  }
  return bytes
}

async function startViteHarness() {
  const vitePath = resolve(FRONTEND, 'node_modules/vite/dist/node/index.js')
  const { createServer } = await import(pathToFileURL(vitePath).href)
  const server = await createServer({
    configFile: resolve(FRONTEND, 'vite.config.ts'),
    root: FRONTEND,
    server: { port: 0, strictPort: false, host: '127.0.0.1' },
    logLevel: 'error',
  })
  await server.listen()
  const urls = server.resolvedUrls?.local
  const base = urls?.[0] || `http://127.0.0.1:${server.config.server.port}/`
  return {
    server,
    harnessUrl: new URL('/cc-header-packing-harness.html', base).href,
  }
}

async function collectMetrics(page) {
  return page.evaluate(() => {
    const rectOf = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const r = el.getBoundingClientRect()
      return {
        left: r.left,
        right: r.right,
        top: r.top,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      }
    }
    const closestTestId = (x, y) => {
      const el = document.elementFromPoint(x, y)
      if (!el) return null
      const host = el.closest('[data-testid]')
      return host?.getAttribute('data-testid') ?? null
    }
    const sampleGrid = (box, testIdPrefix) => {
      if (!box || box.width < 2 || box.height < 2) return { hits: 0, misses: [], total: 0 }
      const pts = [
        [0.25, 0.25],
        [0.5, 0.5],
        [0.75, 0.75],
        [0.25, 0.75],
        [0.75, 0.25],
      ]
      const misses = []
      let hits = 0
      for (const [fx, fy] of pts) {
        const x = box.left + box.width * fx
        const y = box.top + box.height * fy
        const id = closestTestId(x, y)
        if (id && id.startsWith(testIdPrefix)) hits += 1
        else misses.push({ x, y, id })
      }
      return { hits, misses, total: pts.length }
    }

    const trail = document.querySelector('[data-testid="cc-header-trailing-panels"]')
    const unitsValue = rectOf('[data-testid="quick-stat-units-details-value"]')
    const categoryCell = rectOf('[data-testid="quick-stat-category"]')
    const unitsCell = rectOf('[data-testid="quick-stat-units-details"]')
    const addressLineEl =
      document.querySelector('[data-testid="property-overview-address-line"]')
      || document.querySelector('[data-testid="property-overview-address"]')
    const addressLineText = (addressLineEl?.textContent || '').replace(/\s+/g, ' ').trim()
    const addressCs = addressLineEl ? getComputedStyle(addressLineEl) : null
    const addressRect = addressLineEl ? addressLineEl.getBoundingClientRect() : null
    const addressLh = addressCs ? parseFloat(addressCs.lineHeight) || 27 : 27
    const addressApproxLines = addressRect
      ? Math.round((addressRect.height / addressLh) * 10) / 10
      : null
    const addressScrollWider = addressLineEl
      ? addressLineEl.scrollWidth > addressLineEl.clientWidth + 2
      : false

    const driverChips = [
      ...document.querySelectorAll('[data-testid="header-score-drivers"] .MuiChip-label'),
    ]
    const driverReport = driverChips.map((el) => {
      const cs = getComputedStyle(el)
      return {
        text: (el.textContent || '').trim(),
        whiteSpace: cs.whiteSpace,
        textOverflow: cs.textOverflow,
        scrollWider: el.scrollWidth > el.clientWidth + 2,
      }
    })

    const condoVerdict =
      document.querySelector('[data-testid="header-condo-verdict"]')?.textContent?.trim()
      || ''

    return {
      header: rectOf('[data-testid="property-overview-header"]'),
      back: rectOf('[data-testid="back-button"], [aria-label="Go back"], [aria-label="Back"]'),
      address: rectOf('[data-testid="property-overview-address"]'),
      est: rectOf('[data-testid="quick-stat-est-value"]'),
      lastSale: rectOf('[data-testid="quick-stat-last-sale"]'),
      stats: rectOf('[data-testid="property-overview-quick-stats"]'),
      condo: rectOf('[data-testid="header-condo-check"]'),
      score: rectOf('[data-testid="header-lead-score"]'),
      trail: rectOf('[data-testid="cc-header-trailing-panels"]'),
      unitsCell,
      categoryCell,
      unitsValue,
      categoryValue: rectOf('[data-testid="quick-stat-category-value"]'),
      statsInsideTrail: trail
        ? Boolean(trail.querySelector('[data-testid="property-overview-quick-stats"]'))
        : true,
      unitsPaint: sampleGrid(unitsCell, 'quick-stat-units'),
      categoryPaint: sampleGrid(categoryCell, 'quick-stat-category'),
      unitsValueText: document.querySelector('[data-testid="quick-stat-units-details-value"]')
        ?.textContent ?? '',
      addressLineText,
      addressWhiteSpace: addressCs?.whiteSpace ?? null,
      addressTextOverflow: addressCs?.textOverflow ?? null,
      addressApproxLines,
      addressScrollWider,
      driverCount: driverChips.length,
      driverReport,
      condoVerdict,
      kpiBand: document
        .querySelector('[data-testid="property-overview-quick-stats"]')
        ?.getAttribute('data-cc-kpi-band'),
      trailMode: trail?.getAttribute('data-cc-trail-mode'),
      fixture: document
        .querySelector('[data-testid="property-overview-header"]')
        ?.getAttribute('data-cc-fixture'),
    }
  })
}

async function assertViewport(page, viewport) {
  const metrics = await collectMetrics(page)
  mkdirSync(ARTIFACT_DIR, { recursive: true })
  const shotPath = resolve(ARTIFACT_DIR, `cc-header-packing-${viewport.width}.png`)
  const canonicalShotPath = resolve(ARTIFACT_DIR, 'cc-header-packing.png')
  await page.getByTestId('property-overview-header').screenshot({ path: shotPath })
  // Keep canonical name for the narrowest width (CI consumers).
  if (viewport.width === 1280) {
    await page
      .getByTestId('property-overview-header')
      .screenshot({ path: canonicalShotPath })
  }

  const { back, address, est, stats, condo, score, header } = metrics
  if (!back || !address || !est || !stats || !condo || !score || !metrics.unitsCell || !metrics.categoryCell) {
    fail(viewport, 'Missing landmark boxes', metrics)
  }

  const allZero = [address, est, stats, condo, score].every(
    (b) => b.width === 0 && b.height === 0,
  )
  if (allZero) fail(viewport, 'Vacuous zero-sized boxes — refusing ALIGNED')

  if (metrics.statsInsideTrail) {
    fail(viewport, 'FORBID: quick-stats inside trailing ml:auto pack')
  }

  const gap = est.left - address.right
  if (gap > GAP_MAX_PX) {
    fail(viewport, `Dead middle: address→Est gap ${gap.toFixed(1)}px > ${GAP_MAX_PX}`)
  }
  if (gap < -OVERLAP_EPS) {
    fail(viewport, `Overlap: address and Est value overlap by ${(-gap).toFixed(1)}px`)
  }

  // ONE horizontal row: address, KPIs, condo, score tops within epsilon.
  const rowTops = [address.top, stats.top, condo.top, score.top]
  const topMin = Math.min(...rowTops)
  const topMax = Math.max(...rowTops)
  if (topMax - topMin > ROW_TOP_EPS) {
    fail(viewport, `Not one horizontal row — top spread ${(topMax - topMin).toFixed(1)}px`, {
      addressTop: address.top,
      statsTop: stats.top,
      condoTop: condo.top,
      scoreTop: score.top,
    })
  }

  const canyon = condo.left - stats.right
  if (canyon > GAP_MAX_PX) {
    fail(viewport, `KPI→trail canyon: stats.right→condo ${canyon.toFixed(1)}px > ${GAP_MAX_PX}`)
  }
  if (back.right > address.left + OVERLAP_EPS) {
    fail(viewport, 'Back button must sit before the address cluster without overlap', {
      back,
      address,
    })
  }

  // Lead Signals must sit flush right — no leftover whitespace after the score card.
  if (header && score) {
    const afterScore = header.right - score.right
    const FLUSH_MAX_PX = 28 // header padding (~12–16) + epsilon
    if (afterScore > FLUSH_MAX_PX) {
      fail(
        viewport,
        `Score not flush right: ${afterScore.toFixed(1)}px trailing gap > ${FLUSH_MAX_PX}`,
      )
    }
  }

  const named = [
    ['back', back],
    ['address', address],
    ['stats', stats],
    ['condo', condo],
    ['score', score],
  ]
  for (let i = 0; i < named.length; i++) {
    for (let j = i + 1; j < named.length; j++) {
      const [na, a] = named[i]
      const [nb, b] = named[j]
      if (overlaps(a, b)) fail(viewport, `Overlap between ${na} and ${nb}`, { a, b })
    }
  }

  if (overlaps(metrics.unitsCell, metrics.categoryCell)) {
    fail(viewport, 'Overlap: Units cell vs Category cell', {
      units: metrics.unitsCell,
      category: metrics.categoryCell,
    })
  }
  if (
    metrics.unitsValue
    && metrics.categoryValue
    && overlaps(metrics.unitsValue, metrics.categoryValue)
  ) {
    fail(viewport, 'Overlap: Units value vs Category value')
  }
  if (metrics.unitsValue && overlaps(metrics.unitsValue, condo)) {
    fail(viewport, 'Overlap: Units value vs Condo panel')
  }
  if (
    metrics.unitsValue
    && metrics.unitsValue.right > metrics.unitsCell.right + OVERLAP_EPS + 2
  ) {
    fail(
      viewport,
      `Units value spills past cell: value.right=${metrics.unitsValue.right.toFixed(1)} cell.right=${metrics.unitsCell.right.toFixed(1)}`,
    )
  }

  // Clip past header card edge.
  if (header) {
    const clipEps = 2
    for (const [name, box] of [
      ['condo', condo],
      ['score', score],
      ['stats', stats],
    ]) {
      if (box.right > header.right + clipEps) {
        fail(
          viewport,
          `${name} clips past header right edge (${box.right.toFixed(1)} > ${header.right.toFixed(1)})`,
        )
      }
      if (box.left < header.left - clipEps) {
        fail(
          viewport,
          `${name} clips past header left edge (${box.left.toFixed(1)} < ${header.left.toFixed(1)})`,
        )
      }
    }
  }

  if (!/12\s*Units/i.test(metrics.unitsValueText) || metrics.unitsValueText.length < 20) {
    fail(viewport, 'Hostile Units fixture too short — gate would be theater', metrics.unitsValueText)
  }

  if (metrics.categoryPaint.hits < metrics.categoryPaint.total) {
    fail(viewport, 'Paint veto: Category cell samples missed Category tree', metrics.categoryPaint)
  }
  if (metrics.unitsPaint.hits < metrics.unitsPaint.total) {
    fail(viewport, 'Paint veto: Units cell samples missed Units tree', metrics.unitsPaint)
  }

  const bytes = assertScreenshot(viewport, shotPath, 'header')
  if (viewport.width === 1280) {
    assertScreenshot(viewport, canonicalShotPath, 'canonical header')
  }

  const bleed = await page.evaluate(() => {
    const cat = document.querySelector('[data-testid="quick-stat-category"]')
    const unitsVal = document.querySelector('[data-testid="quick-stat-units-details-value"]')
    if (!cat || !unitsVal) return { bad: true, reason: 'missing' }
    const cr = cat.getBoundingClientRect()
    const ur = unitsVal.getBoundingClientRect()
    const x = Math.min(cr.right, ur.right) - Math.max(cr.left, ur.left)
    const y = Math.min(cr.bottom, ur.bottom) - Math.max(cr.top, ur.top)
    return { bad: x > 1 && y > 1, overlapX: x, overlapY: y }
  })
  if (bleed.bad) {
    fail(viewport, 'Paint veto: Units value rect intersects Category cell', bleed)
  }

  const addr = metrics.addressLineText || ''
  if (!/Hoyne/i.test(addr) || !/60622/.test(addr)) {
    fail(viewport, 'Address readability fail — expected full Hoyne + ZIP', addr)
  }
  if (/\.\.\.|…\s*$/.test(addr) || /Chicago,\s*I\.\.\./i.test(addr)) {
    fail(viewport, 'Address ellipsis crush detected in DOM text', addr)
  }
  if (metrics.addressWhiteSpace !== 'nowrap') {
    fail(
      viewport,
      `FORBID: hero address must be nowrap at desktop (got ${metrics.addressWhiteSpace})`,
    )
  }
  if (metrics.addressApproxLines != null && metrics.addressApproxLines > 1.35) {
    fail(viewport, `Address wraps — expected ~1 line (got ${metrics.addressApproxLines})`)
  }
  // Plan lock: address must not ellipsize at 1440+.
  if (viewport.width >= 1440 && metrics.addressScrollWider) {
    fail(
      viewport,
      'Address truncated (scrollWidth > clientWidth) at ≥1440 — must fit one line',
    )
  }

  if (metrics.driverCount > 2) {
    fail(viewport, `Score drivers exceed max 2 (got ${metrics.driverCount})`, metrics.driverReport)
  }
  if (metrics.driverCount < 1) {
    fail(viewport, 'Hostile fixture missing score drivers')
  }
  for (const d of metrics.driverReport) {
    if (d.textOverflow === 'ellipsis' && d.whiteSpace === 'nowrap') {
      fail(viewport, 'Score driver chip still nowrap+ellipsis', d)
    }
    if (d.scrollWider && d.textOverflow === 'ellipsis') {
      fail(viewport, 'Score driver label truncated via ellipsis', d)
    }
    if (/\.\.\.|…/.test(d.text) && d.text.length < 12) {
      fail(viewport, 'Score driver looks truncated in DOM text', d)
    }
  }

  if (!/Checking/i.test(metrics.condoVerdict || '')) {
    fail(viewport, 'Condo verdict missing Checking… (hostile pending fixture)', metrics.condoVerdict)
  }

  return {
    ok: true,
    viewport,
    gapPx: Number(gap.toFixed(2)),
    canyonPx: Number(canyon.toFixed(2)),
    rowTopSpreadPx: Number((topMax - topMin).toFixed(2)),
    addressWidth: Number(address.width.toFixed(2)),
    condoWidth: Number(condo.width.toFixed(2)),
    scoreWidth: Number(score.width.toFixed(2)),
    addressLineText: metrics.addressLineText,
    addressApproxLines: metrics.addressApproxLines,
    addressScrollWider: metrics.addressScrollWider,
    screenshotBytes: bytes,
    screenshotPath: shotPath,
  }
}

const SYMMETRY_MAX_PX = 32

async function assertResidentialViewport(page, viewport) {
  const metrics = await collectMetrics(page)
  mkdirSync(ARTIFACT_DIR, { recursive: true })
  const shotPath = resolve(ARTIFACT_DIR, `cc-header-packing-residential-${viewport.width}.png`)
  await page.getByTestId('property-overview-header').screenshot({ path: shotPath })

  const { back, address, est, stats, score, header } = metrics
  if (!back || !address || !est || !stats || !score) {
    fail(viewport, 'Residential: missing landmark boxes', metrics)
  }
  if (metrics.condo) {
    fail(viewport, 'Residential fixture must not show condo panel')
  }
  if (metrics.fixture !== 'residential') {
    fail(viewport, `Expected residential fixture (got ${metrics.fixture ?? 'missing'})`, metrics)
  }
  if (metrics.kpiBand !== 'centered-residential') {
    fail(viewport, `Expected data-cc-kpi-band=centered-residential (got ${metrics.kpiBand})`)
  }
  if (metrics.trailMode !== 'grow-score') {
    fail(viewport, `Expected trail grow-score (got ${metrics.trailMode})`)
  }
  // Match main: score uses clamp(10rem, 13vw, 260px) grow — not content-hug.
  const SCORE_MIN_PX = 160
  if (score.width < SCORE_MIN_PX) {
    fail(viewport, `Residential score too narrow vs main clamp: ${score.width.toFixed(1)}px < ${SCORE_MIN_PX}`)
  }

  // Optical center of KPI grid ≈ midpoint of address.right and score.left
  const spanMid = (address.right + score.left) / 2
  const kpiMid = (stats.left + stats.right) / 2
  // Prefer est+lastSale block midpoint when available (hug-width grid inside band)
  const gridLeft = est.left
  const gridRight = metrics.lastSale ? metrics.lastSale.right : est.right
  const gridMid = (gridLeft + gridRight) / 2
  const skew = Math.abs(gridMid - spanMid)
  if (skew > SYMMETRY_MAX_PX) {
    fail(
      viewport,
      `Residential KPI not centered: |gridMid-spanMid|=${skew.toFixed(1)}px > ${SYMMETRY_MAX_PX}`,
      { spanMid, gridMid, kpiMid, addressRight: address.right, scoreLeft: score.left },
    )
  }

  // Forbid left-parked KPIs: left gap much smaller than right gap while slack exists
  const leftGap = Math.max(0, est.left - address.right)
  const rightGap = Math.max(0, score.left - (metrics.lastSale?.right ?? stats.right))
  const slack = leftGap + rightGap
  if (slack > 80 && leftGap < 16 && rightGap > leftGap * 3) {
    fail(viewport, `Left-parked KPIs: leftGap=${leftGap.toFixed(1)} rightGap=${rightGap.toFixed(1)}`)
  }

  // alignItems:center → tops differ when score is taller than the 2×2; compare midlines.
  const statsMidY = (stats.top + stats.bottom) / 2
  const scoreMidY = (score.top + score.bottom) / 2
  if (Math.abs(statsMidY - scoreMidY) > ROW_TOP_EPS) {
    fail(viewport, 'Residential: KPIs and score not vertically centered on one row', {
      statsTop: stats.top,
      scoreTop: score.top,
      statsMidY,
      scoreMidY,
      addressTop: address.top,
    })
  }
  // Address may be taller (status chip); require vertical overlap with KPI band.
  if (address.bottom < stats.top + OVERLAP_EPS || address.top > stats.bottom - OVERLAP_EPS) {
    fail(viewport, 'Residential: address and KPI band must share the header row')
  }

  if (header && score) {
    const afterScore = header.right - score.right
    // Paper padding (~12–16); trail grows with score clamp like main.
    const FLUSH_MAX_PX = 40
    if (afterScore > FLUSH_MAX_PX) {
      fail(viewport, `Residential score not flush right: ${afterScore.toFixed(1)}px`)
    }
  }

  if (!/Gresham/i.test(metrics.addressLineText || '')) {
    fail(viewport, 'Residential address missing Gresham', metrics.addressLineText)
  }

  assertScreenshot(viewport, shotPath, 'residential header')

  return {
    ok: true,
    fixture: metrics.fixture,
    viewport,
    symmetrySkewPx: Number(skew.toFixed(2)),
    leftGapPx: Number(leftGap.toFixed(2)),
    rightGapPx: Number(rightGap.toFixed(2)),
    screenshotPath: shotPath,
  }
}

async function main() {
  let chromium
  try {
    ;({ chromium } = require(resolve(FRONTEND, 'node_modules/playwright')))
  } catch (err) {
    console.error('playwright not found under frontend/node_modules', err)
    process.exit(1)
  }

  const { server, harnessUrl } = await startViteHarness()
  const browser = await chromium.launch({ headless: true })
  const results = []
  const residentialResults = []
  try {
    for (const viewport of VIEWPORTS) {
      const page = await browser.newPage({ viewport })
      const pageErrors = []
      page.on('pageerror', (e) => pageErrors.push(String(e)))

      await page.goto(harnessUrl, { waitUntil: 'networkidle', timeout: 120000 })
      await page.getByTestId('property-overview-header').waitFor({ state: 'visible', timeout: 60000 })
      await page.getByTestId('quick-stat-units-details-value').waitFor({ state: 'visible' })

      if (pageErrors.length) {
        console.error(`[${viewport.width}] Harness page errors:`, pageErrors)
        process.exit(1)
      }

      const result = await assertViewport(page, viewport)
      results.push(result)
      await page.close()
    }

    for (const viewport of VIEWPORTS) {
      const page = await browser.newPage({ viewport })
      const pageErrors = []
      page.on('pageerror', (e) => pageErrors.push(String(e)))
      const residentialUrl = new URL(harnessUrl)
      residentialUrl.searchParams.set('fixture', 'residential')
      await page.goto(residentialUrl.href, { waitUntil: 'networkidle', timeout: 120000 })
      await page.getByTestId('property-overview-header').waitFor({ state: 'visible', timeout: 60000 })
      if (pageErrors.length) {
        console.error(`[${viewport.width}] Residential harness page errors:`, pageErrors)
        process.exit(1)
      }
      const resResult = await assertResidentialViewport(page, viewport)
      residentialResults.push(resResult)
      await page.close()
    }

    console.log(
      JSON.stringify(
        {
          ok: true,
          mode: 'real-react-mui-multi-width',
          visible: true,
          viewports: results,
          residentialViewports: residentialResults,
        },
        null,
        2,
      ),
    )
  } finally {
    await browser.close()
    await server.close()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
