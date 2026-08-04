#!/usr/bin/env node
/**
 * Mechanical forbid: Units/Category KPI values must not use whiteSpace nowrap.
 * Also requires allowWrap: true on units-details + category cells.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = resolve(
  ROOT,
  'frontend/src/components/lead-detail/PropertyOverviewQuickStats.tsx',
)
const CHROME = resolve(
  ROOT,
  'frontend/src/components/lead-detail/commandCenterChrome.ts',
)

const src = readFileSync(SRC, 'utf8')
const chrome = readFileSync(CHROME, 'utf8')

let ok = true

function fail(msg) {
  console.error(msg)
  ok = false
}

// units-details and category must declare allowWrap: true
for (const id of ['units-details', 'category']) {
  const re = new RegExp(`id:\\s*'${id}'[\\s\\S]*?allowWrap:\\s*true`)
  if (!re.test(src)) {
    fail(`FORBID: quick-stat ${id} must set allowWrap: true`)
  }
}

// No nowrap trap on units/category value path — allowWrap branch must not
// fall through to nowrap for those cells. Detect raw nowrap assignment on
// the value Typography without allowWrap gating is OK only for est-value.
if (/id:\s*'units-details'[\s\S]{0,200}whiteSpace:\s*['"]nowrap['"]/.test(src)) {
  fail('FORBID: units-details must not hard-code whiteSpace nowrap')
}

if (!src.includes("contain: 'layout style'") && !src.includes('contain: "layout style"')) {
  fail('FORBID: KPI cells must set contain: layout style')
}

if (!chrome.includes("contain: 'layout'") && !chrome.includes('contain: "layout"')) {
  fail('FORBID: ccHeaderQuickStatsSx / trailing panels must set contain: layout')
}

if (!chrome.includes('isolation')) {
  fail('FORBID: packing tokens must set isolation for paint containment')
}

const ulcc = readFileSync(
  resolve(ROOT, 'frontend/src/components/UnifiedLeadCommandCenter.tsx'),
  'utf8',
)
const scorePanel = readFileSync(
  resolve(ROOT, 'frontend/src/components/lead-detail/HeaderLeadScorePanel.tsx'),
  'utf8',
)

// Hero address (md+): must be nowrap one-liner — ban wrap-as-packing-fix.
if (
  /data-testid="property-overview-address-line"[\s\S]{0,500}whiteSpace:\s*\{\s*[^}]*md:\s*['"]normal['"]/.test(
    ulcc,
  )
) {
  fail('FORBID: property-overview-address-line must not use whiteSpace normal at md')
}
if (
  /data-testid="property-overview-address-line"[\s\S]{0,400}whiteSpace:\s*['"]normal['"]/.test(ulcc)
  && !/whiteSpace:\s*\{\s*xs:/.test(
    ulcc.slice(
      ulcc.indexOf('property-overview-address-line'),
      ulcc.indexOf('property-overview-address-line') + 500,
    ),
  )
) {
  fail('FORBID: property-overview-address-line must not hard-code whiteSpace normal')
}
if (!/md:\s*['"]nowrap['"]/.test(
  ulcc.slice(
    ulcc.indexOf('property-overview-address-line'),
    ulcc.indexOf('property-overview-address-line') + 600,
  ),
)) {
  fail('FORBID: property-overview-address-line must set md nowrap')
}

// Ban tight rem/% address clamps that force wrap while space exists.
const addressSxBlock = chrome.slice(
  chrome.indexOf('export const ccHeaderAddressColumnSx'),
  chrome.indexOf('export const ccHeaderPrimaryClusterSx'),
)
if (/md:\s*['"]22rem['"]/.test(addressSxBlock) || /['"]22rem['"]/.test(addressSxBlock)) {
  fail('FORBID: ccHeaderAddressColumnSx must not use 22rem clamp')
}
if (/42%/.test(addressSxBlock)) {
  fail('FORBID: ccHeaderAddressColumnSx must not use 42% clamp')
}
if (!/max-content|md:\s*['"]none['"]/.test(addressSxBlock)) {
  fail('FORBID: address column must be content-sized (max-content / maxWidth none) at md')
}

if (!/limit\s*=\s*2/.test(scorePanel)) {
  fail('FORBID: resolveTopScoreDrivers default limit must be 2')
}

if (
  /header-score-drivers[\s\S]{0,1200}textOverflow:\s*['"]ellipsis['"]/.test(scorePanel)
) {
  fail('FORBID: header score driver chips must not use textOverflow ellipsis')
}

if (!ok) process.exit(1)
console.log(JSON.stringify({ ok: true, gate: 'cc-kpi-nowrap-containment-forbid' }))
