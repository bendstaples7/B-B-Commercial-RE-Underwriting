import { describe, expect, it } from 'vitest'
import {
  formatSaleDateFreshness,
  isSaleDateVerifiedWithinDays,
} from './saleDateFreshness'

describe('isSaleDateVerifiedWithinDays', () => {
  const now = new Date('2026-07-16T12:00:00Z')

  it('is true when success check is within 30 days', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-07-01T12:00:00Z', status: 'success' },
        30,
        now,
      ),
    ).toBe(true)
  })

  it('is false when last_checked_at is older than 30 days', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-05-01T12:00:00Z', status: 'success' },
        30,
        now,
      ),
    ).toBe(false)
  })

  it('ignores last_updated_at without a check stamp', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_updated_at: '2026-07-15T12:00:00Z', status: 'success' },
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

  it('is false for no_sale when a sale date is still displayed', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-07-15T12:00:00Z', status: 'no_sale' },
        30,
        now,
        { hasDisplayedSale: true },
      ),
    ).toBe(false)
  })

  it('is true for no_sale when no sale date is displayed', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-07-15T12:00:00Z', status: 'no_sale' },
        30,
        now,
        { hasDisplayedSale: false },
      ),
    ).toBe(true)
  })

  it('is false for legacy no_results without sale confirmation', () => {
    expect(
      isSaleDateVerifiedWithinDays(
        { last_checked_at: '2026-07-15T12:00:00Z', status: 'no_results' },
        30,
        now,
      ),
    ).toBe(false)
  })
})

describe('formatSaleDateFreshness', () => {
  it('says confirmed as of for success', () => {
    expect(
      formatSaleDateFreshness({
        last_checked_at: '2024-03-15T12:00:00Z',
        source: 'Cook County records',
        status: 'success',
      }),
    ).toBe('Confirmed as of Mar 2024')
  })

  it('prefers last_checked_at over last_updated_at', () => {
    expect(
      formatSaleDateFreshness({
        last_updated_at: '2023-01-01T12:00:00Z',
        last_checked_at: '2024-03-15T12:00:00Z',
        status: 'success',
      }),
    ).toBe('Confirmed as of Mar 2024')
  })

  it('falls back to last_updated_at', () => {
    expect(
      formatSaleDateFreshness({
        last_updated_at: '2024-03-15T12:00:00Z',
        source: 'Import',
      }),
    ).toBe('Updated Mar 2024')
  })

  it('returns null when no timestamp', () => {
    expect(formatSaleDateFreshness(null)).toBeNull()
    expect(formatSaleDateFreshness({})).toBeNull()
  })

  it('returns null for invalid timestamp', () => {
    expect(formatSaleDateFreshness({ last_checked_at: 'not-a-date' })).toBeNull()
  })

  it('says cannot confirm when sale is displayed but probe found none', () => {
    expect(
      formatSaleDateFreshness(
        {
          last_checked_at: '2026-07-17T12:00:00Z',
          source: 'Cook County records',
          status: 'no_sale',
        },
        { hasDisplayedSale: true },
      ),
    ).toBe('Cannot confirm as of Jul 2026')
  })

  it('says no sale found when display is empty after no_sale probe', () => {
    expect(
      formatSaleDateFreshness(
        {
          last_checked_at: '2026-07-17T12:00:00Z',
          source: 'Cook County records',
          status: 'no_sale',
        },
        { hasDisplayedSale: false },
      ),
    ).toBe('No sale found as of Jul 2026')
  })

  it('says check failed as of for failed status', () => {
    expect(
      formatSaleDateFreshness({
        last_checked_at: '2026-07-17T12:00:00Z',
        status: 'failed',
      }),
    ).toBe('Check failed as of Jul 2026')
  })
})
