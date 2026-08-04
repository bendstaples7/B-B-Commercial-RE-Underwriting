/**
 * Contract / forbid: detailed Mail history table lives only in MailHistorySection
 * (mounted under At a glance). Must not reappear in LeadDetailTabPanel or ActivityPanel.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = resolve(__dirname, '../../..')

function readSrc(rel: string): string {
  return readFileSync(resolve(ROOT, rel), 'utf8')
}

describe('mail history surface contracts', () => {
  it('MailHistorySection owns the detailed table + testid', () => {
    const section = readSrc('src/components/lead-detail/MailHistorySection.tsx')
    expect(section).toContain('data-testid="mail-history-section"')
    expect(section).toContain('id="mail-history-section"')
    expect(section).toContain('aria-label="Mail history"')
    expect(section).toContain('resolveMailerHistorySummary')
    expect(section).toContain('Responses attributed to mail')
  })

  it('PropertyKpiCard mounts MailHistorySection after At a glance wide rows', () => {
    const kpi = readSrc('src/components/lead-detail/PropertyKpiCard.tsx')
    expect(kpi).toContain('MailHistorySection')
    expect(kpi).toMatch(/import\s*\{[^}]*MailHistorySection/)
    expect(kpi).not.toContain("id: 'mailer-history'")
    expect(kpi).not.toContain('formatMailerGlance')
  })

  it('forbids detailed Mail history markup in LeadDetailTabPanel and ActivityPanel', () => {
    const tabs = readSrc('src/components/lead-detail/LeadDetailTabPanel.tsx')
    // ActivityPanel is defined inline in UnifiedLeadCommandCenter (not a separate file).
    const ulcc = readSrc('src/components/UnifiedLeadCommandCenter.tsx')

    expect(tabs).not.toContain('aria-label="Mail history"')
    expect(tabs).not.toContain('Mail history')
    expect(tabs).not.toContain('Responses attributed to mail')
    expect(tabs).not.toContain('resolveMailerHistorySummary')
    expect(tabs).not.toContain('MailHistorySection')
    expect(tabs).toContain('Marketing lists')

    expect(ulcc).not.toContain('aria-label="Mail history"')
    expect(ulcc).not.toContain('MailHistorySection')
    expect(ulcc).not.toContain('Responses attributed to mail')
  })
})
