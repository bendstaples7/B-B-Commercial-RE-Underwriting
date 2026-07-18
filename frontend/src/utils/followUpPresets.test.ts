import { describe, expect, it } from 'vitest'
import {
  followUpDueForPreset,
  formatFollowUpDueLong,
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

  it('formats preset labels with weekday and long month', () => {
    const text = formatFollowUpPresetLabel('3', '2026-07-22')
    expect(text).toMatch(/^In 3 days \(/)
    expect(text).toMatch(/Wednesday/)
    expect(text).toMatch(/July/)
    expect(text).toMatch(/22/)
  })

  it('formatFollowUpDueLong includes weekday and month', () => {
    const text = formatFollowUpDueLong('2026-07-22')
    expect(text).toMatch(/Wednesday/)
    expect(text).toMatch(/July/)
  })
})
