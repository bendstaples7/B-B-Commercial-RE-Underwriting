/**
 * Vite plugin: DEV-only live-UI capture + session export endpoints.
 *
 * POST /__bb/live-ui/session  { session_token, user_id?, origin? }
 * POST /__bb/live-ui/capture  { selector?, label?, url?, viewport? }
 *   → runs Playwright snapshot against the running app (uses saved session)
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(HERE, '../..')
const AUTH_DIR = resolve(REPO_ROOT, 'artifacts', 'auth')
const SESSION_EXPORT = resolve(AUTH_DIR, 'session-export.json')

function readJson(req) {
  return new Promise((resolveBody, reject) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf8') || '{}'
        resolveBody(JSON.parse(raw))
      } catch (err) {
        reject(err)
      }
    })
    req.on('error', reject)
  })
}

function sendJson(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(body))
}

function runSnapshot(args) {
  return new Promise((resolveRun, reject) => {
    const child = spawn(process.execPath, [resolve(HERE, 'snapshot.mjs'), ...args], {
      cwd: REPO_ROOT,
      env: process.env,
      windowsHide: true,
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (d) => {
      stdout += d.toString()
    })
    child.stderr.on('data', (d) => {
      stderr += d.toString()
    })
    child.on('error', reject)
    child.on('close', (code) => {
      resolveRun({ code, stdout, stderr })
    })
  })
}

export function liveUiCapturePlugin() {
  return {
    name: 'bb-live-ui-capture',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = req.url?.split('?')[0]
        if (req.method === 'POST' && url === '/__bb/live-ui/session') {
          try {
            const body = await readJson(req)
            const token = body.session_token || body.localStorage?.session_token
            if (!token) return sendJson(res, 400, { ok: false, error: 'session_token required' })
            mkdirSync(AUTH_DIR, { recursive: true })
            const payload = {
              exportedAt: new Date().toISOString(),
              origin: body.origin || 'http://localhost:3000',
              session_token: token,
              user_id: body.user_id || body.localStorage?.user_id || null,
              localStorage: {
                session_token: token,
                user_id: body.user_id || body.localStorage?.user_id || '',
              },
            }
            writeFileSync(SESSION_EXPORT, JSON.stringify(payload, null, 2), 'utf8')
            return sendJson(res, 200, { ok: true, path: SESSION_EXPORT })
          } catch (err) {
            return sendJson(res, 500, { ok: false, error: String(err?.message || err) })
          }
        }

        if (req.method === 'POST' && url === '/__bb/live-ui/capture') {
          try {
            const body = await readJson(req)
            if (!existsSync(SESSION_EXPORT) && !process.env.BB_E2E_EMAIL && !process.env.BB_E2E_SESSION_TOKEN) {
              return sendJson(res, 400, {
                ok: false,
                error:
                  'No auth export yet. Click Export session on the Capture FAB while logged in, or set BB_E2E_EMAIL/PASSWORD.',
              })
            }
            const selector = body.selector || '[data-testid="property-overview-header"]'
            const label = body.label || 'capture-fab'
            const target = body.url || body.pathname || '/'
            const result = await runSnapshot([
              '--url',
              String(target),
              '--selector',
              selector,
              '--label',
              label,
            ])
            let report = null
            try {
              report = JSON.parse(result.stdout)
            } catch {
              /* leave null */
            }
            if (result.code !== 0 && result.code !== 2) {
              return sendJson(res, 500, {
                ok: false,
                error: result.stderr || result.stdout || `snapshot exit ${result.code}`,
                report,
              })
            }
            return sendJson(res, 200, {
              ok: true,
              warnClipped: result.code === 2,
              report,
              stderr: result.stderr || undefined,
            })
          } catch (err) {
            return sendJson(res, 500, { ok: false, error: String(err?.message || err) })
          }
        }

        return next()
      })
    },
  }
}
