import { describe, it, expect } from 'vitest'
import {
  buildScorePathSummary,
  formatSignedPoints,
  partitionScoreDetails,
} from './scoreBreakdownSummary'

describe('formatSignedPoints', () => {
  it('uses true minus for negatives (no fake +)', () => {
    expect(formatSignedPoints(-40)).toBe('−40')
    expect(formatSignedPoints(-15)).toBe('−15')
    expect(formatSignedPoints(17.5)).toBe('+17.5')
    expect(formatSignedPoints(0)).toBe('0')
  })
})

describe('partitionScoreDetails', () => {
  it('splits helps vs adjustments and skips meta/attribution', () => {
    const { helps, adjustments, attribution } = partitionScoreDetails({
      property_equity: 17.5,
      ownership_duration: 15,
      pipeline_stage_bonus: -15,
      hubspot_engagement: -40,
      notes_keywords: 5,
      weighted_base: 48,
    })
    expect(helps.map(([k]) => k)).toEqual(['property_equity', 'ownership_duration'])
    expect(adjustments.map(([k, v]) => [k, v])).toEqual([
      ['hubspot_engagement', -40],
      ['pipeline_stage_bonus', -15],
    ])
    expect(attribution).toEqual([['notes_keywords', 5]])
  })
})

describe('buildScorePathSummary', () => {
  it('builds floored 9909-class equation from weighted_base', () => {
    const path = buildScorePathSummary(
      {
        weighted_base: 48,
        pipeline_stage_bonus: -15,
        hubspot_engagement: -40,
        property_equity: 17.5,
      },
      0,
    )
    expect(path.title).toBe('How we got to 0')
    expect(path.equation).toContain('Base ~48')
    expect(path.equation).toContain('− pipeline 15')
    expect(path.equation).toContain('− CRM 40')
    expect(path.equation).toContain('→ 0 (floored at 0)')
    expect(path.floored).toBe(true)
  })

  it('reports floored for legacy rows without fabricating a clamped base', () => {
    const path = buildScorePathSummary(
      {
        pipeline_stage_bonus: -15,
        hubspot_engagement: -40,
      },
      0,
    )
    expect(path.floored).toBe(true)
    expect(path.equation).toContain('→ 0 (floored at 0)')
    expect(path.equation).not.toMatch(/Base ~55/)
  })
})
