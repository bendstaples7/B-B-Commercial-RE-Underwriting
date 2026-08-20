import { describe, expect, it, vi } from 'vitest'
import {
  afterCommandCenterMutation,
  commandCenterQueryKey,
} from '@/utils/afterCommandCenterMutation'

describe('afterCommandCenterMutation', () => {
  it('invalidates winner and loser commandCenter keys then navigates', async () => {
    const invalidateQueries = vi.fn().mockResolvedValue(undefined)
    const navigate = vi.fn()
    const queryClient = { invalidateQueries } as never

    await afterCommandCenterMutation(queryClient, {
      winnerId: 11130,
      loserId: 2036,
      navigate,
    })

    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: commandCenterQueryKey(11130),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: commandCenterQueryKey(2036),
    })
    expect(navigate).toHaveBeenCalledWith('/leads/11130')
  })

  it('still navigates when invalidating a commandCenter key rejects', async () => {
    const invalidateQueries = vi
      .fn()
      .mockRejectedValueOnce(new Error('winner cache unavailable'))
      .mockResolvedValueOnce(undefined)
    const navigate = vi.fn()
    const queryClient = { invalidateQueries } as never

    await afterCommandCenterMutation(queryClient, {
      winnerId: 11130,
      loserId: 2036,
      navigate,
    })

    expect(invalidateQueries).toHaveBeenCalledTimes(2)
    expect(navigate).toHaveBeenCalledWith('/leads/11130')
  })

  it('preserves queue URL, queue state, and destination flash when navigating', async () => {
    const invalidateQueries = vi.fn().mockResolvedValue(undefined)
    const navigate = vi.fn()
    const queryClient = { invalidateQueries } as never
    const fromQueue = {
      key: 'todays-action',
      label: "Today's Action",
      outreach: 'call_now',
      visitedHistory: [10, 20],
      forwardStack: [40],
    }
    const flashSnackbar = { message: 'Records combined.' }

    await afterCommandCenterMutation(queryClient, {
      winnerId: 11130,
      loserId: 2036,
      navigate,
      fromQueue,
      flashSnackbar,
    })

    expect(navigate).toHaveBeenCalledWith('/leads/11130?queue=todays-action', {
      state: {
        fromQueue,
        flashSnackbar,
      },
    })
  })

  it('still invalidates winner when already on that lead (no loser)', async () => {
    const invalidateQueries = vi.fn().mockResolvedValue(undefined)
    const navigate = vi.fn()
    const queryClient = { invalidateQueries } as never

    await afterCommandCenterMutation(queryClient, {
      winnerId: 100,
      navigate,
    })

    expect(invalidateQueries).toHaveBeenCalledTimes(1)
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: commandCenterQueryKey(100),
    })
    expect(navigate).toHaveBeenCalledWith('/leads/100')
  })
})
