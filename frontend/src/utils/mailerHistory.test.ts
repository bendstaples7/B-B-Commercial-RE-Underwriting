import { describe, expect, it } from 'vitest'
import {
  formatMailerSentAtDisplay,
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

  it('coerces dict creative on API summary rows to a string label', () => {
    const api = {
      count: 1,
      last_sent_at: '2025-01-01',
      rows: [
        {
          id: 'mail-0',
          sent_at: '2025-01-01',
          label: "Standard, {'id': 'x', 'label': 'Bessy Tam'}",
          creative: {
            label: 'Bessy Tam',
            sender_display_name: 'Bessy Tam',
            first_name: 'Bessy',
            last_name: 'Tam',
          } as unknown as string | null,
          template_name: 'Standard',
          campaign_id: 1,
          olc_order_id: null,
          address_feedback: null,
          cancelled: false,
          source: 'olc' as const,
        },
      ],
    }
    const resolved = resolveMailerHistorySummary(api, null)
    expect(typeof resolved.rows[0].creative).toBe('string')
    expect(resolved.rows[0].creative).toBe('Bessy Tam')
    expect(resolved.rows[0].label).toBe('Standard, Bessy Tam')
  })

  it('rebuilds label when creative is an object even if label looks fine', () => {
    const api = {
      count: 1,
      last_sent_at: '2025-01-01',
      rows: [
        {
          id: 'mail-0',
          sent_at: '2025-01-01',
          label: 'Stale label',
          creative: { label: 'Bessy Tam' } as unknown as string | null,
          template_name: 'Standard',
          campaign_id: 1,
          olc_order_id: null,
          address_feedback: null,
          cancelled: false,
          source: 'olc' as const,
        },
      ],
    }
    const resolved = resolveMailerHistorySummary(api, null)
    expect(resolved.rows[0].label).toBe('Standard, Bessy Tam')
  })

  it('rebuilds label when string creative has whitespace before dict quote', () => {
    const api = {
      count: 1,
      last_sent_at: '2025-01-01',
      rows: [
        {
          id: 'mail-0',
          sent_at: '2025-01-01',
          label: 'Standard, { "label": "Bessy Tam" }',
          creative: 'Bessy Tam',
          template_name: 'Standard',
          campaign_id: 1,
          olc_order_id: null,
          address_feedback: null,
          cancelled: false,
          source: 'olc' as const,
        },
      ],
    }
    const resolved = resolveMailerHistorySummary(api, null)
    expect(resolved.rows[0].label).toBe('Standard, Bessy Tam')
  })

  it('parseMailerSentAt handles ISO and US dates', () => {
    expect(parseMailerSentAt('2024-06-01T00:00:00Z')).not.toBeNull()
    expect(parseMailerSentAt('6/21/2024')?.getTime()).toBe(parseMailerSentAt('2024-06-21')?.getTime())
    expect(parseMailerSentAt('6/21/99')?.getUTCFullYear()).toBe(1999)
    expect(parseMailerSentAt('6/21/24')?.getUTCFullYear()).toBe(2024)
    expect(parseMailerSentAt('nope')).toBeNull()
  })

  it('treats naive ISO datetimes as UTC', () => {
    const naive = parseMailerSentAt('2026-07-29T03:35:23.127597')
    const zulu = parseMailerSentAt('2026-07-29T03:35:23.127597Z')
    expect(naive?.getTime()).toBe(zulu?.getTime())
  })
})

describe('formatMailerSentAtDisplay', () => {
  it('formats naive UTC ISO timestamps in US Central Time', () => {
    expect(formatMailerSentAtDisplay('2026-07-29T03:35:23.127597')).toBe(
      'Jul 28, 2026, 10:35 PM CDT',
    )
    expect(formatMailerSentAtDisplay('2026-07-29T03:35:23.127597Z')).toBe(
      'Jul 28, 2026, 10:35 PM CDT',
    )
    expect(formatMailerSentAtDisplay('2026-01-15T18:00:00Z')).toBe(
      'Jan 15, 2026, 12:00 PM CST',
    )
  })

  it('can split date and Central Time onto two lines for narrow tables', () => {
    expect(
      formatMailerSentAtDisplay('2026-07-29T03:35:23.127597', { multiline: true }),
    ).toBe('Jul 28, 2026\n10:35 PM CDT')
  })

  it('keeps date-only values as calendar dates without a clock time', () => {
    expect(formatMailerSentAtDisplay('6/21/2024')).toBe('Jun 21, 2024')
    expect(formatMailerSentAtDisplay('2025-01-01')).toBe('Jan 1, 2025')
  })

  it('returns an em dash for missing or invalid values', () => {
    expect(formatMailerSentAtDisplay(null)).toBe('—')
    expect(formatMailerSentAtDisplay('')).toBe('—')
    expect(formatMailerSentAtDisplay('not-a-date')).toBe('—')
  })
})
