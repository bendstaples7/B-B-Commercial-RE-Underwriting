/**
 * Component tests for GlobalSearchBar — navigates to full search results page.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider, createTheme } from '@mui/material'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import GlobalSearchBar from './GlobalSearchBar'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

vi.mock('@/services/api', () => ({
  searchService: {
    search: vi.fn(),
  },
}))

import { searchService } from '@/services/api'

const theme = createTheme()

function TestWrapper({ children, initialEntries = ['/kanban'] }: { children: React.ReactNode; initialEntries?: string[] }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <ThemeProvider theme={theme}>{children}</ThemeProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function mockDesktop() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

function getSearchInput(container: HTMLElement): HTMLInputElement {
  const el = container.querySelector('input') as HTMLInputElement
  if (!el) throw new Error('search input not found')
  return el
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  setter?.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockDesktop()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('GlobalSearchBar', () => {
  it('renders the search input on desktop', () => {
    render(<GlobalSearchBar />, { wrapper: TestWrapper })
    expect(screen.getByTestId('search-input')).toBeInTheDocument()
  })

  it('navigates to /search on Enter with a valid query', () => {
    const { container } = render(<GlobalSearchBar />, { wrapper: TestWrapper })
    const input = getSearchInput(container)
    setInputValue(input, 'jutkins')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(mockNavigate).toHaveBeenCalledWith('/search?q=jutkins&page=1')
  })

  it('does not navigate for queries shorter than 2 characters', () => {
    const { container } = render(<GlobalSearchBar />, { wrapper: TestWrapper })
    const input = getSearchInput(container)
    setInputValue(input, 'a')
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('navigates when the search submit button is clicked', () => {
    const { container } = render(<GlobalSearchBar />, { wrapper: TestWrapper })
    const input = getSearchInput(container)
    setInputValue(input, 'ronald')
    fireEvent.click(screen.getByTestId('search-submit-button'))
    expect(mockNavigate).toHaveBeenCalledWith('/search?q=ronald&page=1')
  })

  it('syncs query from URL when on the search page', async () => {
    const { container } = render(<GlobalSearchBar />, {
      wrapper: ({ children }) => (
        <TestWrapper initialEntries={['/search?q=Ronald%20Jutkins&page=1']}>{children}</TestWrapper>
      ),
    })
    await waitFor(() => {
      expect(getSearchInput(container)).toHaveValue('Ronald Jutkins')
    })
  })

  it('shows matching results under the search bar while typing', async () => {
    vi.mocked(searchService.search).mockResolvedValue({
      q: 'jutkins',
      page: 1,
      per_page: 10,
      leads_total: 1,
      sessions_total: 0,
      leads: [
        {
          id: 11129,
          type: 'lead',
          label: 'Ronald Jutkins · 1915 W Schiller',
          nav_path: '/leads/11129',
          match_context: { type: 'name', value: 'Ronald Jutkins' },
        },
      ],
      sessions: [],
    })
    const { container } = render(<GlobalSearchBar />, { wrapper: TestWrapper })
    const input = getSearchInput(container)
    fireEvent.focus(input)
    setInputValue(input, 'jutkins')

    await waitFor(() => {
      expect(searchService.search).toHaveBeenCalledWith(
        expect.objectContaining({ q: 'jutkins', page: 1, per_page: 10 }),
      )
    })
    expect(screen.getByTestId('search-dropdown')).toBeInTheDocument()
    expect(
      await screen.findByText('Ronald Jutkins · 1915 W Schiller'),
    ).toBeInTheDocument()
  })

  it('navigates directly to a keyboard-selected result', async () => {
    vi.mocked(searchService.search).mockResolvedValue({
      q: 'jutkins',
      page: 1,
      per_page: 10,
      leads_total: 1,
      sessions_total: 0,
      leads: [
        {
          id: 11129,
          type: 'lead',
          label: 'Ronald Jutkins',
          nav_path: '/leads/11129',
        },
      ],
      sessions: [],
    })
    const { container } = render(<GlobalSearchBar />, { wrapper: TestWrapper })
    const input = getSearchInput(container)
    fireEvent.focus(input)
    setInputValue(input, 'jutkins')
    await screen.findByText('Ronald Jutkins')

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(mockNavigate).toHaveBeenCalledWith('/leads/11129')
  })
})
