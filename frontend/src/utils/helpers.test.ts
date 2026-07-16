import { describe, expect, it } from 'vitest'
import { formatDateOnly } from './helpers'

describe('formatDateOnly', () => {
  it('formats ISO date-only values in local time', () => {
    expect(formatDateOnly('2026-07-15')).toBe(
      new Date('2026-07-15T00:00:00').toLocaleDateString(),
    )
  })

  it('uses the standard empty display for missing or invalid values', () => {
    expect(formatDateOnly(null)).toBe('—')
    expect(formatDateOnly('not-a-date')).toBe('—')
    expect(formatDateOnly('2026-02-30')).toBe('—')
  })
})
