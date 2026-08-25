import { describe, expect, it, vi, afterEach } from 'vitest'
import {
  clearAllQueueSessionHistory,
  mergeQueueSessionHistory,
  readQueueSessionHistory,
  writeQueueSessionHistory,
} from './fromQueue'

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
})

describe('queue session history', () => {
  it('scopes persisted history by outreach filter', () => {
    writeQueueSessionHistory('todays-action', {
      visitedHistory: [1],
      forwardStack: [3],
    }, 'call_now')

    expect(readQueueSessionHistory('todays-action')).toBeNull()
    expect(readQueueSessionHistory('todays-action', 'direct_mail')).toBeNull()
    expect(readQueueSessionHistory('todays-action', 'call_now')).toEqual({
      visitedHistory: [1],
      forwardStack: [3],
    })
  })

  it('does not restore browser-back history that points at the current lead', () => {
    writeQueueSessionHistory('todays-action', {
      visitedHistory: [99],
      forwardStack: [],
    })

    expect(mergeQueueSessionHistory({
      key: 'todays-action',
      label: "Today's Action",
    }, 99)).toEqual({
      key: 'todays-action',
      label: "Today's Action",
    })
  })

  it('continues when session storage rejects writes', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('quota exceeded', 'QuotaExceededError')
    })

    expect(() => {
      writeQueueSessionHistory('todays-action', {
        visitedHistory: [1],
        forwardStack: [],
      })
    }).not.toThrow()
  })

  it('clears all queue-session entries on logout cleanup', () => {
    writeQueueSessionHistory('todays-action', {
      visitedHistory: [1],
      forwardStack: [],
    })
    writeQueueSessionHistory('todays-action', {
      visitedHistory: [2],
      forwardStack: [],
    }, 'direct_mail')
    sessionStorage.setItem('unrelated', 'keep')

    clearAllQueueSessionHistory()

    expect(readQueueSessionHistory('todays-action')).toBeNull()
    expect(readQueueSessionHistory('todays-action', 'direct_mail')).toBeNull()
    expect(sessionStorage.getItem('unrelated')).toBe('keep')
  })
})
