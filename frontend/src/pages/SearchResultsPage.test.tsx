/**
 * Tests for SearchResultsPage
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme } from '@mui/material'
import SearchResultsPage from './SearchResultsPage'

vi.mock('@/services/api', () => ({
  searchService: {
    search: vi.fn(),
  },
}))

import { searchService } from '@/services/api'

const theme = createTheme()

function renderPage(initialEntry = '/search?q=jutkins&page=1') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ThemeProvider theme={theme}>
          <Routes>
            <Route path="/search" element={<SearchResultsPage />} />
          </Routes>
        </ThemeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('SearchResultsPage', () => {
  it('shows lead results with total count', async () => {
    vi.mocked(searchService.search).mockResolvedValue({
      q: 'jutkins',
      page: 1,
      per_page: 25,
      leads_total: 2,
      sessions_total: 0,
      leads: [
        {
          id: 11129,
          type: 'lead',
          label: 'Ronald Jutkins · 1915 W Schiller',
          nav_path: '/leads/11129',
          lead_score: 36.9,
          lead_status: 'negotiating_remote',
        },
      ],
      sessions: [],
    })

    renderPage()
    await waitFor(() => {
      expect(screen.getByTestId('search-lead-11129')).toBeInTheDocument()
    })
    expect(screen.getByText(/2 matching properties/i)).toBeInTheDocument()
    expect(screen.getByText(/showing 1 person on this page/i)).toBeInTheDocument()
  })

  it('shows empty state when no matches', async () => {
    vi.mocked(searchService.search).mockResolvedValue({
      q: 'zzznomatch',
      page: 1,
      per_page: 25,
      leads_total: 0,
      sessions_total: 0,
      leads: [],
      sessions: [],
    })

    renderPage('/search?q=zzznomatch&page=1')
    await waitFor(() => {
      expect(screen.getByTestId('search-empty')).toBeInTheDocument()
    })
  })
})
