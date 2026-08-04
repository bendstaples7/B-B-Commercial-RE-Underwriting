#!/usr/bin/env node
/**
 * Authenticated live UI snapshot — real app route, not a harness.
 *
 * Usage:
 *   node scripts/live-ui/snapshot.mjs --url /leads/10305 --selector '[data-testid="property-overview-header"]' --label cc-header
 *   node scripts/live-ui/snapshot.mjs --url http://localhost:3000/leads/10305 --cdp http://127.0.0.1:9222
 *
 * Auth (first match wins with --cdp taking precedence for capture):
 *   --cdp URL          attach to Chromium with remote debugging (already logged in)
 *   session-export / BB_E2E_SESSION_TOKEN / BB_E2E_EMAIL+PASSWORD
 *
 * Writes:
 *   artifacts/live-ui/<stamp>-<label>.png
 *   artifacts/live-ui/<stamp>-<label>.json
 *
 * Agent MUST Read the PNG before claiming UI done (live-ui-visibility skill).
 */
import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  ARTIFACT_DIR,
  assertNotLoginWall,
  baseUrl,
  collectMetricsFn,
  ensureDirs,
  getPlaywright,
  injectSession,
  loadDotEnvFiles,
  resolveSession,
  slug,
  stamp,
} from './lib.mjs'

function parseArgs(argv) {
  const out = {
    url: null,
    selector: '[data-live-ui-surface], [data-testid="property-overview-header"], main, #root',
    label: 'surface',
    width: 1280,
    height: 900,
    cdp: null,
    fullPage: false,
  }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => argv[++i]
    if (a === '--url') out.url = next()
    else if (a === '--selector') out.selector = next()
    else if (a === '--label') out.label = next()
    else if (a === '--width') out.width = Number(next())
    else if (a === '--height') out.height = Number(next())
    else if (a === '--cdp') out.cdp = next()
    else if (a === '--full-page') out.fullPage = true
    else if (a === '--help' || a === '-h') out.help = true
  }
  return out
}

function resolveTargetUrl(raw) {
  if (!raw) throw new Error('--url is required (path or absolute)')
  if (/^https?:\/\//i.test(raw)) return raw
  const path = raw.startsWith('/') ? raw : `/${raw}`
  return `${baseUrl()}${path}`
}

async function pickSelector(page, selectorList) {
  const parts = selectorList.split(',').map((s) => s.trim()).filter(Boolean)
  for (const sel of parts) {
    const handle = await page.$(sel)
    if (handle) return sel
  }
  return parts[0]
}

async function main() {
  loadDotEnvFiles()
  ensureDirs()
  const args = parseArgs(process.argv.slice(2))
  if (args.help) {
    console.log(`Usage: node scripts/live-ui/snapshot.mjs --url /leads/10305 [options]
  --selector CSS     (default: data-live-ui-surface / property-overview-header / main)
  --label name       artifact label
  --width/--height   viewport (ignored for --cdp unless new page)
  --cdp URL          connectOverCDP to logged-in Chromium
  --full-page        screenshot full page instead of selector`)
    process.exit(0)
  }

  const targetUrl = resolveTargetUrl(args.url)
  const { chromium } = getPlaywright()
  const id = `${stamp()}-${slug(args.label)}`
  const pngPath = resolve(ARTIFACT_DIR, `${id}.png`)
  const jsonPath = resolve(ARTIFACT_DIR, `${id}.json`)

  let browser
  let context
  let page
  let channel = 'auth-playwright'
  let closeBrowser = true

  try {
    if (args.cdp) {
      channel = 'chromium-session'
      browser = await chromium.connectOverCDP(args.cdp)
      closeBrowser = false
      context = browser.contexts()[0]
      if (!context) throw new Error('CDP connected but no browser context')
      page =
        context.pages().find((p) => /localhost|127\.0\.0\.1/.test(p.url())) ||
        context.pages()[0] ||
        (await context.newPage())
      if (!page.url().includes(new URL(targetUrl).pathname.split('?')[0].slice(0, 24))) {
        await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 120000 })
      }
    } else {
      const session = await resolveSession()
      browser = await chromium.launch({ headless: true })
      context = await browser.newContext({
        viewport: { width: args.width, height: args.height },
        baseURL: baseUrl(),
      })
      page = await context.newPage()
      await injectSession(page, session)
      await page.goto(targetUrl, { waitUntil: 'networkidle', timeout: 120000 })
      channel = `auth-playwright:${session.source}`
    }

    await page.waitForTimeout(800)
    assertNotLoginWall(page.url(), { loginWall: /\/login/i.test(page.url()) })

    const selector = await pickSelector(page, args.selector)
    await page.waitForSelector(selector, { state: 'visible', timeout: 60000 }).catch(() => {
      throw new Error(`Selector not visible: ${selector} (url=${page.url()})`)
    })

    const metrics = await page.evaluate(collectMetricsFn(), selector)
    assertNotLoginWall(page.url(), metrics)

    if (args.fullPage) {
      await page.screenshot({ path: pngPath, fullPage: true })
    } else {
      const el = await page.$(selector)
      if (!el) throw new Error(`Element gone before screenshot: ${selector}`)
      await el.screenshot({ path: pngPath })
    }

    const report = {
      ok: true,
      channel,
      label: args.label,
      targetUrl,
      finalUrl: page.url(),
      selector,
      png: pngPath,
      json: jsonPath,
      viewport: { width: args.width, height: args.height },
      metrics,
      capturedAt: new Date().toISOString(),
    }
    writeFileSync(jsonPath, JSON.stringify(report, null, 2), 'utf8')
    console.log(JSON.stringify(report, null, 2))

    if (metrics.clippedCount > 0) {
      console.error(
        `WARN: ${metrics.clippedCount} child testids clipped by root: ${metrics.clippedTestIds.join(', ')}`,
      )
      process.exitCode = 2
    }
  } finally {
    if (closeBrowser && browser) await browser.close()
    else if (browser && args.cdp) {
      // leave user's Chromium running; disconnect only
      try {
        await browser.close()
      } catch {
        /* CDP disconnect */
      }
    }
  }
}

main().catch((err) => {
  console.error(err.message || err)
  process.exit(1)
})
