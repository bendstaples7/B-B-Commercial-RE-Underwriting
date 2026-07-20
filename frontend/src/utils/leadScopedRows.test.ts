import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import {
  scopeRowsToLead,
  scopeRowsToLeadWithTotal,
  scopedListTotal,
  resetLeadScopeReportCacheForTests,
} from '@/utils/leadScopedRows'

describe('scopeRowsToLead', () => {
  beforeEach(() => {
    resetLeadScopeReportCacheForTests()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps rows for the active lead and rows without lead_id', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const rows = [
      { id: 1, lead_id: 4404, summary: 'mine' },
      { id: 2, lead_id: 3415, summary: 'gilberto' },
      { id: 3, summary: 'optimistic' },
    ]
    const scoped = scopeRowsToLead(rows, 4404, 'timeline')
    expect(scoped.map((r) => r.id)).toEqual([1, 3])
    expect(errorSpy).toHaveBeenCalledTimes(1)
    expect(String(errorSpy.mock.calls[0]?.[0])).toContain('foreign lead_id')
    expect(String(errorSpy.mock.calls[0]?.[0])).toContain('active=4404')
  })

  it('returns the same array contents when nothing is foreign', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const rows = [
      { id: 1, lead_id: 10 },
      { id: 2, lead_id: 10 },
    ]
    expect(scopeRowsToLead(rows, 10, 'tasks')).toEqual(rows)
    expect(errorSpy).not.toHaveBeenCalled()
  })

  it('does not re-log the same drop set on repeated calls', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const rows = [
      { id: 1, lead_id: 4404 },
      { id: 2, lead_id: 3415 },
    ]
    scopeRowsToLead(rows, 4404, 'timeline')
    scopeRowsToLead(rows, 4404, 'timeline')
    scopeRowsToLead(rows, 4404, 'timeline')
    expect(errorSpy).toHaveBeenCalledTimes(1)
  })

  it('logs again when the dropped id set changes', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    scopeRowsToLead(
      [{ id: 1, lead_id: 4404 }, { id: 2, lead_id: 3415 }],
      4404,
      'timeline',
    )
    scopeRowsToLead(
      [{ id: 1, lead_id: 4404 }, { id: 9, lead_id: 999 }],
      4404,
      'timeline',
    )
    expect(errorSpy).toHaveBeenCalledTimes(2)
  })
})

describe('scopedListTotal / scopeRowsToLeadWithTotal', () => {
  beforeEach(() => {
    resetLeadScopeReportCacheForTests()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps server total when nothing was dropped', () => {
    expect(scopedListTotal(50, 10, 0)).toBe(50)
  })

  it('shrinks total when foreign rows were stripped', () => {
    expect(scopedListTotal(12, 10, 2)).toBe(10)
    expect(scopedListTotal(2, 1, 1)).toBe(1)
  })

  it('scopeRowsToLeadWithTotal adjusts total alongside rows', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const result = scopeRowsToLeadWithTotal(
      [
        { id: 1, lead_id: 4404 },
        { id: 2, lead_id: 3415 },
      ],
      4404,
      'timeline',
      2,
    )
    expect(result.rows.map((r) => r.id)).toEqual([1])
    expect(result.total).toBe(1)
    expect(result.droppedCount).toBe(1)
  })
})
