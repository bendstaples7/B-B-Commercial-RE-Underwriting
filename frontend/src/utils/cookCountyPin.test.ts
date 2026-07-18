import { describe, expect, it } from 'vitest'
import { formatCookCountyPin, normalizePinDigits } from './cookCountyPin'

describe('cookCountyPin', () => {
  it('formats 14-digit condensed PINs to dashed Cook County form', () => {
    expect(formatCookCountyPin('14284000080000')).toBe('14-28-400-008-0000')
  })

  it('keeps already-dashed 14-digit PINs', () => {
    expect(formatCookCountyPin('14-28-400-008-0000')).toBe('14-28-400-008-0000')
  })

  it('leaves non-14-digit values trimmed but unchanged', () => {
    expect(formatCookCountyPin('  ABC123  ')).toBe('ABC123')
    expect(formatCookCountyPin('123')).toBe('123')
  })

  it('normalizes digits by stripping dashes and spaces', () => {
    expect(normalizePinDigits('14-28-400-008-0000')).toBe('14284000080000')
  })
})
