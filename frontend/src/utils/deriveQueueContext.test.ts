import { describe, it, expect } from 'vitest'
import { deriveQueueContext } from '@/utils/deriveQueueContext'

describe('deriveQueueContext', () => {
  it('maps server work_queues into banner contexts for banner keys only', () => {
    const queues = deriveQueueContext({
      work_queues: [
        { key: 'previously-warm', label: 'Previously Warm', path: '/queues/previously-warm' },
        { key: 'follow-up-overdue', label: 'Follow-Up Overdue', path: '/queues/follow-up-overdue' },
        { key: 'do-not-contact', label: 'Do Not Contact', path: '/queues/do-not-contact' },
      ],
    })

    expect(queues).toHaveLength(2)
    expect(queues.map((q) => q.label)).toEqual([
      'Follow-Up Overdue',
      'Do Not Contact',
    ])
    expect(queues[0].path).toBe('/queues/follow-up-overdue')
    expect(queues[0].color).toBe('error')
  })

  it('uses review_reason for needs-review banners', () => {
    const queues = deriveQueueContext({
      work_queues: [
        { key: 'needs-review', label: 'Needs Review', path: '/queues/needs-review' },
      ],
      review_reason: 'Manual flag',
    })
    expect(queues).toHaveLength(1)
    expect(queues[0].reason).toBe('Manual flag')
  })

  it('returns empty when work_queues missing', () => {
    expect(deriveQueueContext({})).toEqual([])
  })
})
