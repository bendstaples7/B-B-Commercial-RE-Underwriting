#!/usr/bin/env node
/**
 * Import / sync auth for live-UI from:
 *   --from-export path.json   session export (Capture FAB or prior save)
 *   --token JWT --user-id id  raw JWT
 *   --cdp http://127.0.0.1:9222  pull localStorage from open Chromium tab
 *
 * Writes artifacts/auth/session-export.json (+ storageState when possible).
 */
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  AUTH_DIR,
  SESSION_EXPORT_PATH,
  STORAGE_STATE_PATH,
  baseUrl,
  ensureDirs,
  getPlaywright,
  injectSession,
  loadDotEnvFiles,
  writePlaywrightStorageState,
  writeSessionExport,
} from './lib.mjs'

function parseArgs(argv) {
  const out = { fromExport: null, token: null, userId: null, cdp: null }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => argv[++i]
    if (a === '--from-export') out.fromExport = next()
    else if (a === '--token') out.token = next()
    else if (a === '--user-id') out.userId = next()
    else if (a === '--cdp') out.cdp = next()
    else if (a === '--help' || a === '-h') out.help = true
  }
  return out
}

async function pullFromCdp(cdpUrl) {
  const { chromium } = getPlaywright()
  const browser = await chromium.connectOverCDP(cdpUrl)
  try {
    const context = browser.contexts()[0]
    if (!context) throw new Error('No CDP context')
    const pages = context.pages()
    const page =
      pages.find((p) => /localhost:3000|127\.0\.0\.1:3000/.test(p.url())) ||
      pages.find((p) => /localhost|127\.0\.0\.1/.test(p.url())) ||
      pages[0]
    if (!page) throw new Error('No pages in CDP browser — open localhost:3000 while logged in')
    const ls = await page.evaluate(() => ({
      session_token: localStorage.getItem('session_token'),
      user_id: localStorage.getItem('user_id'),
      href: location.href,
    }))
    if (!ls.session_token) {
      throw new Error(`No session_token in localStorage on ${ls.href} — log in first`)
    }
    return {
      sessionToken: ls.session_token,
      userId: ls.user_id || 'imported',
      origin: new URL(ls.href).origin,
    }
  } finally {
    try {
      await browser.close()
    } catch {
      /* disconnect */
    }
  }
}

async function main() {
  loadDotEnvFiles()
  ensureDirs()
  const args = parseArgs(process.argv.slice(2))
  if (args.help) {
    console.log(`Usage:
  node scripts/live-ui/import-session.mjs --cdp http://127.0.0.1:9222
  node scripts/live-ui/import-session.mjs --from-export artifacts/auth/session-export.json
  node scripts/live-ui/import-session.mjs --token <jwt> --user-id <id>`)
    process.exit(0)
  }

  let session
  if (args.cdp) {
    session = await pullFromCdp(args.cdp)
  } else if (args.token) {
    session = { sessionToken: args.token, userId: args.userId || 'imported' }
  } else if (args.fromExport) {
    const path = resolve(args.fromExport)
    if (!existsSync(path)) throw new Error(`Missing export: ${path}`)
    const data = JSON.parse(readFileSync(path, 'utf8'))
    const token = data.session_token || data.localStorage?.session_token
    if (!token) throw new Error('Export JSON missing session_token')
    session = {
      sessionToken: token,
      userId: data.user_id || data.localStorage?.user_id || 'imported',
      origin: data.origin,
    }
  } else if (existsSync(SESSION_EXPORT_PATH)) {
    const data = JSON.parse(readFileSync(SESSION_EXPORT_PATH, 'utf8'))
    session = {
      sessionToken: data.session_token || data.localStorage?.session_token,
      userId: data.user_id || data.localStorage?.user_id,
    }
    if (!session.sessionToken) throw new Error('Default session-export missing token')
  } else {
    throw new Error('Provide --cdp, --from-export, or --token')
  }

  const exportPath = writeSessionExport(session)

  const { chromium } = getPlaywright()
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({ baseURL: baseUrl() })
    const page = await context.newPage()
    await injectSession(page, session)
    await page.goto(baseUrl() + '/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await writePlaywrightStorageState(context)
  } finally {
    await browser.close()
  }

  console.log(
    JSON.stringify(
      {
        ok: true,
        sessionExport: exportPath,
        storageState: STORAGE_STATE_PATH,
        authDir: AUTH_DIR,
      },
      null,
      2,
    ),
  )
}

main().catch((err) => {
  console.error(err.message || err)
  process.exit(1)
})
