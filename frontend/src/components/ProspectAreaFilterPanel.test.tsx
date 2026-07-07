/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProspectAreaFilterPanel } from '@/components/ProspectAreaFilterPanel'
import { prospectService } from '@/services/api'

vi.mock('@react-google-maps/api', () => ({
  GoogleMap: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-google-map">{children}</div>
  ),
  Polygon: () => <div data-testid="mock-polygon" />,
}))

vi.mock('@/services/api', () => ({
  prospectService: {
    saveAreaFilter: vi.fn(),
  },
}))

const mockSave = vi.mocked(prospectService.saveAreaFilter)

function renderPanel(mapsLoaded = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ProspectAreaFilterPanel
        mapsLoaded={mapsLoaded}
        config={{ enabled: false, label: null, geometry: null, updated_at: null }}
      />
    </QueryClientProvider>,
  )
}

describe('ProspectAreaFilterPanel', () => {
  beforeEach(() => {
    mockSave.mockReset()
    mockSave.mockResolvedValue({
      enabled: true,
      label: null,
      geometry: {
        type: 'Polygon',
        coordinates: [[[-87.7, 41.7], [-87.6, 41.7], [-87.6, 41.8], [-87.7, 41.7]]],
      },
      updated_at: '2026-07-06T00:00:00Z',
    })
  })

  it('expands panel content when Target area is clicked', async () => {
    const user = userEvent.setup()
    renderPanel(true)

    expect(screen.queryByTestId('prospect-area-filter-panel')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Target area/i }))

    expect(screen.getByTestId('prospect-area-filter-panel')).toBeVisible()
    expect(screen.getByText('Draw a rectangle or polygon to filter Prospect Review')).toBeVisible()
    expect(screen.getByTestId('mock-google-map')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save area' })).toBeVisible()
    expect(screen.getByTestId('prospect-area-draw-rectangle')).toBeVisible()
  })

  it('shows loading state when maps are not ready', async () => {
    const user = userEvent.setup()
    renderPanel(false)

    await user.click(screen.getByRole('button', { name: /Target area/i }))

    expect(screen.getByText('Loading map…')).toBeVisible()
    expect(screen.queryByTestId('mock-google-map')).not.toBeInTheDocument()
  })

  it('saves drawn geometry and enables the filter', async () => {
    const user = userEvent.setup()
    const geometry = {
      type: 'Polygon' as const,
      coordinates: [[[-87.7, 41.7], [-87.6, 41.7], [-87.6, 41.8], [-87.7, 41.7]]],
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <ProspectAreaFilterPanel
          mapsLoaded
          config={{ enabled: false, label: null, geometry, updated_at: null }}
        />
      </QueryClientProvider>,
    )

    await user.click(screen.getByTestId('prospect-area-save'))

    await waitFor(() => {
      expect(mockSave).toHaveBeenCalledWith({
        enabled: true,
        geometry,
        label: null,
      })
    })

    expect(await screen.findByTestId('prospect-area-save-success')).toBeVisible()
  })
})
