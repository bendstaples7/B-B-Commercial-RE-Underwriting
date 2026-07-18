import { describe, expect, it } from 'vitest'
import { formatDate } from '@/utils/formatters'

describe('formatDate', () => {
  it('parses YYYY-MM-DD as a local calendar date without shifting days', () => {
    const expected = new Date(2024, 6, 17).toLocaleDateString()
    expect(formatDate('2024-07-17')).toBe(expected)
    expect(formatDate('2024-07-17T00:00:00Z')).toBe(expected)
  })
})
