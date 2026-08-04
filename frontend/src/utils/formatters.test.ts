import { describe, expect, it } from 'vitest'
import { formatAssessorPinAddress, formatDate, formatLeadCategoryLabel, formatPropertyTypeLabel } from '@/utils/formatters'

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

describe('formatLeadCategoryLabel', () => {
  it('maps residential and commercial', () => {
    expect(formatLeadCategoryLabel('residential')).toBe('Residential')
    expect(formatLeadCategoryLabel('commercial')).toBe('Commercial')
    expect(formatLeadCategoryLabel('COMMERCIAL')).toBe('Commercial')
  })

  it('returns empty for blank', () => {
    expect(formatLeadCategoryLabel(null)).toBe('')
    expect(formatLeadCategoryLabel('')).toBe('')
  })
})

describe('formatAssessorPinAddress', () => {
  it('shows the PIN row street', () => {
    expect(formatAssessorPinAddress({ property_street: '3508 N Sacramento Ave' })).toBe(
      '3508 N Sacramento Ave',
    )
  })

  it('appends unit/apt when present on the row', () => {
    expect(
      formatAssessorPinAddress({ property_street: '3508 N Sacramento Ave', unit: 'Unit 2' }),
    ).toBe('3508 N Sacramento Ave, Unit 2')
    expect(
      formatAssessorPinAddress({ property_street: '3508 N Sacramento Ave', apt: 'Apt 3' }),
    ).toBe('3508 N Sacramento Ave, Apt 3')
  })

  it('falls back to an em dash when the row has no street', () => {
    expect(formatAssessorPinAddress({ property_street: null })).toBe('—')
    expect(formatAssessorPinAddress(null)).toBe('—')
    expect(formatAssessorPinAddress(undefined)).toBe('—')
  })
})
