import React from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as fc from 'fast-check'
import { ComparableReviewTable } from './ComparableReviewTable'
import {
  ComparableSale,
  PropertyType,
  ConstructionType,
  InteriorCondition,
} from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a minimal valid ComparableSale for use in tests. */
function makeComparable(overrides: Partial<ComparableSale> = {}): ComparableSale {
  return {
    id: 'test-1',
    address: '123 Main St',
    saleDate: '2024-01-15',
    salePrice: 250000,
    propertyType: PropertyType.SINGLE_FAMILY,
    units: 1,
    bedrooms: 3,
    bathrooms: 2,
    squareFootage: 1500,
    lotSize: 6000,
    yearBuilt: 1990,
    constructionType: ConstructionType.FRAME,
    interiorCondition: InteriorCondition.AVERAGE,
    distanceMiles: 0.5,
    coordinates: { lat: 41.8781, lng: -87.6298 },
    ...overrides,
  }
}

/** Build 10 comparables (minimum required to enable Approve button). */
function makeComparables(count = 10, overrides: Partial<ComparableSale> = {}): ComparableSale[] {
  return Array.from({ length: count }, (_, i) =>
    makeComparable({ id: `test-${i + 1}`, address: `${100 + i} Main St`, ...overrides })
  )
}

function renderTable(
  comparables: ComparableSale[],
  onComparablesChange = vi.fn(),
  onApprove = vi.fn()
) {
  return render(
    <ComparableReviewTable
      comparables={comparables}
      onComparablesChange={onComparablesChange}
      onApprove={onApprove}
    />
  )
}

// ---------------------------------------------------------------------------
// Task 11.3 — Property 10: Similarity notes truncation threshold
// Feature: gemini-comparable-search, Property 10: Similarity notes truncation threshold
// Validates: Requirements 5.2
// ---------------------------------------------------------------------------

describe('Property 10: Similarity notes truncation threshold', () => {
  it('always shows first 100 chars and a "…more" affordance for strings longer than 100 chars', () => {
    // fc.property(fc.string({ minLength: 101 }), ...)
    fc.assert(
      fc.property(fc.string({ minLength: 101 }), (notes) => {
        const { unmount, container } = renderTable([
          makeComparable({ id: 'p10', similarityNotes: notes }),
        ])

        const expected100 = notes.slice(0, 100)
        const beyond100 = notes.slice(100)

        // A "…more" button must be present (truncation affordance)
        const moreButton = screen.getByRole('button', { name: /…more/i })
        expect(moreButton).toBeTruthy()

        // The cell's text content must include the first 100 characters.
        // We find the table cell that contains the "…more" button and check its text.
        const cell = moreButton.closest('td')
        expect(cell).not.toBeNull()
        const cellText = cell!.textContent ?? ''
        expect(cellText).toContain(expected100)

        // Characters beyond position 100 must NOT be visible before activation.
        // The cell text should not contain the characters that come after position 100.
        // (The cell only renders the first 100 chars + the button label "…more".)
        // We verify the full notes string is not present in the cell.
        expect(cellText).not.toContain(notes)

        // Additionally, the beyond-100 suffix should not appear anywhere in the document
        // as a standalone text node (i.e., not rendered in any element's textContent
        // except as part of the full string — which we already confirmed is absent).
        // We check that no element's textContent equals the full notes string.
        const allElements = Array.from(container.querySelectorAll('*'))
        const fullTextPresent = allElements.some((el) => el.textContent === notes)
        expect(fullTextPresent).toBe(false)

        unmount()
      }),
      { numRuns: 100 }
    )
  })
})

// ---------------------------------------------------------------------------
// Task 11.4 — Example unit tests for ComparableReviewTable similarity notes column
// ---------------------------------------------------------------------------

describe('ComparableReviewTable — Similarity Notes column', () => {
  describe('column header ordering', () => {
    it('renders "Similarity Notes" column header before "Actions" column header', () => {
      renderTable(makeComparables())

      const headers = screen.getAllByRole('columnheader')
      const headerTexts = headers.map((h) => h.textContent?.trim())

      const simNotesIdx = headerTexts.findIndex((t) => t === 'Similarity Notes')
      const actionsIdx = headerTexts.findIndex((t) => t === 'Actions')

      expect(simNotesIdx).toBeGreaterThanOrEqual(0)
      expect(actionsIdx).toBeGreaterThanOrEqual(0)
      expect(simNotesIdx).toBeLessThan(actionsIdx)
    })
  })

  describe('truncated cell expansion', () => {
    it('shows full text after clicking "…more" on a truncated cell', async () => {
      const user = userEvent.setup()
      const longNotes = 'A'.repeat(50) + 'B'.repeat(50) + 'C'.repeat(50) // 150 chars total

      renderTable([makeComparable({ similarityNotes: longNotes })])

      // Before clicking: only first 100 chars visible, full text not present
      expect(screen.queryByText(longNotes)).toBeNull()
      expect(screen.getByRole('button', { name: /…more/i })).toBeTruthy()

      // Click "…more"
      await user.click(screen.getByRole('button', { name: /…more/i }))

      // After clicking: full text should now be visible
      expect(screen.getByText((content) => content.includes(longNotes))).toBeTruthy()
    })
  })

  describe('null/empty similarityNotes', () => {
    it('renders an empty cell when similarityNotes is null', () => {
      renderTable([makeComparable({ similarityNotes: null })])

      // No "…more" button should be present
      expect(screen.queryByRole('button', { name: /…more/i })).toBeNull()
    })

    it('renders an empty cell when similarityNotes is undefined', () => {
      renderTable([makeComparable({ similarityNotes: undefined })])

      expect(screen.queryByRole('button', { name: /…more/i })).toBeNull()
    })

    it('renders an empty cell when similarityNotes is an empty string', () => {
      renderTable([makeComparable({ similarityNotes: '' })])

      expect(screen.queryByRole('button', { name: /…more/i })).toBeNull()
    })
  })

  describe('short notes (≤ 100 chars)', () => {
    it('renders the full text without a "…more" button when notes are 100 chars or fewer', () => {
      const shortNotes = 'Close proximity and similar square footage.'
      renderTable([makeComparable({ similarityNotes: shortNotes })])

      expect(screen.getByText(shortNotes)).toBeTruthy()
      expect(screen.queryByRole('button', { name: /…more/i })).toBeNull()
    })

    it('renders the full text without a "…more" button when notes are exactly 100 chars', () => {
      const exactNotes = 'X'.repeat(100)
      renderTable([makeComparable({ similarityNotes: exactNotes })])

      expect(screen.getByText(exactNotes)).toBeTruthy()
      expect(screen.queryByRole('button', { name: /…more/i })).toBeNull()
    })
  })
})
