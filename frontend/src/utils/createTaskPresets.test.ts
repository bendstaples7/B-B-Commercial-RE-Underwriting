/**
 * Unit tests for createTaskPresets helpers.
 */
import { describe, it, expect } from 'vitest'
import {
  CREATE_TASK_PRESETS,
  getCreateTaskPreset,
  resolveCreateTaskPayload,
  type CreateTaskPresetId,
} from './createTaskPresets'

describe('createTaskPresets', () => {
  it('includes call, email, mail queue, and custom', () => {
    expect(CREATE_TASK_PRESETS.map((p) => p.id)).toEqual([
      'call_owner_today',
      'schedule_email',
      'add_to_mail_batch',
      'custom',
    ])
  })

  it('resolves schedule call to call_owner_today', () => {
    expect(resolveCreateTaskPayload('call_owner_today', '')).toEqual({
      title: 'Follow up call',
      task_type: 'call_owner_today',
    })
  })

  it('resolves schedule email to custom with Email owner title', () => {
    expect(resolveCreateTaskPayload('schedule_email', '')).toEqual({
      title: 'Email owner',
      task_type: 'custom',
    })
  })

  it('uses custom title when provided on typed presets', () => {
    expect(resolveCreateTaskPayload('call_owner_today', 'Call John')).toEqual({
      title: 'Call John',
      task_type: 'call_owner_today',
    })
  })

  it('falls back custom empty title to Custom task', () => {
    expect(resolveCreateTaskPayload('custom', '  ')).toEqual({
      title: 'Custom task',
      task_type: 'custom',
    })
  })

  it('getCreateTaskPreset falls back to custom for unknown ids', () => {
    expect(getCreateTaskPreset('bogus' as CreateTaskPresetId).requireTitle).toBe(true)
  })
})
