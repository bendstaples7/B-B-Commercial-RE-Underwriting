import { describe, expect, it } from 'vitest'
import {
  findCallCompletableTask,
  findPrimaryOpenTask,
  findCompletableTaskForMode,
  findEmailCompletableTask,
  isCallCompletableTask,
  isEmailCompletableTask,
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

describe('isEmailCompletableTask', () => {
  it('allows mail batch and email outreach', () => {
    expect(isEmailCompletableTask('add_to_mail_batch', 'Add to mail')).toBe(true)
    expect(isEmailCompletableTask('custom', 'Email outreach')).toBe(true)
  })

  it('rejects skip-trace and research', () => {
    expect(isEmailCompletableTask('skip_trace_owner', 'Skip trace')).toBe(false)
    expect(isEmailCompletableTask('research_missing_pin', 'Research PIN')).toBe(false)
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

describe('findPrimaryOpenTask', () => {
  it('returns the soonest open task regardless of call-completable matching', () => {
    const tasks = [
      makeTask({ id: 1, title: 'Email outreach', task_type: 'custom', due_date: '2026-08-10' }),
      makeTask({ id: 2, title: 'Research PIN', task_type: 'research_missing_pin', due_date: '2026-08-01' }),
    ]
    expect(findPrimaryOpenTask(tasks)?.id).toBe(2)
  })

  it('returns null when no open tasks', () => {
    expect(findPrimaryOpenTask([])).toBeNull()
  })
})

describe('findCompletableTaskForMode', () => {
  it('uses call matcher for call and note; email may complete mail outreach', () => {
    const tasks = [
      makeTask({ id: 1, title: 'Email outreach', task_type: 'custom' }),
      makeTask({ id: 2, title: 'Call owner', task_type: 'call_owner_today' }),
    ]
    expect(findCompletableTaskForMode('call', tasks)?.id).toBe(2)
    expect(findCompletableTaskForMode('note', tasks)?.id).toBe(2)
    expect(findCompletableTaskForMode('email', tasks)?.id).toBe(1)
  })

  it('never auto-completes skip_trace_owner or mail batch from note', () => {
    const skip = [makeTask({ id: 1, title: 'Skip trace owner', task_type: 'skip_trace_owner' })]
    const mail = [makeTask({ id: 2, title: 'Add to mail', task_type: 'add_to_mail_batch' })]
    expect(findCompletableTaskForMode('note', skip)).toBeNull()
    expect(findCompletableTaskForMode('note', mail)).toBeNull()
    expect(findCompletableTaskForMode('email', skip)).toBeNull()
    expect(findEmailCompletableTask(mail)?.id).toBe(2)
  })
})
