import { describe, expect, it } from 'vitest'
import {
  formatMailSubmitReconciliationBanner,
  formatMailSubmitReconciliationTable,
} from './formatMailSubmitReconciliation'

describe('formatMailSubmitReconciliation', () => {
  const sample = {
    staged_count: 514,
    submitted_count: 501,
    invalid_at_submit_count: 13,
    submit_drop_summary: { 'Incomplete city/state/ZIP': 2 },
  }

  it('formats table caption when staged differs from submitted', () => {
    expect(formatMailSubmitReconciliationTable(sample)).toBe(
      'staged 514 · 13 invalid · 2× Incomplete city/state/ZIP',
    )
  })

  it('formats banner suffix when staged differs from submitted', () => {
    expect(formatMailSubmitReconciliationBanner(sample)).toBe(
      ' · Staged 514 → submitted 501 (13 invalid locally) · 2× Incomplete city/state/ZIP',
    )
  })

  it('returns null/empty when counts match or are missing', () => {
    expect(formatMailSubmitReconciliationTable({
      staged_count: 10,
      submitted_count: 10,
    })).toBeNull()
    expect(formatMailSubmitReconciliationBanner({
      staged_count: 10,
      submitted_count: 10,
    })).toBe('')
  })
})
