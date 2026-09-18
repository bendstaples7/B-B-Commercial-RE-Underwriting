import { describe, expect, it } from 'vitest'
import {
  duplicateConfidenceLabel,
  formatNeedsReviewReason,
  isDuplicateClusterReason,
  mergeDuplicateTwins,
} from './needsReviewReason'

describe('needsReviewReason', () => {
  it('unions cluster members into merge twins without duplicating situs hits', () => {
    const twins = mergeDuplicateTwins(
      10,
      [{ id: 20, owner_display_name: 'Ada', property_street: '100 Main', people_names: ['Ada'] }],
      {
        cluster_ids: [10, 20, 30],
        suggested_winner_id: 20,
        confidence: 'ambiguous',
        streets: { 10: '100 Main', 20: '100 Main', 30: '100 Main Unit 2' },
        members: [
          { id: 10, owner_display_name: 'Ada', property_street: '100 Main', people_names: [] },
          { id: 20, owner_display_name: 'Ada', property_street: '100 Main', people_names: [] },
          { id: 30, owner_display_name: 'Ada', property_street: '100 Main Unit 2', people_names: ['Ada'] },
        ],
      },
    )
    expect(twins.map((row) => row.id)).toEqual([20, 30])
    expect(twins.find((row) => row.id === 20)?.people_names).toEqual(['Ada'])
    expect(twins.find((row) => row.id === 30)?.property_street).toBe('100 Main Unit 2')
  })
})

describe('needsReviewReason', () => {
  it('formats possible duplicate records with winner and siblings', () => {
    expect(
      formatNeedsReviewReason({
        id: 10,
        review_reason: 'duplicate_lead_cluster',
        suggested_winner_id: 20,
        duplicate_cluster_ids: [10, 20, 30],
        duplicate_confidence: 'ambiguous',
      }),
    ).toBe('Possible duplicate records → keep #20 (+2) (ambiguous match)')
  })

  it('passes through non-duplicate reasons', () => {
    expect(
      formatNeedsReviewReason({
        review_reason: 'New HubSpot activity',
      }),
    ).toBe('New HubSpot activity')
  })

  it('labels confidence and detects duplicate reason', () => {
    expect(duplicateConfidenceLabel('clear')).toBe(' (clear match)')
    expect(duplicateConfidenceLabel(null)).toBe('')
    expect(isDuplicateClusterReason('duplicate_lead_cluster')).toBe(true)
    expect(isDuplicateClusterReason('New HubSpot activity')).toBe(false)
  })
})
