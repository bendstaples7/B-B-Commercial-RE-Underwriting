/**
 * Shared follow-up due-date presets used by Log Call and task-complete flows.
 */
import { addDaysIso, addMonthsIso } from '@/utils/fromQueue'

export type FollowUpDayPreset = '1' | '3' | '7' | '14'
export type FollowUpMonthPreset = '1mo' | '3mo' | '6mo' | '1y'
export type FollowUpPreset = FollowUpDayPreset | FollowUpMonthPreset | 'custom'

export const FOLLOW_UP_PRESET_LABELS: Record<Exclude<FollowUpPreset, 'custom'>, string> = {
  '1': 'Tomorrow',
  '3': 'In 3 days',
  '7': 'In 1 week',
  '14': 'In 2 weeks',
  '1mo': 'In 1 month',
  '3mo': 'In 3 months',
  '6mo': 'In 6 months',
  '1y': 'In 1 year',
}

export function followUpDueForPreset(preset: Exclude<FollowUpPreset, 'custom'>): string {
  switch (preset) {
    case '1mo':
      return addMonthsIso(1)
    case '3mo':
      return addMonthsIso(3)
    case '6mo':
      return addMonthsIso(6)
    case '1y':
      return addMonthsIso(12)
    default:
      return addDaysIso(Number(preset))
  }
}

export function formatFollowUpPresetLabel(
  preset: Exclude<FollowUpPreset, 'custom'>,
  dueDate: string,
): string {
  const label = FOLLOW_UP_PRESET_LABELS[preset]
  const parsed = new Date(`${dueDate}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return label
  if (preset === '1' || preset === '3' || preset === '7' || preset === '14') {
    const day = parsed.toLocaleDateString(undefined, { weekday: 'long' })
    return `${label} (${day})`
  }
  const when = parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  return `${label} (${when})`
}

export function resolveFollowUpDueDate(
  preset: FollowUpPreset,
  customDueDate: string,
): string | null {
  if (preset === 'custom') return customDueDate || null
  return followUpDueForPreset(preset)
}
