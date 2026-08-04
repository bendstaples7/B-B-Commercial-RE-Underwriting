#!/usr/bin/env node
/**
 * Meta-guard: CI must keep the hostile CC header packing geometry job.
 * Fails if .github/workflows/ci.yml drops the Playwright packing gate.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const ci = readFileSync(resolve(ROOT, '.github/workflows/ci.yml'), 'utf8')
const script = resolve(ROOT, 'scripts/cc-header-packing-geometry.mjs')
const rule = resolve(ROOT, '.cursor/rules/tabular-packing-geometry.mdc')

const required = [
  'cc-header-packing-geometry.mjs',
  'CC header packing geometry',
]

let ok = true
for (const needle of required) {
  if (!ci.includes(needle)) {
    console.error(`CI missing packing geometry gate: ${needle}`)
    ok = false
  }
}

try {
  readFileSync(script, 'utf8')
} catch {
  console.error('Missing scripts/cc-header-packing-geometry.mjs')
  ok = false
}

try {
  readFileSync(rule, 'utf8')
} catch {
  console.error('Missing .cursor/rules/tabular-packing-geometry.mdc')
  ok = false
}

if (!ok) process.exit(1)
console.log(JSON.stringify({ ok: true, gate: 'cc-header-packing-geometry' }))
