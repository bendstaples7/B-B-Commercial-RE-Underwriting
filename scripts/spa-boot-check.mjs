#!/usr/bin/env node
/**
 * Headless SPA boot gate — fail on pageerror / white #root.
 *
 * Usage:
 *   node scripts/spa-boot-check.mjs --url https://example.com/login
 *   node scripts/spa-boot-check.mjs --dir frontend/dist --path /login
 *
 * Modes:
 *   --dir  (CI/local): fail on any pageerror
 *   --url  (prod): fail only on boot-killer errors + empty #root / watchdog
 *
 * Requires: playwright (frontend devDependency). Then:
 *   npx playwright install --with-deps chromium
 *
 * Exits 0 on success, 1 on boot failure.
 */
import { createServer } from 'node:http'
import { readFileSync, existsSync, statSync } from 'node:fs'
import { join, extname, resolve, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(SCRIPT_DIR, '..')

const BOOT_KILLER_RE =
  /createContext|Cannot read properties of undefined|is not a function|Unexpected token/i

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
  const out = { url: null, dir: null, path: '/login', timeoutMs: 20000 }
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--url') out.url = argv[++i]
    else if (a === '--dir') out.dir = argv[++i]
    else if (a === '--path') out.path = argv[++i]
    else if (a === '--timeout-ms') out.timeoutMs = Number(argv[++i])
  }
  return out
}

function startStaticServer(dir) {
  const root = resolve(dir)
  const server = createServer((req, res) => {
    const urlPath = decodeURIComponent((req.url || '/').split('?')[0])
    let filePath = join(root, urlPath === '/' ? 'index.html' : urlPath)
    if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
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
    resolve(process.cwd(), 'node_modules/playwright/index.mjs'),
    resolve(process.cwd(), 'node_modules/playwright/index.js'),
    resolve(REPO_ROOT, 'frontend/node_modules/playwright/index.mjs'),
    resolve(REPO_ROOT, 'frontend/node_modules/playwright/index.js'),
    resolve(REPO_ROOT, 'node_modules/playwright/index.mjs'),
  ]
  for (const candidate of candidates) {
    if (!existsSync(candidate)) continue
    try {
      return await import(pathToFileURL(candidate).href)
    } catch {
      // try next
    }
  }
  try {
    return await import('playwright')
  } catch {
    console.error(
      'playwright not found — from frontend/: npm ci && npx playwright install --with-deps chromium',
    )
    throw new Error('playwright module missing')
  }
}

function isBootKiller(message) {
  return BOOT_KILLER_RE.test(String(message || ''))
}

function isVisibleElement(el) {
  if (!el || el.hidden) return false
  const style = window.getComputedStyle(el)
  const rect = el.getBoundingClientRect()
  return (
    style.display !== 'none'
    && style.visibility !== 'hidden'
    && Number(style.opacity) !== 0
    && rect.width > 0
    && rect.height > 0
  )
}

async function runBootCheck({ url, timeoutMs, strictPageErrors }) {
  const { chromium } = await loadPlaywright()
  const pageErrors = []
  const browser = await chromium.launch({ headless: true })
  try {
    const page = await browser.newPage()
    page.on('pageerror', (err) => {
      pageErrors.push(String(err && err.message ? err.message : err))
    })
    page.on('console', (msg) => {
      if (msg.type() !== 'error') return
      const text = msg.text()
      if (isBootKiller(text)) pageErrors.push(text)
    })
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs })
    // Wait until React paints #root OR the static boot watchdog appears.
    await page.waitForFunction(
      () => {
        const root = document.getElementById('root')
        const fail = document.getElementById('spa-boot-failure')
        const failVisible =
          fail
          && !fail.hidden
          && window.getComputedStyle(fail).display !== 'none'
          && window.getComputedStyle(fail).visibility !== 'hidden'
          && Number(window.getComputedStyle(fail).opacity) !== 0
          && fail.getBoundingClientRect().width > 0
          && fail.getBoundingClientRect().height > 0
        return Boolean((root && root.childElementCount > 0) || failVisible)
      },
      { timeout: timeoutMs },
    )

    const failing = []
    const bootFailureVisible = await page
      .$eval('#spa-boot-failure', isVisibleElement)
      .catch(() => false)
    const childCount = await page.$eval('#root', (el) => el.childElementCount).catch(() => 0)

    // Watchdog only counts as failure if #root never painted (banner may flash then dismiss).
    if (bootFailureVisible && childCount < 1) {
      failing.push('spa-boot-failure watchdog visible — #root never painted')
    }

    if (strictPageErrors) {
      for (const e of pageErrors) failing.push(e)
    } else {
      for (const e of pageErrors) {
        if (isBootKiller(e)) failing.push(e)
      }
    }

    if (failing.length) {
      console.error('SPA boot check FAILED')
      for (const e of failing) console.error(`  - ${e}`)
      return 1
    }
    if (childCount < 1) {
      console.error('SPA boot check FAILED: #root has no children')
      return 1
    }
    // Soft landmark: login shell should expose a password field or Sign in copy.
    if (/\/login(?:\?|$)/.test(new URL(url).pathname)) {
      const loginLandmark = await page.evaluate(() => {
        const hasPassword = Boolean(document.querySelector('input[type="password"]'))
        const text = (document.body && document.body.innerText) || ''
        return hasPassword || /sign in|log in|login/i.test(text)
      })
      if (!loginLandmark) {
        console.error('SPA boot check FAILED: /login painted #root but no login landmark')
        return 1
      }
    }
    console.log(
      `SPA boot check OK: ${url} (#root children=${childCount}, mode=${strictPageErrors ? 'strict' : 'prod'})`,
    )
    return 0
  } finally {
    await browser.close()
  }
}

async function main() {
  const args = parseArgs(process.argv)
  let server = null
  let targetUrl = args.url
  const strictPageErrors = Boolean(args.dir) && !args.url
  try {
    if (!targetUrl) {
      if (!args.dir) {
        console.error('Provide --url or --dir frontend/dist')
        process.exit(1)
      }
      const started = await startStaticServer(args.dir)
      server = started.server
      targetUrl = `${started.baseUrl}${args.path.startsWith('/') ? args.path : `/${args.path}`}`
    }
    const code = await runBootCheck({
      url: targetUrl,
      timeoutMs: args.timeoutMs,
      strictPageErrors,
    })
    process.exit(code)
  } catch (err) {
    console.error('SPA boot check error:', err)
    process.exit(1)
  } finally {
    if (server) server.close()
  }
}

main()
