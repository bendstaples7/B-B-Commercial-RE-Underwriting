#!/usr/bin/env node
/**
 * Capture SameAddressMerge lookbook screenshots for PR walkthrough.
 * Starts Vite if needed, injects a client-side JWT, mocks merge preview API.
 */
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
const OUT_DIR = resolve(ROOT, 'artifacts/live-ui')
const CURSOR_OUT = '/opt/cursor/artifacts'
const PORT = 3017
const BASE = `http://127.0.0.1:${PORT}`

function base64UrlEncode(str) {
  return Buffer.from(str, 'utf8')
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

function buildJwt(payload) {
  const header = base64UrlEncode(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = base64UrlEncode(JSON.stringify(payload))
  return `${header}.${body}.fakesignature`
}

async function waitForServer(url, timeoutMs = 60000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url)
      if (res.ok || res.status === 404 || res.status === 401) return
    } catch {
      // retry
    }
    await new Promise((r) => setTimeout(r, 400))
  }
  throw new Error(`Server not ready: ${url}`)
}

async function main() {
  console.log({ __dirname, ROOT, OUT_DIR, CURSOR_OUT })
  mkdirSync(OUT_DIR, { recursive: true })
  mkdirSync(CURSOR_OUT, { recursive: true })

  const vite = spawn(
    'npm',
    ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(PORT)],
    {
      cwd: resolve(ROOT, 'frontend'),
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, BROWSER: 'none' },
    },
  )
  let viteLog = ''
  vite.stdout.on('data', (d) => {
    viteLog += d.toString()
  })
  vite.stderr.on('data', (d) => {
    viteLog += d.toString()
  })

  try {
    await waitForServer(BASE)
    const browser = await chromium.launch({ headless: true })
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } })

    const now = Math.floor(Date.now() / 1000)
    const token = buildJwt({
      sub: 'lookbook-user',
      email: 'lookbook@example.com',
      display_name: 'Lookbook',
      is_admin: true,
      iat: now,
      exp: now + 60 * 60 * 12,
    })

    await page.route('**/api/**', async (route) => {
      const url = route.request().url()
      if (url.includes('/merge-preview/')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            same_building: true,
            current: {
              id: 2496,
              property_street: '1867 N Howe St',
              owner_display_name: 'JAMES E MALONE',
              people_names: ['JAMES E MALONE'],
            },
            other: {
              id: 2497,
              property_street: '1867-1869 N Howe St',
              owner_display_name: 'JAMES E MALONE',
              people_names: ['JAMES E MALONE'],
            },
          }),
        })
        return
      }
      if (url.includes('/merge-into/')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ winner_id: 2496, loser_id: 2497, merged: true }),
        })
        return
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      })
    })

    await page.addInitScript((sessionToken) => {
      localStorage.setItem('session_token', sessionToken)
    }, token)

    await page.goto(`${BASE}/lookbook/same-address-merge`, { waitUntil: 'networkidle' })
    await page.getByTestId('merge-lookbook').waitFor({ timeout: 30000 })
    await page.getByTestId('merge-lookbook-cc-placement').waitFor({ timeout: 15000 })

    // Placement shot: CC header + highlighted Merge duplicate entry
    const placement = page.getByTestId('merge-lookbook-cc-placement')
    const placementPath = resolve(OUT_DIR, 'cc-merge-entry-point.png')
    await placement.screenshot({ path: placementPath })
    writeFileSync(
      resolve(OUT_DIR, 'cc-merge-entry-point.json'),
      JSON.stringify(
        {
          url: `${BASE}/lookbook/same-address-merge`,
          label: 'cc-merge-entry-point',
          loginWall: false,
          capturedAt: new Date().toISOString(),
        },
        null,
        2,
      ),
    )

    // Open dialog from the CC placement Merge duplicate button
    await placement.getByTestId('same-address-merge-open').click()
    await page.getByTestId('same-address-merge-dialog').waitFor()
    await page.getByTestId('same-address-merge-paste-id').fill('Howe')
    await page.waitForTimeout(500)
    await page.getByTestId('same-address-merge-paste-id').fill('2497')
    await page.getByTestId('same-address-merge-paste-id').blur()
    await page.waitForTimeout(400)

    const dialogPath = resolve(OUT_DIR, 'cc-merge-search-dialog.png')
    await page.screenshot({ path: dialogPath, fullPage: false })
    writeFileSync(
      resolve(OUT_DIR, 'cc-merge-search-dialog.json'),
      JSON.stringify(
        {
          url: `${BASE}/lookbook/same-address-merge`,
          label: 'cc-merge-search-dialog',
          loginWall: false,
          capturedAt: new Date().toISOString(),
        },
        null,
        2,
      ),
    )

    const { copyFileSync } = await import('node:fs')
    for (const name of ['cc-merge-entry-point.png', 'cc-merge-search-dialog.png']) {
      copyFileSync(resolve(OUT_DIR, name), resolve(CURSOR_OUT, name))
    }

    console.log(JSON.stringify({ placementPath, dialogPath, ok: true }))
    await browser.close()
  } catch (err) {
    console.error(viteLog.slice(-4000))
    throw err
  } finally {
    vite.kill('SIGTERM')
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
