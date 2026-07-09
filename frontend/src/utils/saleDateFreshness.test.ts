import { describe, expect, it } from 'vitest'
import { formatSaleDateFreshness } from './saleDateFreshness'

describe('formatSaleDateFreshness', () => {
  it('formats updated date and source', () => {
    const text = formatSaleDateFreshness({
      last_updated_at: '2024-03-15T12:00:00Z',
      source: 'Cook County records',
    })
    expect(text).toMatch(/Updated .* · Cook County records/)
  })

  it('returns null when no timestamp', () => {
    expect(formatSaleDateFreshness(null)).toBeNull()
    expect(formatSaleDateFreshness({})).toBeNull()
  })

  it('returns null for invalid timestamp', () => {
    expect(formatSaleDateFreshness({ last_updated_at: 'not-a-date' })).toBeNull()
  })

  it('omits source when whitespace-only', () => {
    const text = formatSaleDateFreshness({
      last_updated_at: '2024-03-15T12:00:00Z',
      source: '   ',
    })
    expect(text).toMatch(/^Updated /)
    expect(text).not.toContain('·')
  })
})
