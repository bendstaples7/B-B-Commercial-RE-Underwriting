import { describe, expect, it } from 'vitest'
import { formatDate, formatPropertyTypeLabel } from '@/utils/formatters'

describe('formatDate', () => {
  it('parses YYYY-MM-DD as a local calendar date without shifting days', () => {
    const expected = new Date(2024, 6, 17).toLocaleDateString()
    expect(formatDate('2024-07-17')).toBe(expected)
    expect(formatDate('2024-07-17T00:00:00Z')).toBe(expected)
  })

  it('rejects invalid calendar dates instead of rolling over', () => {
    expect(formatDate('2024-02-30')).toBe('—')
    expect(formatDate('2024-13-01')).toBe('—')
  })
})

describe('formatPropertyTypeLabel', () => {
  it('title-cases raw property types', () => {
    expect(formatPropertyTypeLabel('triplex')).toBe('Triplex')
    expect(formatPropertyTypeLabel('TRIPLEX')).toBe('Triplex')
    expect(formatPropertyTypeLabel('multi_family')).toBe('Multi Family')
    expect(formatPropertyTypeLabel('multi family')).toBe('Multi Family')
  })
})
