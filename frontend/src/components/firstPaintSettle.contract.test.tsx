/**
 * First-paint settle contracts for plan surfaces (log note/email next-step,
 * mail history under At a glance, residential header KPI centering).
 * Live-UI / packing geometry provide visual proof; these lock landmarks in source.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(__dirname, '../..')

function readSrc(rel: string): string {
  return readFileSync(resolve(ROOT, rel), 'utf8')
}

describe('first-paint settle contracts', () => {
  it('Log note/email always mount ActivityNextStepPanel landmarks', () => {
    const form = readSrc('src/components/LogActivityForm.tsx')
    const panel = readSrc('src/components/ActivityNextStepPanel.tsx')
    expect(form).toContain('ActivityNextStepPanel')
    // Next-step column is always mounted (7/5 grid) — no mode gate flag.
    expect(form).toContain('<Grid item xs={12} md={5}>{nextStepPanel}</Grid>')
    expect(form).not.toContain('showNextStepSection')
    expect(panel).toContain('activity-next-step-actions')
    expect(panel).toContain('complete-activity-task-checkbox')
    expect(panel).toContain('create-follow-up-checkbox')
  })

  it('Mail history settles under At a glance (PropertyKpiCard), not Marketing tab', () => {
    const kpi = readSrc('src/components/lead-detail/PropertyKpiCard.tsx')
    const panel = readSrc('src/components/lead-detail/LeadDetailTabPanel.tsx')
    const section = readSrc('src/components/lead-detail/MailHistorySection.tsx')
    expect(kpi).toContain('MailHistorySection')
    expect(section).toContain('mail-history-section')
    expect(panel).not.toContain('aria-label="Mail history"')
  })

  it('Residential header uses centered KPI band tokens', () => {
    const ulcc = readSrc('src/components/UnifiedLeadCommandCenter.tsx')
    const chrome = readSrc('src/components/lead-detail/commandCenterChrome.ts')
    expect(ulcc).toContain('centerInGap')
    expect(ulcc).toContain('ccHeaderTrailingPanelsSx')
    expect(ulcc).not.toContain('ccHeaderTrailingPanelsHugSx')
    expect(chrome).toContain('ccHeaderQuickStatsCenteredSx')
    expect(chrome).not.toContain('ccHeaderTrailingPanelsHugSx')
  })
})
