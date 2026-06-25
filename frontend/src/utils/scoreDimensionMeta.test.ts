import { describe, it, expect } from 'vitest'
import { getDimensionMeta, getScoreVersionMeta } from './scoreDimensionMeta'

describe('scoreDimensionMeta', () => {
  it('returns residential unit count metadata', () => {
    const meta = getDimensionMeta('unit_count_fit', 'residential_v1_internal_data')
    expect(meta.label).toBe('Unit Count Fit')
    expect(meta.maxPoints).toBe(15)
    expect(meta.dataSource).toMatch(/Units field/i)
  })

  it('returns absentee owner metadata', () => {
    const meta = getDimensionMeta('absentee_owner', 'residential_v1_internal_data')
    expect(meta.label).toBe('Absentee Owner')
    expect(meta.maxPoints).toBe(10)
    expect(meta.description).toMatch(/mailing address/i)
  })

  it('explains residential score version in plain language', () => {
    const meta = getScoreVersionMeta('residential_v1_internal_data')
    expect(meta.shortLabel).toBe('Residential (v1)')
    expect(meta.description).toMatch(/two scoring models/i)
  })
})
