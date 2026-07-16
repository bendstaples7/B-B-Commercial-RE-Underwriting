import { describe, expect, it } from 'vitest'
import {
  findCallCompletableTask,
  isCallCompletableTask,
  parseHubSpotTaskId,
} from './callCompletableTask'
import type { LeadTask } from '@/types'

function makeTask(overrides: Partial<LeadTask> & Pick<LeadTask, 'id' | 'title' | 'task_type'>): LeadTask {
  return {
    lead_id: 1,
    status: 'open',
    due_date: null,
    created_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    created_by: 'test',
    source: 'native',
    ...overrides,
  }
}

describe('isCallCompletableTask', () => {
  it('matches call_owner_today', () => {
    expect(isCallCompletableTask('call_owner_today', 'x')).toBe(true)
  })

  it('rejects mail/email outreach', () => {
    expect(isCallCompletableTask('add_to_mail_batch', 'Add to mail')).toBe(false)
    expect(isCallCompletableTask('custom', 'Email outreach')).toBe(false)
  })

  it('matches custom call titles', () => {
    expect(isCallCompletableTask('custom', 'Call the owner')).toBe(true)
  })

  it('matches follow-up titles', () => {
    expect(isCallCompletableTask('custom', 'Follow up on 1726 W Roscoe St')).toBe(true)
    expect(isCallCompletableTask('custom', 'Follow-up with owner')).toBe(true)
  })
})

describe('parseHubSpotTaskId', () => {
  it('parses numeric LeadTask ids', () => {
    expect(parseHubSpotTaskId(42)).toBe(42)
    expect(parseHubSpotTaskId('42')).toBe(42)
  })

  it('returns null for invalid ids', () => {
    expect(parseHubSpotTaskId('native-1')).toBeNull()
  })
})

describe('findCallCompletableTask', () => {
  it('prefers explicit call task when multiple open tasks exist', () => {
    const tasks = [
      makeTask({ id: 1, title: 'Email outreach', task_type: 'custom' }),
      makeTask({ id: 2, title: 'Call owner', task_type: 'call_owner_today' }),
      makeTask({ id: 10, title: 'Follow up on address', task_type: 'custom', source: 'hubspot' }),
    ]
    const found = findCallCompletableTask(tasks)
    expect(found?.id).toBe(2)
  })

  it('returns null when only mail task', () => {
    const tasks = [makeTask({ id: 1, title: 'Add to mail batch', task_type: 'add_to_mail_batch' })]
    expect(findCallCompletableTask(tasks)).toBeNull()
  })

  it('matches sole open custom follow-up task', () => {
    const tasks = [makeTask({ id: 3, title: 'Mobile (555) 123-4567', task_type: 'custom' })]
    expect(findCallCompletableTask(tasks)?.id).toBe(3)
  })

  it('matches sole open hubspot follow-up task', () => {
    const tasks = [
      makeTask({
        id: 99,
        title: 'Follow up on 1726 W Roscoe St',
        task_type: 'custom',
        source: 'hubspot',
        status: 'overdue',
      }),
    ]
    expect(findCallCompletableTask(tasks)?.id).toBe(99)
  })
})
