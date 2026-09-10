import { describe, expect, it } from 'vitest'
import { userFacingApiErrorMessage } from '@/services/httpClient'

describe('userFacingApiErrorMessage', () => {
  it('prefers message when error is Provider not configured', () => {
    expect(userFacingApiErrorMessage({
      error: 'Provider not configured',
      message: 'Illinois LLC list is not loaded yet',
    })).toBe('Illinois LLC list is not loaded yet')
  })

  it('keeps a specific error string when no message is present', () => {
    expect(userFacingApiErrorMessage({
      error: 'Not found',
    })).toBe('Not found')
  })

  it('prefers message when error is the Mail queue error wrapper', () => {
    expect(userFacingApiErrorMessage({
      error: 'Mail queue error',
      message: 'Only queued items can be removed',
    })).toBe('Only queued items can be removed')
  })
})
