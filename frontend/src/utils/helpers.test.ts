import { describe, expect, it } from 'vitest'
import { formatShortCalendarDay, formatUtcDateRange } from './helpers'

describe('formatUtcDateRange', () => {
  it('formats an exclusive end bound as an inclusive day range', () => {
    expect(formatUtcDateRange('2026-07-13T05:00:00Z', '2026-07-20T05:00:00Z')).toBe(
      (() => {
        const start = new Date('2026-07-13T12:00:00')
        const end = new Date('2026-07-19T12:00:00')
        const opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }
        return `${start.toLocaleDateString(undefined, opts)} – ${end.toLocaleDateString(undefined, opts)}`
      })(),
    )
  })
})

describe('formatShortCalendarDay', () => {
  it('includes weekday for a calendar date', () => {
    expect(formatShortCalendarDay('2026-07-15')).toBe(
      new Date('2026-07-15T12:00:00').toLocaleDateString(undefined, {
        weekday: 'short',
        month: 'numeric',
        day: 'numeric',
      }),
    )
  })
})
