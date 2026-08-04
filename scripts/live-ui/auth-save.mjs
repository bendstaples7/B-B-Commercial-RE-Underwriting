#!/usr/bin/env node
/**
 * Save authenticated Playwright storage + session-export for live-UI snapshots.
 *
 *   node scripts/live-ui/auth-save.mjs
 *
 * Requires BB_E2E_EMAIL + BB_E2E_PASSWORD (or BB_E2E_SESSION_TOKEN).
 */
import {
  ARTIFACT_DIR,
  STORAGE_STATE_PATH,
  SESSION_EXPORT_PATH,
  baseUrl,
  ensureDirs,
  getPlaywright,
  injectSession,
  loadDotEnvFiles,
  resolveSession,
  writePlaywrightStorageState,
  writeSessionExport,
} from './lib.mjs'

async function main() {
  loadDotEnvFiles()
  ensureDirs()
  const session = await resolveSession()
  writeSessionExport(session)

  const { chromium } = getPlaywright()
  const browser = await chromium.launch({ headless: true })
  try {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      baseURL: baseUrl(),
    })
    const page = await context.newPage()
    await injectSession(page, session)
    await page.goto(baseUrl() + '/', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.waitForTimeout(500)
    if (/\/login/i.test(page.url())) {
      throw new Error(`Auth save still on login: ${page.url()}`)
    }
    await writePlaywrightStorageState(context)
    console.log(
      JSON.stringify(
        {
          ok: true,
          source: session.source,
          storageState: STORAGE_STATE_PATH,
          sessionExport: SESSION_EXPORT_PATH,
          artifactDir: ARTIFACT_DIR,
        },
        null,
        2,
      ),
    )
  } finally {
    await browser.close()
  }
}

main().catch((err) => {
  console.error(err.message || err)
  process.exit(1)
})
