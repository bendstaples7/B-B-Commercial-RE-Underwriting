import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { computeTotalPages, clampPage } from './pagination'

// Feature: queue-pagination, Property 4: totalPages computation is correct for all positive totals
describe('computeTotalPages', () => {
  it('P4: result equals Math.ceil(total / perPage) for all positive totals', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 1_000_000 }),
        fc.integer({ min: 1, max: 100 }),
        (total, perPage) => {
          expect(computeTotalPages(total, perPage)).toBe(Math.ceil(total / perPage))
        }
      ),
      { numRuns: 100 }
    )
  })

  it('P4: returns 0 when total is 0', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 100 }),
        (perPage) => {
          expect(computeTotalPages(0, perPage)).toBe(0)
        }
      ),
      { numRuns: 100 }
    )
  })
})

// Feature: queue-pagination, Property 3: Page clamping holds for all integer inputs
describe('clampPage', () => {
  it('P3: result is always in [1, totalPages] for all integer inputs', () => {
    fc.assert(
      fc.property(
        fc.integer(),
        fc.integer({ min: 1 }),
        (requestedPage, totalPages) => {
          const result = clampPage(requestedPage, totalPages)
          expect(result).toBeGreaterThanOrEqual(1)
          expect(result).toBeLessThanOrEqual(totalPages)
        }
      ),
      { numRuns: 100 }
    )
  })

  it('P3: values below 1 clamp to 1', () => {
    fc.assert(
      fc.property(
        fc.integer({ max: 0 }),
        fc.integer({ min: 1 }),
        (requestedPage, totalPages) => {
          expect(clampPage(requestedPage, totalPages)).toBe(1)
        }
      ),
      { numRuns: 100 }
    )
  })

  it('P3: values above totalPages clamp to totalPages', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1 }),
        (totalPages) => {
          expect(clampPage(totalPages + 1, totalPages)).toBe(totalPages)
          expect(clampPage(totalPages + 100, totalPages)).toBe(totalPages)
        }
      ),
      { numRuns: 100 }
    )
  })

  it('P3: values in range are returned unchanged', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1 }),
        fc.integer({ min: 1 }),
        (totalPages, offset) => {
          const page = ((offset - 1) % totalPages) + 1 // map to [1, totalPages]
          expect(clampPage(page, totalPages)).toBe(page)
        }
      ),
      { numRuns: 100 }
    )
  })
})
