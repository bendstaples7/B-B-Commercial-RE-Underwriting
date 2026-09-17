import { describe, expect, it } from 'vitest'
import {
  MAIL_CANDIDATE_ENQUEUE_MAX,
  clampMailAddCount,
  defaultMailAddCount,
  mailAddCountPresets,
  maxMailCandidateAddCount,
} from './mailCandidateEnqueue'

describe('mailCandidateEnqueue', () => {
  it('caps addable count at the backend enqueue maximum', () => {
    expect(maxMailCandidateAddCount(1520)).toBe(MAIL_CANDIDATE_ENQUEUE_MAX)
    expect(maxMailCandidateAddCount(40)).toBe(40)
    expect(maxMailCandidateAddCount(0)).toBe(0)
  })

  it('clamps typed counts into 1..maxAddable', () => {
    expect(clampMailAddCount('75', 100)).toBe(75)
    expect(clampMailAddCount(0, 100)).toBe(1)
    expect(clampMailAddCount(9999, 100)).toBe(100)
    expect(clampMailAddCount('nope', 100)).toBe(0)
    expect(clampMailAddCount(10, 0)).toBe(0)
  })

  it('defaults to remaining minimum when below batch floor', () => {
    expect(defaultMailAddCount(1520, 48)).toBe(48)
    expect(defaultMailAddCount(20, 48)).toBe(20)
    expect(defaultMailAddCount(1520, 0)).toBe(50)
  })

  it('builds sorted unique presets including minimum and max', () => {
    expect(mailAddCountPresets(1520, 48)).toEqual([
      25, 48, 50, 100, 250, 500, 1000,
    ])
    expect(mailAddCountPresets(40, 0)).toEqual([25, 40])
  })
})
