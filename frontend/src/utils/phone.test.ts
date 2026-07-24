import { describe, expect, it } from 'vitest'
import { formatPhoneNumber, looksLikePhoneNumber, phoneCopyText, phoneTelHref } from './phone'

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

describe('looksLikePhoneNumber', () => {
  it('detects formatted and raw US phones', () => {
    expect(looksLikePhoneNumber('(708) 222-6620')).toBe(true)
    expect(looksLikePhoneNumber('7082226620')).toBe(true)
    expect(looksLikePhoneNumber('+1 708-222-6620')).toBe(true)
  })

  it('rejects emails and short digit strings', () => {
    expect(looksLikePhoneNumber('ssuperman0018@yahoo.com')).toBe(false)
    expect(looksLikePhoneNumber('12345')).toBe(false)
    expect(looksLikePhoneNumber('')).toBe(false)
    expect(looksLikePhoneNumber(null)).toBe(false)
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
