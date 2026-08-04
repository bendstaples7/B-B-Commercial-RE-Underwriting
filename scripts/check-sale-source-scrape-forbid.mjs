#!/usr/bin/env node
/**
 * Systemic forbid (assessor-only-blind-spot): enrichment plugins must not
 * scrape Redfin / Zillow / MLS / Realtor consumer sites for sale history.
 * Allowed sale sources: Assessor Socrata, related-PIN Assessor ladder, MyDec.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PLUGINS_DIR = resolve(ROOT, 'backend/app/services/plugins')
const DOCS = resolve(ROOT, 'docs/cook-county-sale-history-sources.md')

const FORBIDDEN = [
  /redfin\.com/i,
  /zillow\.com/i,
  /realtor\.com/i,
  /homes\.com/i,
  /trulia\.com/i,
]

const ALLOW_DOC_MENTION = /redfin|zillow|mls scrape|do not scrape/i

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const st = statSync(full)
    if (st.isDirectory()) out.push(...walk(full))
    else if (name.endsWith('.py')) out.push(full)
  }
  return out
}

let ok = true
function fail(msg) {
  console.error(msg)
  ok = false
}

if (!statSync(DOCS, { throwIfNoEntry: false })) {
  fail(`Missing ${relative(ROOT, DOCS)} — sale-source policy doc required`)
} else {
  const doc = readFileSync(DOCS, 'utf8')
  if (!/do not scrape Redfin/i.test(doc) && !/forbidden/i.test(doc)) {
    fail(`${relative(ROOT, DOCS)} must ban Redfin scrape for production`)
  }
  if (!/assessor_related_pin/.test(doc) || !/\bmydec\b/i.test(doc)) {
    fail(`${relative(ROOT, DOCS)} must document assessor | assessor_related_pin | mydec`)
  }
}

for (const file of walk(PLUGINS_DIR)) {
  const text = readFileSync(file, 'utf8')
  const rel = relative(ROOT, file).replace(/\\/g, '/')
  for (const pattern of FORBIDDEN) {
    if (!pattern.test(text)) continue
    // Allow comments that explicitly forbid the scrape.
    const lines = text.split(/\r?\n/)
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      if (!pattern.test(line)) continue
      if (ALLOW_DOC_MENTION.test(line) || /^\s*#/.test(line) || /^\s*"""/.test(line) || /^\s*'/.test(line)) {
        // Docstring / comment mentioning the ban is OK.
        if (/https?:\/\//i.test(line) && !/do not|forbid|not scrape|out of (reach|scope)|never/i.test(line)) {
          fail(`FORBID: ${rel}:${i + 1} must not reference scrape URL ${pattern}`)
        }
        continue
      }
      fail(`FORBID: ${rel}:${i + 1} matches banned sale-scrape host ${pattern}`)
    }
  }
}

if (!ok) {
  process.exit(1)
}
console.log(JSON.stringify({ ok: true, gate: 'sale-source-scrape-forbid' }))
