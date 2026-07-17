import { describe, expect, it } from 'vitest'
import {
  followUpDueForPreset,
  formatFollowUpPresetLabel,
  resolveFollowUpDueDate,
} from './followUpPresets'

describe('followUpPresets', () => {
  it('resolves day and month presets to ISO dates', () => {
    expect(followUpDueForPreset('1')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(followUpDueForPreset('1mo')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('resolveFollowUpDueDate uses custom date when selected', () => {
    expect(resolveFollowUpDueDate('custom', '2026-08-01')).toBe('2026-08-01')
    expect(resolveFollowUpDueDate('custom', '')).toBeNull()
    expect(resolveFollowUpDueDate('3', '')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('formats preset labels with weekday or month', () => {
    const text = formatFollowUpPresetLabel('3', '2026-07-19')
    expect(text).toMatch(/^In 3 days \(/)
  })
})
