#!/usr/bin/env node
/**
 * Lead Command Center mount smoke — regression gate for blank /leads/:id.
 *
 * After a production build, open a lead and fail closed unless the SPA both
 * requests command-center AND paints a lead landmark (not API-only).
 *
 *   node scripts/lead-cc-mount-smoke.mjs --dir frontend/dist
 *
 * Fails if:
 *   - pageerror
 *   - #root empty
 *   - zero GET /api/leads/:id/command-center after open
 *   - no lead landmark (property street / Loading lead never clears)
 */
import { createServer } from 'node:http'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { join, extname, resolve, dirname, sep } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, '..')

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
}

function parseArgs(argv) {
  const out = { dir: 'frontend/dist', lead: '643', timeoutMs: 25000 }
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--dir') out.dir = argv[++i]
    else if (a === '--lead') out.lead = argv[++i]
    else if (a === '--timeout-ms') out.timeoutMs = Number(argv[++i])
  }
  return out
}

function b64url(obj) {
  const json = Buffer.from(JSON.stringify(obj)).toString('base64')
  return json.replace(/=+$/g, '').replace(/\+/g, '-').replace(/\//g, '_')
}

function makeToken() {
  const now = Math.floor(Date.now() / 1000)
  return `${b64url({ alg: 'none', typ: 'JWT' })}.${b64url({
    sub: 'smoke-user',
    email: 'smoke@example.com',
    display_name: 'Smoke User',
    is_admin: true,
    iat: now,
    exp: now + 3600,
  })}.smoke`
}

function ccPayload(leadId) {
  const path = resolve(REPO_ROOT, `artifacts/cc${leadId}.json`)
  if (existsSync(path)) {
    try {
      return JSON.parse(readFileSync(path, 'utf8'))
    } catch {
      // fall through
    }
  }
  return {
    id: leadId,
    property_street: '2915 N Hamlin Ave',
    property_city: 'Chicago',
    property_state: 'IL',
    property_zip: '60618',
    owner_first_name: 'Julian',
    owner_last_name: 'Shin',
    lead_status: 'in_person_appointment',
    lead_score: 100,
    lead_category: 'residential',
    emails: ['smoke@example.com'],
    phones: ['(630) 555-0100'],
    contacts: [],
    organizations: [],
    open_tasks: [],
    work_queues: [{ key: 'todays-action', label: "Today's Action" }],
    recommended_action: {
      value: 'call_ready',
      label: 'Call ready',
      explanation: null,
      recommended_contact_method: 'phone',
      outreach_contact: null,
      winning_rule: null,
      winning_rule_label: null,
      signals: {},
    },
    timeline: { entries: [], total: 0 },
    mailer_history_summary: { count: 0, last_sent_at: null, rows: [] },
    sale_history: [],
  }
}

function startServer(dir, payload) {
  const root = resolve(dir)
  const rootPrefix = root.endsWith(sep) ? root : root + sep
  const leadId = Number(payload.id) || 643
  const server = createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || '/').split('?')[0])
    if (urlPath.startsWith('/api/')) {
      const json = (body, status = 200) => {
        res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
        res.end(JSON.stringify(body))
      }
      if (urlPath === '/api/health' || urlPath === '/api/health/runtime') {
        return json({ status: 'ok', source_stale: false, build_id: 'smoke' })
      }
      if (urlPath === '/api/queues/counts') return json({})
      if (urlPath === '/api/hubspot/pipeline/status') {
        return json({
          pipeline_running: false,
          matches: { total: 0, high: 0, medium: 0, unmatched: 0 },
          interactions: 0,
          tasks: 0,
          signals: 0,
        })
      }
      if (urlPath === `/api/leads/${leadId}/command-center` && req.method === 'GET') {
        return json(payload)
      }
      if (urlPath.includes('/navigation')) {
        return json({ position: 1, total: 1, prev_id: null, next_id: null })
      }
      if (urlPath.startsWith('/api/lead-scores/')) return json({ latest: null, history: [] })
      if (urlPath.startsWith('/api/properties/')) {
        return json({ id: leadId, property_street: payload.property_street })
      }
      return json({ ok: true })
    }
    const rel = urlPath === '/' ? 'index.html' : urlPath.replace(/^\/+/, '')
    let filePath = resolve(root, rel)
    if (
      (filePath !== root && !filePath.startsWith(rootPrefix))
      || !existsSync(filePath)
      || statSync(filePath).isDirectory()
    ) {
      filePath = join(root, 'index.html')
    }
    try {
      const body = readFileSync(filePath)
      res.writeHead(200, {
        'Content-Type': MIME[extname(filePath)] || 'application/octet-stream',
        'Cache-Control': 'no-store',
      })
      res.end(body)
    } catch {
      res.writeHead(404)
      res.end('not found')
    }
  })
  return new Promise((resolvePromise) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      resolvePromise({ server, baseUrl: `http://127.0.0.1:${port}` })
    })
  })
}

async function loadPlaywright() {
  const candidates = [
    resolve(REPO_ROOT, 'frontend/node_modules/playwright/index.mjs'),
    resolve(REPO_ROOT, 'frontend/node_modules/playwright/index.js'),
  ]
  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue
    return await import(pathToFileURL(candidate).href)
  }
  return await import('playwright')
}

async function main() {
  const args = parseArgs(process.argv)
  // Prefer cwd (CI runs from frontend/ with --dir dist), then repo-root paths.
  const candidates = [
    resolve(args.dir),
    resolve(REPO_ROOT, args.dir),
    resolve(REPO_ROOT, 'frontend', args.dir),
  ]
  const dir =
    candidates.find((c) => existsSync(join(c, 'index.html'))) || candidates[0]
  if (!existsSync(join(dir, 'index.html'))) {
    console.error(`lead-cc-mount-smoke FAILED: missing ${join(dir, 'index.html')}`)
    process.exit(2)
  }
  const payload = ccPayload(Number(args.lead))
  const streetNeedle = String(payload.property_street || '').trim()
  const { server, baseUrl } = await startServer(dir, payload)
  const { chromium } = await loadPlaywright()
  const pageErrors = []
  const apiHits = []
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage()
    page.on('pageerror', (err) => pageErrors.push(err.stack || String(err)))
    page.on('request', (req) => {
      if (req.url().includes('/api/')) apiHits.push(req.url())
    })
    await page.addInitScript((t) => {
      localStorage.setItem('session_token', t)
      localStorage.setItem('user_id', 'smoke-user')
    }, makeToken())

    const target = `${baseUrl}/leads/${args.lead}?queue=todays-action`
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: args.timeoutMs })

    // Wait until loading spinner is gone and street landmark is visible (or timeout).
    try {
      await page.waitForFunction(
        (street) => {
          const loading = document.querySelector('[aria-label="Loading lead"]')
          if (loading) return false
          const text = (document.body && document.body.innerText) || ''
          return Boolean(street) && text.includes(street)
        },
        streetNeedle,
        { timeout: Math.min(args.timeoutMs, 15000) },
      )
    } catch {
      // Collected below via landmark checks.
    }

    const leadIdForApi = String(Number(payload.id) || Number(args.lead) || 643)
    const rootKids = await page.$eval('#root', (el) => el.childElementCount).catch(() => 0)
    const ccHits = apiHits.filter((u) => {
      try {
        const path = new URL(u).pathname
        return path === `/api/leads/${leadIdForApi}/command-center`
      } catch {
        return u.includes(`/api/leads/${leadIdForApi}/command-center`)
      }
    })
    const loadingCount = await page.locator('[aria-label="Loading lead"]').count()
    const bodyText = await page.evaluate(() => (document.body && document.body.innerText) || '')
    const hasStreetLandmark = Boolean(streetNeedle) && bodyText.includes(streetNeedle)
    const errorBoundaryVisible = await page
      .locator('[data-testid="lead-command-center-error-boundary"]')
      .count()
      .then((n) => n > 0)
      .catch(() => false)

    const failing = []
    if (rootKids < 1) failing.push('#root has no children')
    if (!ccHits.length) failing.push('no GET /api/leads/*/command-center after lead open')
    if (loadingCount > 0) failing.push('Loading lead spinner still visible')
    if (!hasStreetLandmark) {
      failing.push(
        `no lead landmark (expected property street ${JSON.stringify(streetNeedle)} in body)`,
      )
    }
    if (errorBoundaryVisible) failing.push('lead ErrorBoundary visible (render throw)')
    for (const e of pageErrors) failing.push(`pageerror: ${e}`)

    if (failing.length) {
      console.error('lead-cc-mount-smoke FAILED')
      for (const f of failing) console.error(`  - ${f}`)
      process.exitCode = 1
    } else {
      console.log(
        `lead-cc-mount-smoke OK: ${target} (command-center hits=${ccHits.length}, #root children=${rootKids}, landmark=${streetNeedle})`,
      )
    }
  } finally {
    await browser.close()
    server.close()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
