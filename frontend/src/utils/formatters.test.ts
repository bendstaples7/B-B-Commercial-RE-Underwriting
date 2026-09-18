import { describe, expect, it } from 'vitest'
import { formatAssessorPinAddress, formatDate, formatDateTime, formatLeadCategoryLabel, formatPropertyTypeLabel } from '@/utils/formatters'

describe('formatDate', () => {
  it('parses YYYY-MM-DD as a calendar date without shifting days', () => {
    expect(formatDate('2024-07-17')).toBe('Jul 17, 2024')
    expect(formatDate('6/21/2024')).toBe('Jun 21, 2024')
  })

  it('uses the Central calendar day for UTC datetimes', () => {
    expect(formatDate('2024-07-17T00:00:00Z')).toBe('Jul 16, 2024')
  })

  it('rejects invalid calendar dates instead of rolling over', () => {
    expect(formatDate('2024-02-30')).toBe('—')
    expect(formatDate('2024-13-01')).toBe('—')
    expect(formatDate('2/30/2024')).toBe('—')
  })
})

describe('formatDateTime', () => {
  it('formats naive UTC ISO timestamps in US Central Time', () => {
    expect(formatDateTime('2026-07-29T03:35:23.127597')).toBe('Jul 28, 2026, 10:35 PM CDT')
    expect(formatDateTime('2026-07-29T03:35:23.127597Z')).toBe('Jul 28, 2026, 10:35 PM CDT')
    expect(formatDateTime('2026-01-15T18:00:00Z')).toBe('Jan 15, 2026, 12:00 PM CST')
  })

  it('keeps date-only values as calendar dates without a clock time', () => {
    expect(formatDateTime('6/21/2024')).toBe('Jun 21, 2024')
    expect(formatDateTime('2025-01-01')).toBe('Jan 1, 2025')
  })

  it('can split date and Central Time onto two lines', () => {
    expect(formatDateTime('2026-07-29T03:35:23.127597', { multiline: true })).toBe(
      'Jul 28, 2026\n10:35 PM CDT',
    )
  })

  it('returns an em dash for missing or invalid values', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('')).toBe('—')
    expect(formatDateTime('not-a-date')).toBe('—')
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
