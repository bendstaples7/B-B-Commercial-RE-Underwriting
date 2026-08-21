import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { SameAddressMergeBanner } from '@/components/lead-detail/SameAddressMergeBanner'
import { commandCenterService } from '@/services/api'
import type { SameAddressLeadSummary } from '@/types'
import { AppSnackbar } from '@/components/AppSnackbar'
import {
  afterCommandCenterMutation,
  commandCenterQueryKey,
} from '@/utils/afterCommandCenterMutation'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    mergeInto: vi.fn(),
    getMergePreview: vi.fn(),
  },
}))

const twin200: SameAddressLeadSummary = {
  id: 200,
  property_street: '1110 Yoko Ave',
  owner_display_name: 'Yoko + Edwin',
  people_names: ['Yoko Miller', 'Edwin Chen'],
}

describe('SameAddressMergeBanner', () => {
  beforeEach(() => {
    vi.mocked(commandCenterService.getMergePreview).mockReset()
    vi.mocked(commandCenterService.mergeInto).mockReset()
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 200,
      loser_id: 100,
      merged: true,
    })
  })

  it('settles banner landmark and merge is not a silent no-op', async () => {
    const user = userEvent.setup()
    const onMerged = vi.fn().mockResolvedValue(undefined)
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Yoko Miller"
          currentPeopleNames={['Yoko Miller']}
          twins={[twin200]}
          onMerged={onMerged}
        />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('same-address-merge-banner')).toHaveTextContent(
      'Another record for this address',
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    expect(screen.getByTestId('same-address-merge-dialog')).toBeInTheDocument()
    await user.click(screen.getByTestId('same-address-merge-stay-200'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(commandCenterService.mergeInto).toHaveBeenCalledWith(100, 200)
    })
    expect(onMerged).toHaveBeenCalledWith({ winnerId: 200, loserId: 100 })
  })

  it('when winner differs from current lead, onMerged still runs (navigate owned by helper)', async () => {
    const user = userEvent.setup()
    const navigate = vi.fn()
    const invalidateQueries = vi.fn().mockResolvedValue(undefined)
    const queryClient = { invalidateQueries } as never
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 200,
      loser_id: 100,
      merged: true,
    })
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Current"
          currentPeopleNames={['Current']}
          twins={[twin200]}
          onMerged={async ({ winnerId, loserId }) => {
            await afterCommandCenterMutation(queryClient, {
              winnerId,
              loserId,
              navigate,
            })
          }}
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.click(screen.getByTestId('same-address-merge-stay-200'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith('/leads/200')
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: commandCenterQueryKey(200),
    })
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: commandCenterQueryKey(100),
    })
  })

  it('lets parent-owned success feedback survive an onMerged refresh failure', async () => {
    const user = userEvent.setup()
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 100,
      loser_id: 200,
      merged: true,
    })

    function Harness() {
      const [snack, setSnack] = useState<string | null>(null)
      return (
        <>
          <SameAddressMergeBanner
            leadId={100}
            currentOwnerLabel="Current"
            currentPeopleNames={['Current']}
            twins={[
              {
                id: 200,
                property_street: '1 Main',
                owner_display_name: 'Twin',
                people_names: ['Twin'],
              },
            ]}
            onMerged={async () => {
              setSnack('Records combined.')
              throw new Error('invalidate failed')
            }}
          />
          <AppSnackbar
            open={Boolean(snack)}
            onClose={() => setSnack(null)}
            message={snack ?? ''}
          />
        </>
      )
    }

    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(screen.getByText('Records combined.')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('same-address-merge-error')).not.toBeInTheDocument()
  })

  it('calls onMerged when stay is the current lead (same-URL stay)', async () => {
    const user = userEvent.setup()
    const onMerged = vi.fn().mockResolvedValue(undefined)
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 100,
      loser_id: 200,
      merged: true,
    })
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Current"
          currentPeopleNames={['Current']}
          twins={[
            {
              id: 200,
              property_street: '1 Main',
              owner_display_name: 'Twin',
              people_names: ['Twin'],
            },
          ]}
          onMerged={onMerged}
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(onMerged).toHaveBeenCalledWith({ winnerId: 100, loserId: 200 })
    })
  })

  it('outcome: banner clears after Combine when stay=current and twins refetch empty', async () => {
    const user = userEvent.setup()
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 100,
      loser_id: 200,
      merged: true,
    })

    function Harness() {
      const [twins, setTwins] = useState<SameAddressLeadSummary[]>([
        {
          id: 200,
          property_street: '1 Main',
          owner_display_name: 'Twin',
          people_names: ['Twin'],
        },
      ])
      const [snack, setSnack] = useState<string | null>(null)
      return (
        <>
          <SameAddressMergeBanner
            leadId={100}
            currentOwnerLabel="Current"
            currentPeopleNames={['Current']}
            twins={twins}
            onMerged={async () => {
              setSnack('Records combined.')
              setTwins([])
            }}
          />
          <AppSnackbar
            open={Boolean(snack)}
            onClose={() => setSnack(null)}
            message={snack ?? ''}
          />
        </>
      )
    }

    render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('same-address-merge-banner')).toBeInTheDocument()
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(screen.queryByTestId('same-address-merge-banner')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Records combined.')).toBeInTheDocument()
  })

  it('lets you pick which twin to remove when several share the address', async () => {
    const user = userEvent.setup()
    const onMerged = vi.fn().mockResolvedValue(undefined)
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 100,
      loser_id: 300,
      merged: true,
    })
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Current"
          currentPeopleNames={['Current']}
          twins={[
            {
              id: 200,
              property_street: '1 Main',
              owner_display_name: 'Twin A',
              people_names: ['A'],
            },
            {
              id: 300,
              property_street: '1 Main',
              owner_display_name: 'Twin B',
              people_names: ['B'],
            },
          ]}
          onMerged={onMerged}
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.click(screen.getByTestId('same-address-merge-remove-300'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(commandCenterService.mergeInto).toHaveBeenCalledWith(300, 100)
    })
    expect(onMerged).toHaveBeenCalledWith({ winnerId: 100, loserId: 300 })
  })

  it('uses the selected remove row when a different twin stays', async () => {
    const user = userEvent.setup()
    const onMerged = vi.fn().mockResolvedValue(undefined)
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 200,
      loser_id: 300,
      merged: true,
    })
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Current"
          currentPeopleNames={['Current']}
          twins={[
            {
              id: 200,
              property_street: '1 Main',
              owner_display_name: 'Twin A',
              people_names: ['A'],
            },
            {
              id: 300,
              property_street: '1 Main',
              owner_display_name: 'Twin B',
              people_names: ['B'],
            },
          ]}
          onMerged={onMerged}
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.click(screen.getByTestId('same-address-merge-stay-200'))
    await user.click(screen.getByTestId('same-address-merge-remove-300'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(commandCenterService.mergeInto).toHaveBeenCalledWith(300, 200)
    })
    expect(onMerged).toHaveBeenCalledWith({ winnerId: 200, loserId: 300 })
  })

  it('rejects paste of a different building via merge preview', async () => {
    const user = userEvent.setup()
    vi.mocked(commandCenterService.getMergePreview).mockResolvedValue({
      same_building: false,
      current: {
        id: 100,
        property_street: '1110 Yoko Ave',
        owner_display_name: 'Yoko',
        people_names: ['Yoko'],
      },
      other: {
        id: 999,
        property_street: '2200 Other St',
        owner_display_name: 'Other',
        people_names: [],
      },
    })
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Yoko"
          currentPeopleNames={['Yoko']}
          twins={[
            {
              id: 200,
              property_street: '1110 Yoko Ave',
              owner_display_name: 'Edwin',
              people_names: ['Edwin'],
            },
          ]}
          onMerged={vi.fn()}
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.type(screen.getByTestId('same-address-merge-paste-id'), '999')
    await user.tab()
    await waitFor(() => {
      expect(commandCenterService.getMergePreview).toHaveBeenCalledWith(100, 999)
    })
    expect(await screen.findByText('That record is not the same address.')).toBeInTheDocument()
  })

  it('waits for pasted lead validation before merging', async () => {
    const user = userEvent.setup()
    const onMerged = vi.fn().mockResolvedValue(undefined)
    let resolvePreview: (value: {
      same_building: boolean
      current: {
        id: number
        property_street: string
        owner_display_name: string
        people_names: string[]
      }
      other: {
        id: number
        property_street: string
        owner_display_name: string
        people_names: string[]
      }
    }) => void = () => {}
    vi.mocked(commandCenterService.getMergePreview).mockReturnValue(
      new Promise((resolve) => {
        resolvePreview = resolve
      }),
    )
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 100,
      loser_id: 300,
      merged: true,
    })
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Yoko"
          currentPeopleNames={['Yoko']}
          twins={[
            {
              id: 200,
              property_street: '1110 Yoko Ave',
              owner_display_name: 'Edwin',
              people_names: ['Edwin'],
            },
          ]}
          onMerged={onMerged}
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.type(screen.getByTestId('same-address-merge-paste-id'), '300')
    await user.click(screen.getByTestId('same-address-merge-confirm'))

    expect(commandCenterService.getMergePreview).toHaveBeenCalledWith(100, 300)
    expect(commandCenterService.mergeInto).not.toHaveBeenCalled()

    resolvePreview({
      same_building: true,
      current: {
        id: 100,
        property_street: '1110 Yoko Ave',
        owner_display_name: 'Yoko',
        people_names: ['Yoko'],
      },
      other: {
        id: 300,
        property_street: '1110 Yoko Ave',
        owner_display_name: 'Manual twin',
        people_names: ['Manual twin'],
      },
    })
    await waitFor(() => {
      expect(commandCenterService.mergeInto).toHaveBeenCalledWith(300, 100)
    })
    expect(onMerged).toHaveBeenCalledWith({ winnerId: 100, loserId: 300 })
  })

  it('clears pasted lead state after cancel and reopen', async () => {
    const user = userEvent.setup()
    vi.mocked(commandCenterService.getMergePreview).mockResolvedValue({
      same_building: true,
      current: {
        id: 100,
        property_street: '1110 Yoko Ave',
        owner_display_name: 'Yoko',
        people_names: ['Yoko'],
      },
      other: {
        id: 300,
        property_street: '1110 Yoko Ave',
        owner_display_name: 'Manual twin',
        people_names: ['Manual twin'],
      },
    })
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Yoko"
          currentPeopleNames={['Yoko']}
          twins={[
            {
              id: 200,
              property_street: '1110 Yoko Ave',
              owner_display_name: 'Edwin',
              people_names: ['Edwin'],
            },
          ]}
          onMerged={vi.fn()}
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.type(screen.getByTestId('same-address-merge-paste-id'), '300')
    await user.tab()
    await waitFor(() => {
      expect(screen.getAllByText('Manual twin (#300)').length).toBeGreaterThan(0)
    })

    await user.click(screen.getByText('Cancel'))
    await user.click(screen.getByTestId('same-address-merge-open'))

    expect(screen.getByTestId('same-address-merge-paste-id')).toHaveValue('')
    expect(screen.queryAllByText('Manual twin (#300)')).toHaveLength(0)
  })
})
