#!/usr/bin/env node
/**
 * Single choke point: what counts as a valid Live-UI SEEN proof.
 *
 * CLI:
 *   node scripts/live-ui/claim-guard.mjs --check-claim   < stdin JSON { text, repoRoot? }
 *   node scripts/live-ui/claim-guard.mjs --validate-png <path.png>
 *
 * Exit 0 = ok / no enforcement needed; exit 1 = invalid SEEN or blind UI claim.
 */
import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, isAbsolute, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT_DEFAULT = resolve(SCRIPT_DIR, '../..')

/** Max age of screenshot proof for VERDICT: SEEN (ms). */
export const MAX_AGE_MS = 2 * 60 * 60 * 1000

export const LIVE_UI_SECTION_RE = /###\s*Live-UI\b/i
export const SEEN_RE = /VERDICT:\s*SEEN\b/i
export const NOT_SEEN_RE = /VERDICT:\s*NOT\s*SEEN\b/i
export const SETTLED_RE = /VERDICT:\s*SETTLED\b/i
export const VISIBLE_RE = /VERDICT:\s*VISIBLE\b/i

export const UI_DONE_CLAIM_RE =
  /\b(ready to (test|retest)|please (re)?test|please verify|ui (is )?ready|looks good to test|ready for (ui |browser )?verif)/i

export const RETEST_ASK_RE =
  /\b(please (re)?test|please verify|ready to (test|retest)|open (the )?(app|browser)|check in (the )?browser)\b/i

const PNG_CITE_RE =
  /artifacts[/\\]live-ui[/\\][A-Za-z0-9._-]+\.png/i

export function findRepoRoot(startDir) {
  let dir = startDir || process.cwd()
  for (let i = 0; i < 14; i += 1) {
    if (existsSync(resolve(dir, 'scripts', 'live-ui', 'claim-guard.mjs'))) {
      return dir
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return null
}

export function extractCitedPngRel(text) {
  const m = String(text || '').match(PNG_CITE_RE)
  return m ? m[0].replace(/\\/g, '/') : null
}

/**
 * Validate a PNG (+ companion JSON) as Live-UI proof.
 * @returns {{ ok: boolean, reason?: string, report?: object, pngPath?: string, jsonPath?: string }}
 */
export function validatePngProof(pngPath, { maxAgeMs = MAX_AGE_MS, now = Date.now() } = {}) {
  if (!pngPath) {
    return { ok: false, reason: 'missing_png_path' }
  }
  if (!existsSync(pngPath)) {
    return { ok: false, reason: `png_missing:${pngPath}` }
  }
  const st = statSync(pngPath)
  if (!st.isFile() || st.size < 64) {
    return { ok: false, reason: 'png_vacuous' }
  }

  const jsonPath = pngPath.replace(/\.png$/i, '.json')
  if (!existsSync(jsonPath)) {
    return { ok: false, reason: `json_missing:${jsonPath}` }
  }

  let report
  try {
    report = JSON.parse(readFileSync(jsonPath, 'utf8'))
  } catch {
    return { ok: false, reason: 'json_parse_error' }
  }

  if (!report || report.ok !== true) {
    return { ok: false, reason: 'json_ok_false', report }
  }
  if (report.metrics?.loginWall === true) {
    return { ok: false, reason: 'login_wall', report }
  }
  if (/\/login(\?|$)/i.test(String(report.finalUrl || ''))) {
    return { ok: false, reason: 'final_url_login', report }
  }

  let capturedMs = null
  if (report.capturedAt) {
    const t = Date.parse(report.capturedAt)
    if (Number.isFinite(t)) capturedMs = t
  }
  if (capturedMs == null) {
    capturedMs = st.mtimeMs
  }
  if (now - capturedMs > maxAgeMs) {
    return {
      ok: false,
      reason: `stale_proof_age_ms:${now - capturedMs}`,
      report,
      pngPath,
      jsonPath,
    }
  }

  return { ok: true, report, pngPath, jsonPath }
}

/**
 * Evaluate an agent response for Live-UI enforcement.
 * @returns {{
 *   ok: boolean,
 *   action: 'none'|'clear'|'followup',
 *   reason?: string,
 *   message?: string,
 *   citedPng?: string|null,
 * }}
 */
export function checkClaim(text, { repoRoot, pending = false, maxAgeMs = MAX_AGE_MS } = {}) {
  const body = String(text || '')
  const root = repoRoot || REPO_ROOT_DEFAULT
  const hasSection = LIVE_UI_SECTION_RE.test(body)
  const isSeen = SEEN_RE.test(body)
  const isNotSeen = NOT_SEEN_RE.test(body)
  const uiClaim =
    UI_DONE_CLAIM_RE.test(body) ||
    SETTLED_RE.test(body) ||
    VISIBLE_RE.test(body) ||
    (hasSection && (isSeen || isNotSeen))
  const asksRetest = RETEST_ASK_RE.test(body)

  if (!uiClaim && !pending) {
    return { ok: true, action: 'none', reason: 'no_ui_claim' }
  }

  // Pending FE edits: any UI-done / settle / visible / retest must include Live-UI.
  if (pending && (UI_DONE_CLAIM_RE.test(body) || SETTLED_RE.test(body) || VISIBLE_RE.test(body) || asksRetest)) {
    if (!hasSection) {
      return {
        ok: false,
        action: 'followup',
        reason: 'pending_ui_claim_missing_live_ui',
        message:
          'STOP: frontend UI claim without ### Live-UI. Run live-ui snapshot / Capture FAB, Read the PNG, then emit ### Live-UI VERDICT: SEEN (or NOT SEEN + blocker).',
      }
    }
  }

  if (isNotSeen && asksRetest) {
    return {
      ok: false,
      action: 'followup',
      reason: 'not_seen_with_retest_ask',
      message:
        'STOP: VERDICT: NOT SEEN cannot ask for human retest. Fix auth/snapshot or unblock, then SEEN — or stop asking for retest.',
    }
  }

  if (isSeen) {
    const rel = extractCitedPngRel(body)
    if (!rel) {
      return {
        ok: false,
        action: 'followup',
        reason: 'seen_without_cited_png',
        message:
          'STOP: VERDICT: SEEN without citing artifacts/live-ui/<file>.png. Snapshot first, cite the path, Read the PNG.',
        citedPng: null,
      }
    }
    const abs = isAbsolute(rel) ? rel : resolve(root, rel)
    const proof = validatePngProof(abs, { maxAgeMs })
    if (!proof.ok) {
      return {
        ok: false,
        action: 'followup',
        reason: `seen_invalid:${proof.reason}`,
        message: `STOP: VERDICT: SEEN but proof invalid (${proof.reason}). Re-run node scripts/live-ui/snapshot.mjs and cite a fresh PNG.`,
        citedPng: rel,
      }
    }
    return {
      ok: true,
      action: 'clear',
      reason: 'seen_valid',
      citedPng: rel,
    }
  }

  if (isNotSeen) {
    // Allowed mid-work; do not clear pending (still need SEEN before done).
    return {
      ok: true,
      action: 'none',
      reason: 'not_seen_ok',
    }
  }

  if (pending && hasSection && !isSeen && !isNotSeen) {
    return {
      ok: false,
      action: 'followup',
      reason: 'live_ui_section_missing_verdict',
      message:
        'STOP: ### Live-UI present without VERDICT: SEEN or NOT SEEN.',
    }
  }

  if (
    pending &&
    (UI_DONE_CLAIM_RE.test(body) || SETTLED_RE.test(body) || VISIBLE_RE.test(body)) &&
    !isSeen
  ) {
    return {
      ok: false,
      action: 'followup',
      reason: 'pending_done_without_seen',
      message:
        'STOP: UI done/SETTLED/VISIBLE while live-ui pending — need VERDICT: SEEN with fresh PNG (or NOT SEEN without asking retest).',
    }
  }

  return { ok: true, action: 'none', reason: 'no_enforcement' }
}

async function readStdin() {
  const chunks = []
  for await (const c of process.stdin) chunks.push(c)
  return Buffer.concat(chunks).toString('utf8')
}

async function main() {
  const argv = process.argv.slice(2)
  if (argv[0] === '--validate-png') {
    const p = argv[1]
    const root = findRepoRoot(process.cwd()) || REPO_ROOT_DEFAULT
    const abs = p && !isAbsolute(p) ? resolve(root, p) : p
    const result = validatePngProof(abs)
    console.log(JSON.stringify(result, null, 2))
    process.exit(result.ok ? 0 : 1)
  }

  if (argv[0] === '--check-claim') {
    const raw = await readStdin()
    let input = {}
    try {
      input = raw.trim() ? JSON.parse(raw) : {}
    } catch {
      input = { text: raw }
    }
    const root =
      input.repoRoot ||
      findRepoRoot(input.cwd || process.cwd()) ||
      REPO_ROOT_DEFAULT
    const result = checkClaim(input.text || '', {
      repoRoot: root,
      pending: Boolean(input.pending),
      maxAgeMs: input.maxAgeMs || MAX_AGE_MS,
    })
    console.log(JSON.stringify(result, null, 2))
    process.exit(result.ok ? 0 : 1)
  }

  console.error('Usage: --check-claim (stdin JSON) | --validate-png <path>')
  process.exit(2)
}

const isMain =
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  main().catch((err) => {
    console.error(err)
    process.exit(1)
  })
}
