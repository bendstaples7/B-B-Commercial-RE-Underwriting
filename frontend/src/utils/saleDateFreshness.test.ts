import { describe, expect, it } from 'vitest'
import {
  formatSaleDateFreshness,
  isSaleDateVerifiedWithinDays,
} from './saleDateFreshness'

describe('isSaleDateVerifiedWithinDays', () => {
  const now = new Date('2026-07-16T12:00:00Z')

  it('is true when last_checked_at is within 30 days', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-07-01T12:00:00Z', status: 'ok' },
        30,
        now,
      ),
    ).toBe(true)
  })

  it('is false when last_checked_at is older than 30 days', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-05-01T12:00:00Z' },
        30,
        now,
      ),
    ).toBe(false)
  })

  it('ignores last_updated_at without a check stamp', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_updated_at: '2026-07-15T12:00:00Z' },
        30,
        now,
      ),
    ).toBe(false)
  })

  it('is false for failed checks', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-07-15T12:00:00Z', status: 'failed' },
        30,
        now,
      ),
    ).toBe(false)
  })

  it('treats no_results as a successful verification', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-07-15T12:00:00Z', status: 'no_results' },
        30,
        now,
      ),
    ).toBe(true)
  })
})

describe('formatSaleDateFreshness', () => {
  it('formats last checked date and source', () => {
    const text = formatSaleDateFreshness({
      last_checked_at: '2024-03-15T12:00:00Z',
      source: 'Cook County records',
    })
    expect(text).toMatch(/Last checked .* · Cook County records/)
  })

  it('prefers last_checked_at over last_updated_at', () => {
    const text = formatSaleDateFreshness({
      last_updated_at: '2023-01-01T12:00:00Z',
      last_checked_at: '2024-03-15T12:00:00Z',
      source: 'Cook County records',
    })
    expect(text).toMatch(/Last checked Mar 2024/)
  })

  it('falls back to last_updated_at', () => {
    const text = formatSaleDateFreshness({
      last_updated_at: '2024-03-15T12:00:00Z',
      source: 'Import',
    })
    expect(text).toMatch(/Updated .* · Import/)
  })

  it('returns null when no timestamp', () => {
    expect(formatSaleDateFreshness(null)).toBeNull()
    expect(formatSaleDateFreshness({})).toBeNull()
  })

  it('returns null for invalid timestamp', () => {
    expect(formatSaleDateFreshness({ last_checked_at: 'not-a-date' })).toBeNull()
  })

  it('omits source when whitespace-only', () => {
    const text = formatSaleDateFreshness({
      last_checked_at: '2024-03-15T12:00:00Z',
      source: '   ',
    })
    expect(text).toMatch(/^Last checked /)
    expect(text).not.toContain('·')
  })

  it('labels checked sources that returned no sale', () => {
    const text = formatSaleDateFreshness({
      last_checked_at: '2024-03-15T12:00:00Z',
      source: 'Cook County records',
      status: 'no_results',
    })
    expect(text).toMatch(/Cook County records \(no sale found\)/)
  })
})
