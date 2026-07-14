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

  it('preserves Cost < $500 style comparisons', () => {
    expect(stripHtmlTags('Cost is < $500')).toBe('Cost is < $500')
  })

  it('decodes emoji numeric entities with fromCodePoint', () => {
    expect(stripHtmlTags('Hi &#128512;')).toContain('😀')
  })

  it('strips tags whose attributes contain >', () => {
    expect(stripHtmlTags('<span title="a > b">Body</span>')).toBe('Body')
  })

  it('turns br with attributes into a space/newline then collapses', () => {
    expect(stripHtmlTags('A<br class="x">B')).toBe('A B')
  })
})
