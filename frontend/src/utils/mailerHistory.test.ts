import { describe, expect, it } from 'vitest'
import {
  mailerHistorySummary,
  parseMailerSentAt,
  resolveMailerHistorySummary,
} from './mailerHistory'

describe('mailerHistory', () => {
  it('parses legacy string with trailing date', () => {
    const summary = mailerHistorySummary('Boyfriend, OLM, Blue,  6/21/2024')
    expect(summary.count).toBe(1)
    expect(summary.rows[0].label).toBe('Boyfriend, OLM, Blue')
    expect(summary.rows[0].sent_at).toBe('6/21/2024')
  })

  it('prefers chronological last_sent over lexicographic', () => {
    const summary = mailerHistorySummary([
      { sent_at: '12/1/2024', template_name: 'Old' },
      { sent_at: '1/1/2025', template_name: 'New' },
    ])
    expect(summary.last_sent_at).toBe('1/1/2025')
  })

  it('uses API summary when present', () => {
    const api = {
      count: 2,
      last_sent_at: '2025-01-01',
      rows: [
        {
          id: 'mail-0',
          sent_at: '2025-01-01',
          label: 'From API',
          creative: null,
          template_name: null,
          campaign_id: null,
          olc_order_id: null,
          address_feedback: null,
          cancelled: false,
          source: 'imported' as const,
        },
      ],
    }
    const resolved = resolveMailerHistorySummary(api, 'ignored legacy')
    expect(resolved.last_sent_at).toBe('2025-01-01')
    expect(resolved.rows[0].label).toBe('From API')
  })

  it('parseMailerSentAt handles ISO and US dates', () => {
    expect(parseMailerSentAt('2024-06-01T00:00:00Z')).not.toBeNull()
    expect(parseMailerSentAt('6/21/2024')?.getMonth()).toBe(5)
    expect(parseMailerSentAt('nope')).toBeNull()
  })
})
