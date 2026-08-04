/**
 * Cursor hook helper — packing ALIGNED claims need Playwright geometry green.
 * Invoked from stop/after-response hooks when agent claims tabular packing done.
 */
import { existsSync, readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '../..')
const SCRIPT = resolve(REPO, 'scripts/cc-header-packing-geometry.mjs')

const ALIGNED_RE = /VERDICT:\s*ALIGNED/i
const PACKING_RE = /header packing|property-overview|dead middle|cc-header|Packing/i

/**
 * @param {string} text agent message
 * @returns {{ stop: boolean, reason?: string }}
 */
export function evaluatePackingAlignedClaim(text) {
  if (!ALIGNED_RE.test(text) || !PACKING_RE.test(text)) {
    return { stop: false }
  }
  if (!existsSync(SCRIPT)) {
    return {
      stop: true,
      reason:
        'STOP: VERDICT ALIGNED for packing claimed but scripts/cc-header-packing-geometry.mjs is missing.',
    }
  }
  const r = spawnSync(process.execPath, [SCRIPT], {
    cwd: REPO,
    encoding: 'utf8',
    timeout: 120000,
  })
  if (r.status !== 0) {
    return {
      stop: true,
      reason: `STOP: packing ALIGNED claimed but hostile geometry failed:\n${r.stdout || ''}\n${r.stderr || ''}`,
    }
  }
  return { stop: false }
}

export function packingGeometryScriptExists() {
  return existsSync(SCRIPT)
}

// Self-check when run directly
if (process.argv[1] && process.argv[1].includes('cc-header-packing-aligned-hook')) {
  const sample = process.argv[2] || ''
  const result = evaluatePackingAlignedClaim(sample)
  console.log(JSON.stringify(result, null, 2))
  process.exit(result.stop ? 1 : 0)
}
