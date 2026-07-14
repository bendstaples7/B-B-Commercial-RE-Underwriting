/**
 * stripHtmlTags — no-innerHTML entity decode + entity-encoded tag scrub.
 */
import { describe, it, expect } from 'vitest'
import { stripHtmlTags } from '@/utils/helpers'

describe('stripHtmlTags', () => {
  it('strips tags and decodes entities without DOM', () => {
    expect(stripHtmlTags('<p>Hello&nbsp;<b>world</b></p>')).toBe('Hello world')
  })

  it('does not rehydrate entity-encoded markup via innerHTML', () => {
    const sneaky = '&lt;img src=x onerror=alert(1)&gt;Hi'
    expect(stripHtmlTags(sneaky)).toBe('Hi')
    expect(stripHtmlTags(sneaky)).not.toContain('<img')
  })

  it('collapses whitespace', () => {
    expect(stripHtmlTags('<div>a</div><div>b</div>')).toBe('a b')
  })
})
