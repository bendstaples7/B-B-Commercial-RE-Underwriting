#!/usr/bin/env node
/**
 * Forbid mode==='call' gating of next-step complete/follow-up UI in LogActivityForm.
 * Next-step chrome must live in ActivityNextStepPanel only.
 */
import { readFileSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const FORM = resolve(ROOT, 'frontend/src/components/LogActivityForm.tsx')
const PANEL = resolve(ROOT, 'frontend/src/components/ActivityNextStepPanel.tsx')

function fail(msg) {
  console.error(msg)
  process.exit(1)
}

if (!existsSync(PANEL)) {
  fail('Missing ActivityNextStepPanel.tsx — next-step must be a shared component')
}

const form = readFileSync(FORM, 'utf8')
if (!form.includes('ActivityNextStepPanel')) {
  fail('LogActivityForm must render ActivityNextStepPanel')
}

// Ban inline complete-task / follow-up checkbox markup in the form.
if (/data-testid=["']complete-call-task-checkbox["']/.test(form)) {
  fail('FORBID: complete-call-task-checkbox must not live in LogActivityForm (use ActivityNextStepPanel)')
}
if (/data-testid=["']create-follow-up-checkbox["']/.test(form)) {
  fail('FORBID: create-follow-up-checkbox must not be inlined in LogActivityForm')
}

// Ban mode === 'call' wrapping next-step complete UI
if (/mode\s*===\s*['"]call['"]\s*&&[\s\S]{0,120}completeTask|complete-call-task/.test(form)) {
  fail('FORBID: mode===\'call\' gating around complete-task next-step UI in LogActivityForm')
}

const panel = readFileSync(PANEL, 'utf8')
if (!panel.includes('complete-activity-task-checkbox')) {
  fail('ActivityNextStepPanel must own complete-activity-task-checkbox')
}
if (!panel.includes('create-follow-up-checkbox')) {
  fail('ActivityNextStepPanel must own create-follow-up-checkbox')
}

console.log('OK: LogActivityForm next-step mode-gate forbid passed')
