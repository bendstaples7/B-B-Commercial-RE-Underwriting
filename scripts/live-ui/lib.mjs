/**
 * Shared helpers for live authenticated UI visibility (screenshots + metrics).
 * Auth is JWT in localStorage (`session_token` / `user_id`) — not HTTP cookies.
 */
import { createRequire } from 'node:module'
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT = resolve(SCRIPT_DIR, '../..')
export const FRONTEND = resolve(REPO_ROOT, 'frontend')
export const ARTIFACT_DIR = resolve(REPO_ROOT, 'artifacts', 'live-ui')
export const AUTH_DIR = resolve(REPO_ROOT, 'artifacts', 'auth')
export const STORAGE_STATE_PATH = resolve(AUTH_DIR, 'storageState.json')
export const SESSION_EXPORT_PATH = resolve(AUTH_DIR, 'session-export.json')

const require = createRequire(resolve(FRONTEND, 'package.json'))
const SESSION_EXPIRY_SAFETY_SECONDS = 5 * 60

export function loadDotEnvFiles() {
  for (const rel of ['.env', 'backend/.env', 'frontend/.env']) {
    const p = resolve(REPO_ROOT, rel)
    if (!existsSync(p)) continue
    const text = readFileSync(p, 'utf8')
    for (const line of text.split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/)
      if (!m) continue
      const key = m[1]
      let val = m[2].trim()
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        val = val.slice(1, -1)
      }
      if (process.env[key] === undefined) process.env[key] = val
    }
  }
}

export function ensureDirs() {
  mkdirSync(ARTIFACT_DIR, { recursive: true })
  mkdirSync(AUTH_DIR, { recursive: true, mode: 0o700 })
  chmodSync(AUTH_DIR, 0o700)
}

export function getPlaywright() {
  try {
    return require(resolve(FRONTEND, 'node_modules/playwright'))
  } catch (err) {
    console.error('playwright not found under frontend/node_modules — run npm install in frontend/', err)
    process.exit(1)
  }
}

export function baseUrl() {
  return (process.env.BB_LIVE_UI_BASE_URL || 'http://localhost:3000').replace(/\/$/, '')
}

export function apiBaseUrl() {
  return (process.env.BB_LIVE_UI_API_URL || 'http://localhost:5000/api').replace(/\/$/, '')
}

export function stamp() {
  return new Date().toISOString().replace(/[:.]/g, '-').replace('T', '_').slice(0, 19)
}

export function slug(label) {
  return String(label || 'surface')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 64) || 'surface'
}

/** Inject JWT session the same way AuthProvider restores it. */
export async function injectSession(page, { sessionToken, userId }) {
  if (!sessionToken) throw new Error('sessionToken required')
  await page.addInitScript(
    ({ token, uid }) => {
      localStorage.setItem('session_token', token)
      if (uid) localStorage.setItem('user_id', uid)
    },
    { token: sessionToken, uid: userId || 'e2e' },
  )
}

export async function loginViaApi({ email, password }) {
  const res = await fetch(`${apiBaseUrl()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(`Login failed HTTP ${res.status}: ${body.error || body.message || res.statusText}`)
  }
  if (body.setup_required) {
    throw new Error('Login returned setup_required — set a password for the E2E user first')
  }
  if (!body.session_token || !body.user_id) {
    throw new Error('Login response missing session_token/user_id')
  }
  return { sessionToken: body.session_token, userId: body.user_id, email: body.email }
}

export function readSessionExport(path = SESSION_EXPORT_PATH) {
  if (!existsSync(path)) return null
  const data = JSON.parse(readFileSync(path, 'utf8'))
  const token = data.session_token || data.localStorage?.session_token
  const userId = data.user_id || data.localStorage?.user_id
  if (!token) return null
  const expiresAt = jwtExpiresAt(token)
  const minValidUntil = Date.now() + SESSION_EXPIRY_SAFETY_SECONDS * 1000
  if (!expiresAt || expiresAt <= minValidUntil) {
    try {
      unlinkSync(path)
    } catch {
      /* stale export cleanup best effort */
    }
    return null
  }
  return { sessionToken: token, userId, raw: data }
}

function jwtExpiresAt(token) {
  const parts = String(token).split('.')
  if (parts.length < 2) return null
  try {
    const payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'))
    const exp = Number(payload.exp)
    if (!Number.isFinite(exp)) return null
    return exp * 1000
  } catch {
    return null
  }
}

export function writeSessionExport({ sessionToken, userId, origin }) {
  ensureDirs()
  const payload = {
    exportedAt: new Date().toISOString(),
    origin: origin || baseUrl(),
    session_token: sessionToken,
    user_id: userId || null,
    localStorage: {
      session_token: sessionToken,
      user_id: userId || '',
    },
  }
  writeFileSync(SESSION_EXPORT_PATH, JSON.stringify(payload, null, 2), {
    encoding: 'utf8',
    mode: 0o600,
  })
  chmodSync(SESSION_EXPORT_PATH, 0o600)
  return SESSION_EXPORT_PATH
}

export async function writePlaywrightStorageState(context, path = STORAGE_STATE_PATH) {
  ensureDirs()
  await context.storageState({ path })
  chmodSync(path, 0o600)
  return path
}

/**
 * Resolve credentials: explicit token → session export → BB_E2E_* login.
 */
export async function resolveSession(opts = {}) {
  loadDotEnvFiles()
  if (opts.sessionToken) {
    return { sessionToken: opts.sessionToken, userId: opts.userId || 'e2e', source: 'opts' }
  }
  if (process.env.BB_E2E_SESSION_TOKEN) {
    return {
      sessionToken: process.env.BB_E2E_SESSION_TOKEN,
      userId: process.env.BB_E2E_USER_ID || 'e2e',
      source: 'env-token',
    }
  }
  const exported = readSessionExport(opts.exportPath || SESSION_EXPORT_PATH)
  if (exported) return { ...exported, source: 'session-export' }

  const email = opts.email || process.env.BB_E2E_EMAIL
  const password = opts.password || process.env.BB_E2E_PASSWORD
  if (email && password) {
    const logged = await loginViaApi({ email, password })
    writeSessionExport(logged)
    return { ...logged, source: 'api-login' }
  }

  throw new Error(
    [
      'No live-UI auth available.',
      'Provide one of:',
      '  1) artifacts/auth/session-export.json (Capture FAB → Export session, or import-session)',
      '  2) BB_E2E_EMAIL + BB_E2E_PASSWORD in repo-root .env',
      '  3) BB_E2E_SESSION_TOKEN (+ optional BB_E2E_USER_ID)',
      '  4) --cdp http://127.0.0.1:9222 against a logged-in Chromium',
    ].join('\n'),
  )
}

/** Geometry + clip metrics for a selector (runs in page). */
export function collectMetricsFn() {
  return (selector) => {
    const root = document.querySelector(selector)
    if (!root) return { ok: false, error: `missing selector ${selector}` }
    const rootRect = root.getBoundingClientRect()
    const cs = getComputedStyle(root)
    const children = [...root.querySelectorAll('[data-testid]')].slice(0, 80).map((el) => {
      const r = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      return {
        testId: el.getAttribute('data-testid'),
        left: r.left,
        right: r.right,
        top: r.top,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
        overflow: style.overflow,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        clippedByRoot:
          r.left + 0.5 < rootRect.left ||
          r.right - 0.5 > rootRect.right ||
          r.top + 0.5 < rootRect.top ||
          r.bottom - 0.5 > rootRect.bottom,
      }
    })
    const clipped = children.filter((c) => c.clippedByRoot)
    return {
      ok: true,
      selector,
      url: location.href,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      root: {
        left: rootRect.left,
        right: rootRect.right,
        top: rootRect.top,
        bottom: rootRect.bottom,
        width: rootRect.width,
        height: rootRect.height,
        overflow: cs.overflow,
        overflowX: cs.overflowX,
        overflowY: cs.overflowY,
      },
      children,
      clippedCount: clipped.length,
      clippedTestIds: clipped.map((c) => c.testId),
      loginWall: Boolean(
        document.querySelector('input[type="password"]') &&
          /sign in|log in/i.test(document.body?.innerText || ''),
      ),
    }
  }
}

export function assertNotLoginWall(pageUrl, metrics) {
  if (/\/login(\?|$)/i.test(pageUrl) || metrics?.loginWall) {
    throw new Error(
      `Live-UI landed on login wall (${pageUrl}). Auth injection failed or session expired.`,
    )
  }
}
