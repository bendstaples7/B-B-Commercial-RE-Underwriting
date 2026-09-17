import { describe, expect, it } from 'vitest'
import {
  duplicateConfidenceLabel,
  formatNeedsReviewReason,
  isDuplicateClusterReason,
} from './needsReviewReason'

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
