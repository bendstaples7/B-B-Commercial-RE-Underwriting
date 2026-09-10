#!/usr/bin/env node
/**
 * Capture the three Merge-CTA placement mockups for product review.
 */
import { spawn } from 'node:child_process'
import { copyFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '../frontend/node_modules/playwright/index.mjs'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
const OUT_DIR = resolve(ROOT, 'artifacts/live-ui')
const CURSOR_OUT = '/opt/cursor/artifacts'
const PORT = 3021
const BASE = `http://127.0.0.1:${PORT}`

function b64url(str) {
  return Buffer.from(str, 'utf8')
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

function jwt(payload) {
  return `${b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))}.${b64url(JSON.stringify(payload))}.sig`
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
    const token = jwt({
      sub: 'lookbook-user',
      email: 'lookbook@example.com',
      display_name: 'Lookbook',
      is_admin: true,
      iat: now,
      exp: now + 60 * 60 * 12,
    })

    await page.route('**/api/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      })
    })
    await page.addInitScript((sessionToken) => {
      localStorage.setItem('session_token', sessionToken)
    }, token)

    await page.goto(`${BASE}/lookbook/merge-cta-placements`, { waitUntil: 'networkidle' })
    await page.getByTestId('merge-cta-placement-lookbook').waitFor({ timeout: 30000 })

    const shots = [
      ['merge-placement-option-1', 'merge-cta-option-1-action-center.png'],
      ['merge-placement-option-3', 'merge-cta-option-3-key-contact.png'],
    ]

    for (const [testId, fileName] of shots) {
      const el = page.getByTestId(testId)
      const path = resolve(OUT_DIR, fileName)
      await el.screenshot({ path })
      writeFileSync(
        resolve(OUT_DIR, fileName.replace('.png', '.json')),
        JSON.stringify(
          {
            url: `${BASE}/lookbook/merge-cta-placements`,
            label: fileName.replace('.png', ''),
            loginWall: false,
            capturedAt: new Date().toISOString(),
          },
          null,
          2,
        ),
      )
      copyFileSync(path, resolve(CURSOR_OUT, fileName))
    }

    // Option 2 with overflow menu open
    const option2 = page.getByTestId('merge-placement-option-2')
    await option2.getByTestId('merge-placement-overflow-trigger').click()
    await page.getByTestId('merge-placement-overflow-menu').waitFor()
    const option2Path = resolve(OUT_DIR, 'merge-cta-option-2-header-overflow.png')
    // Capture full page region around option 2 + open menu
    await page.screenshot({
      path: option2Path,
      clip: await option2.boundingBox().then((box) => {
        if (!box) throw new Error('option 2 box missing')
        return {
          x: Math.max(0, box.x - 8),
          y: Math.max(0, box.y - 8),
          width: Math.min(1080, box.width + 16),
          height: Math.min(520, box.height + 180),
        }
      }),
    })
    writeFileSync(
      resolve(OUT_DIR, 'merge-cta-option-2-header-overflow.json'),
      JSON.stringify(
        {
          url: `${BASE}/lookbook/merge-cta-placements`,
          label: 'merge-cta-option-2-header-overflow',
          loginWall: false,
          capturedAt: new Date().toISOString(),
        },
        null,
        2,
      ),
    )
    copyFileSync(option2Path, resolve(CURSOR_OUT, 'merge-cta-option-2-header-overflow.png'))

    console.log(
      JSON.stringify({
        ok: true,
        files: [
          'merge-cta-option-1-action-center.png',
          'merge-cta-option-2-header-overflow.png',
          'merge-cta-option-3-key-contact.png',
        ],
      }),
    )
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
