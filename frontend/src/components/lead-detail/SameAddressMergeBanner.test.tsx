import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { SameAddressMergeBanner } from '@/components/lead-detail/SameAddressMergeBanner'
import { commandCenterService } from '@/services/api'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

vi.mock('@/services/api', () => ({
  commandCenterService: {
    mergeInto: vi.fn(),
    getMergePreview: vi.fn(),
  },
}))

describe('SameAddressMergeBanner', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(commandCenterService.mergeInto).mockResolvedValue({
      winner_id: 200,
      loser_id: 100,
      merged: true,
    })
  })

  it('settles banner landmark and merge is not a silent no-op', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <SameAddressMergeBanner
          leadId={100}
          currentOwnerLabel="Yoko Miller"
          currentPeopleNames={['Yoko Miller']}
          twins={[
            {
              id: 200,
              property_street: '1110 Yoko Ave',
              owner_display_name: 'Yoko + Edwin',
              people_names: ['Yoko Miller', 'Edwin Chen'],
            },
          ]}
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
    expect(mockNavigate).toHaveBeenCalledWith('/leads/200')
  })

  it('lets you pick which twin to remove when several share the address', async () => {
    const user = userEvent.setup()
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
        />
      </MemoryRouter>,
    )
    await user.click(screen.getByTestId('same-address-merge-open'))
    await user.click(screen.getByTestId('same-address-merge-remove-300'))
    await user.click(screen.getByTestId('same-address-merge-confirm'))
    await waitFor(() => {
      expect(commandCenterService.mergeInto).toHaveBeenCalledWith(300, 100)
    })
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
})
