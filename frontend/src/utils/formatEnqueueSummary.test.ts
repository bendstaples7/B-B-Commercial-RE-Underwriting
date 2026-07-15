import { describe, it, expect } from 'vitest'
import {
  enqueueResultSeverity,
  formatEnqueuePreview,
  formatEnqueueSummary,
} from './formatEnqueueSummary'

describe('formatEnqueueSummary', () => {
  it('formats per-status breakdown from results', () => {
    expect(
      formatEnqueueSummary({
        added: 2,
        skipped: 18,
        invalid: 0,
        results: [
          { lead_id: 1, status: 'queued' },
          { lead_id: 2, status: 'queued' },
          ...Array.from({ length: 18 }, (_, i) => ({
            lead_id: i + 3,
            status: 'already_queued',
          })),
        ],
      }),
    ).toBe('Added 2 · 18 already in batch')
  })

  it('formats invalid address count', () => {
    expect(
      formatEnqueueSummary({
        added: 2,
        skipped: 0,
        invalid: 18,
        results: [
          { lead_id: 1, status: 'queued' },
          { lead_id: 2, status: 'queued' },
          { lead_id: 3, status: 'invalid_address', error: 'Incomplete city/state/zip for mailing address' },
        ],
      }),
    ).toBe('Added 2 · 1 invalid address')
  })

  it('returns fallback when nothing added', () => {
    expect(formatEnqueueSummary({ added: 0, skipped: 0, invalid: 0 })).toBe('No leads added')
  })

  it('formats soft-fail errors from results', () => {
    expect(
      formatEnqueueSummary({
        added: 2,
        skipped: 1,
        invalid: 0,
        results: [
          { lead_id: 1, status: 'queued' },
          { lead_id: 2, status: 'queued' },
          { lead_id: 3, status: 'error', error: 'Could not queue lead' },
        ],
      }),
    ).toBe('Added 2 · 1 could not queue')
  })

  it('surfaces a recent-sale rejection as an error, not success', () => {
    const result = {
      added: 0,
      skipped: 1,
      invalid: 0,
      results: [{ lead_id: 1, status: 'recently_sold' }],
    }
    expect(formatEnqueueSummary(result)).toBe('1 recently sold')
    expect(enqueueResultSeverity(result)).toBe('error')
  })

  it('uses warning severity for mixed outcomes', () => {
    expect(enqueueResultSeverity({ added: 1, skipped: 1, invalid: 0 })).toBe('warning')
  })
})

describe('formatEnqueuePreview', () => {
  it('formats dry-run counts', () => {
    expect(
      formatEnqueuePreview({ would_add: 140, would_skip: 0, would_fail: 2 }),
    ).toBe('140 ready to add · 2 would fail validation')
  })
})
