import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BackendRestartRequiredBanner } from './BackendRestartRequiredBanner'

vi.mock('@/hooks/useBackendRuntimeGuard', () => ({
  useBackendRuntimeGuard: vi.fn(),
}))

import { useBackendRuntimeGuard } from '@/hooks/useBackendRuntimeGuard'

const mockedGuard = vi.mocked(useBackendRuntimeGuard)

function renderBanner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <BackendRestartRequiredBanner />
    </QueryClientProvider>,
  )
}

describe('BackendRestartRequiredBanner', () => {
  beforeEach(() => {
    mockedGuard.mockReset()
  })

  it('renders nothing when source is fresh', () => {
    mockedGuard.mockReturnValue({ sourceStale: false, buildId: 'abc' })
    const { container } = renderBanner()
    expect(container).toBeEmptyDOMElement()
  })

  it('renders restart warning when source_stale', () => {
    mockedGuard.mockReturnValue({ sourceStale: true, buildId: 'abc' })
    renderBanner()
    expect(screen.getByTestId('backend-restart-required-banner')).toBeInTheDocument()
    expect(screen.getByText(/Backend restart required/i)).toBeInTheDocument()
    expect(screen.getByText(/python dev\.py/i)).toBeInTheDocument()
  })
})
