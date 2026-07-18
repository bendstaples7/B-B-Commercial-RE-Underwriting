import { describe, expect, it } from 'vitest'
import { formatDate } from '@/utils/formatters'

describe('formatDate', () => {
  it('parses YYYY-MM-DD as a local calendar date without shifting days', () => {
    expect(formatDate('2024-07-17')).toMatch(/7\/17\/2024/)
  })
})
