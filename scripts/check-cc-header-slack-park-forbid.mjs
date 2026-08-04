#!/usr/bin/env node
/**
 * Forbid: trail full-width second row, fixed px trail widths, address maxWidth
 * ceilings, flexShrink:0 on trail, and header overflow clip.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const chrome = readFileSync(
  resolve(ROOT, 'frontend/src/components/lead-detail/commandCenterChrome.ts'),
  'utf8',
)
const ulcc = readFileSync(
  resolve(ROOT, 'frontend/src/components/UnifiedLeadCommandCenter.tsx'),
  'utf8',
)
const score = readFileSync(
  resolve(ROOT, 'frontend/src/components/lead-detail/HeaderLeadScorePanel.tsx'),
  'utf8',
)
const condo = readFileSync(
  resolve(ROOT, 'frontend/src/components/lead-detail/HeaderCondoCheckPanel.tsx'),
  'utf8',
)
const harness = readFileSync(
  resolve(ROOT, 'frontend/src/harness/ccHeaderPackingMain.tsx'),
  'utf8',
)

let ok = true

if (/ccHeaderTrailingPanelsSx[\s\S]{0,500}md:\s*['"]1 1 100%['"]/.test(chrome)) {
  console.error('FORBID: trail md flex 1 1 100% stacks Last sale above condo')
  ok = false
}

if (/ccHeaderTrailingPanelsSx[\s\S]{0,400}minWidth:\s*['"]100%['"]/.test(chrome)) {
  console.error('FORBID: trail minWidth 100% forces a second header row')
  ok = false
}

if (/ccHeaderTrailingPanelsSx[\s\S]{0,250}flexShrink:\s*0/.test(chrome)) {
  console.error('FORBID: trail flexShrink:0 blocks responsive shrink')
  ok = false
}

if (/ccHeaderTrailingPanelsSx[\s\S]{0,350}width:\s*\{\s*md:\s*368/.test(chrome)) {
  console.error('FORBID: trail fixed width 368 — use clamp fluid panels')
  ok = false
}

if (/ccHeaderTrailingPanelsSx[\s\S]{0,500}0 0 180px/.test(chrome)) {
  console.error('FORBID: trail panel flex 0 0 180px — use clamp(9rem, 15vw, 300px)')
  ok = false
}

if (
  /ccHeaderAddressColumnSx[\s\S]{0,400}maxWidth:\s*\{\s*[^}]*md:\s*['"]\d+rem['"]/.test(chrome)
) {
  console.error('FORBID: address maxWidth rem ceiling forces early ellipsis')
  ok = false
}

if (/ccHeaderTrailingPanelsSx[\s\S]{0,400}ml:\s*\{\s*md:\s*['"]auto['"]/.test(chrome)) {
  console.error('FORBID: trail ml:auto canyon on same row')
  ok = false
}

if (!/ccHeaderAddressColumnSx[\s\S]{0,250}md:\s*['"]0 1 auto['"]/.test(chrome)) {
  console.error('Missing address hug flex (md 0 1 auto)')
  ok = false
}

if (!/ccHeaderPrimaryClusterSx[\s\S]{0,250}md:\s*['"]0 1 auto['"]/.test(chrome)) {
  console.error('Missing primary cluster hug (md 0 1 auto) — trail panels absorb slack')
  ok = false
}

if (!/ccHeaderQuickStatsSx[\s\S]{0,250}md:\s*['"]0 1 auto['"]/.test(chrome)) {
  console.error('Missing KPI hug (md 0 1 auto) — trail panels absorb slack')
  ok = false
}

if (!/ccHeaderTrailingPanelsSx[\s\S]{0,250}md:\s*['"]1 1 auto['"]/.test(chrome)) {
  console.error('Missing trail grow (md 1 1 auto) — condo/score must fill whitespace')
  ok = false
}

if (/ccHeaderQuickStatsSx[\s\S]{0,300}repeat\(2,\s*minmax\(0,\s*1fr\)\)/.test(chrome)) {
  console.error('FORBID: KPI 1fr 1fr columns spread Last sale away from Est (internal canyon)')
  ok = false
}

if (!/clamp\(12rem,\s*16vw,\s*300px\)/.test(chrome)) {
  console.error('Missing trail panel clamp(12rem, 16vw, 300px)')
  ok = false
}

if (!/clamp\(12rem,\s*16vw,\s*300px\)/.test(score) || !/clamp\(12rem,\s*16vw,\s*300px\)/.test(condo)) {
  console.error('Panel wrappers must use clamp(12rem, 16vw, 300px)')
  ok = false
}

if (!/flexWrap:\s*\{\s*xs:\s*['"]wrap['"],\s*md:\s*['"]nowrap['"]/.test(ulcc)) {
  console.error('FORBID: property-overview-header must use md flexWrap nowrap (one bar)')
  ok = false
}

if (!/flexWrap:\s*\{\s*xs:\s*['"]wrap['"],\s*md:\s*['"]nowrap['"]/.test(harness)) {
  console.error('FORBID: packing harness must use md flexWrap nowrap (match production)')
  ok = false
}

if (/width:\s*1280/.test(harness) && /maxWidth:\s*1280/.test(harness)) {
  console.error('FORBID: packing harness fixed 1280 width — must be fluid for multi-width gate')
  ok = false
}

if (!/export const ccHeaderPaperSx/.test(chrome)) {
  console.error('Missing ccHeaderPaperSx (overflow visible header surface)')
  ok = false
}

if (!/overflow:\s*['"]visible['"]/.test(chrome.match(/ccHeaderPaperSx[\s\S]{0,400}/)?.[0] || '')) {
  console.error('ccHeaderPaperSx must set overflow visible')
  ok = false
}

if (!ulcc.includes('ccHeaderPaperSx')) {
  console.error('UnifiedLeadCommandCenter must use ccHeaderPaperSx on property-overview-header')
  ok = false
}

if (!ok) process.exit(1)
console.log('cc-header slack-park forbid OK')
