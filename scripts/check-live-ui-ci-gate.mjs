#!/usr/bin/env node
/**
 * Meta-guard: CI must keep live-UI hard enforcement (scripts, skill, hooks, auth smoke).
 */
import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const requiredFiles = [
  'scripts/live-ui/snapshot.mjs',
  'scripts/live-ui/lib.mjs',
  'scripts/live-ui/claim-guard.mjs',
  'scripts/live-ui/ci_seed_auth_lead.py',
  '.cursor/rules/live-ui-visibility.mdc',
  '.cursor/skills/live-ui-visibility/SKILL.md',
  '.cursor/hooks/live-ui-visibility-after-response.js',
  '.cursor/hooks/live-ui-visibility-after-file-edit.js',
  '.cursor/hooks/live-ui-visibility-stop.js',
  '.cursor/hooks/live-ui-visibility-lib.js',
  '.cursor/hooks.json',
]

let ok = true
for (const rel of requiredFiles) {
  const p = resolve(ROOT, rel)
  if (!existsSync(p)) {
    console.error(`Missing live-UI enforcement file: ${rel}`)
    ok = false
  }
}

const hooksJson = readFileSync(resolve(ROOT, '.cursor/hooks.json'), 'utf8')
for (const needle of [
  'live-ui-visibility-after-response.js',
  'live-ui-visibility-after-file-edit.js',
  'live-ui-visibility-stop.js',
]) {
  if (!hooksJson.includes(needle)) {
    console.error(`.cursor/hooks.json missing registration: ${needle}`)
    ok = false
  }
}

const ci = readFileSync(resolve(ROOT, '.github/workflows/ci.yml'), 'utf8')
for (const needle of [
  'check-live-ui-ci-gate.mjs',
  'live-ui-auth-smoke',
  'ci_seed_auth_lead.py',
  'live-ui/snapshot.mjs',
]) {
  if (!ci.includes(needle)) {
    console.error(`CI missing live-UI auth smoke gate: ${needle}`)
    ok = false
  }
}

if (!ok) {
  process.exit(1)
}
console.log('live-UI CI gate present')
