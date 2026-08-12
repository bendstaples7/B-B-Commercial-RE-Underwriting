import { describe, expect, it } from 'vitest'
import {
  formatAssessorBedsBaths,
  formatNoteUnitMixLabel,
} from '@/utils/notePropertyFacts'

describe('notePropertyFacts', () => {
  it('formats foster-shaped unit mix', () => {
    expect(
      formatNoteUnitMixLabel([
        { units: 4, beds: 2 },
        { units: 2, beds: 3 },
      ]),
    ).toBe('4×2 bd + 2×3 bd')
  })

  it('formats assessor beds/baths', () => {
    expect(formatAssessorBedsBaths(6, 6)).toBe('6 bd / 6 ba')
    expect(formatAssessorBedsBaths(null, null)).toBeNull()
  })
})
