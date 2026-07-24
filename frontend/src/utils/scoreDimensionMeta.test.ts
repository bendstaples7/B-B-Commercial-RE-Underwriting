import { describe, it, expect } from 'vitest'
import { getDimensionMeta, getScoreVersionMeta } from './scoreDimensionMeta'

describe('scoreDimensionMeta', () => {
  it('returns residential unit count metadata', () => {
    const meta = getDimensionMeta('unit_count_fit', 'residential_v1_internal_data')
    expect(meta.label).toBe('Ideal unit count')
    expect(meta.maxPoints).toBe(15)
    expect(meta.dataSource).toMatch(/Units field/i)
  })

  it('returns absentee owner metadata', () => {
    const meta = getDimensionMeta('absentee_owner', 'residential_v1_internal_data')
    expect(meta.label).toBe('Absentee owner')
    expect(meta.maxPoints).toBe(10)
    expect(meta.description).toMatch(/mailing address/i)
  })

  it('uses plain labels for unified equity and heuristics dimensions', () => {
    expect(getDimensionMeta('property_equity', 'unified_v1_residential').label).toBe('High equity')
    expect(getDimensionMeta('property_heuristics', 'unified_v1_residential').label).toBe(
      'Strong property details',
    )
    expect(getDimensionMeta('contactability', 'unified_v1_residential').label).toBe(
      'Owner researched',
    )
    expect(getDimensionMeta('ownership_duration', 'unified_v1_residential').label).toBe(
      'Long ownership',
    )
  })

  it('explains residential score version in plain language', () => {
    const meta = getScoreVersionMeta('residential_v1_internal_data')
    expect(meta.shortLabel).toBe('Residential (v1)')
    expect(meta.description).toMatch(/two scoring models/i)
  })
})
