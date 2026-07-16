import { describe, expect, it } from 'vitest'
import { formatDateOnly, formatShortCalendarDay, formatUtcDateRange } from './helpers'

describe('formatDateOnly', () => {
  it('formats ISO date-only values in local time', () => {
    expect(formatDateOnly('2026-07-15')).toBe(
      new Date(Date.UTC(2026, 6, 15)).toLocaleDateString(
        undefined,
        { timeZone: 'UTC' },
      ),
    )
  })

  it('uses the standard empty display for missing or invalid values', () => {
    expect(formatDateOnly(null)).toBe('—')
    expect(formatDateOnly('not-a-date')).toBe('—')
    expect(formatDateOnly('2026-02-30')).toBe('—')
  })
})

describe('formatUtcDateRange', () => {
  it('formats an exclusive end bound as an inclusive day range', () => {
    expect(formatUtcDateRange('2026-07-13T05:00:00Z', '2026-07-20T05:00:00Z')).toMatch(/Jul/)
  })
})

describe('formatShortCalendarDay', () => {
  it('includes weekday for a calendar date', () => {
    expect(formatShortCalendarDay('2026-07-15')).toMatch(/15/)
  })
})
