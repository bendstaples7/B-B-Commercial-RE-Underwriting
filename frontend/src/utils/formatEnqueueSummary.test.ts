import { describe, it, expect } from 'vitest'
import { formatEnqueueSummary } from './formatEnqueueSummary'

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
})
