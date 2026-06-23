import { describe, expect, it } from 'vitest'
import { formatPhoneNumber, phoneCopyText, phoneTelHref } from './phone'

describe('formatPhoneNumber', () => {
  it('formats 10-digit US numbers', () => {
    expect(formatPhoneNumber('6304305720')).toBe('(630) 430-5720')
    expect(formatPhoneNumber('630-430-5720')).toBe('(630) 430-5720')
  })

  it('formats 11-digit numbers with country code', () => {
    expect(formatPhoneNumber('16304305720')).toBe('(630) 430-5720')
    expect(formatPhoneNumber('+1 (630) 430-5720')).toBe('(630) 430-5720')
  })

  it('returns original when unrecognized', () => {
    expect(formatPhoneNumber('12345')).toBe('12345')
  })
})

describe('phoneTelHref', () => {
  it('uses +1 for 10-digit numbers', () => {
    expect(phoneTelHref('6304305720')).toBe('tel:+16304305720')
  })
})

describe('phoneCopyText', () => {
  it('copies E.164 for US numbers', () => {
    expect(phoneCopyText('(630) 430-5720')).toBe('+16304305720')
  })
})
