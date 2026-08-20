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
