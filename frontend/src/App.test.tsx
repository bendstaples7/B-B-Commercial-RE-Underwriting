/**
 * App.test.tsx — frontend sidebar interaction tests
 *
 * Validates dual-rail navigation behavior:
 *  - Icon + label rows stay paired (Home, Work Queue, Analysis, …)
 *  - Accordion sections can expand and collapse
 *  - Analysis selects via icon only (headerNavigates false → no navigate())
 *
 * Tests use React Testing Library + userEvent and mock heavy dependencies
 * (auth, API services, Google Maps, routing) so the component renders quickly
 * in jsdom without network requests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    Link: actual.Link,
  }
})

vi.mock('@react-google-maps/api', () => ({
  useLoadScript: () => ({ isLoaded: false }),
}))

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      user_id: 'test-user-1',
      email: 'test@example.com',
      display_name: 'Test User',
      is_admin: false,
    },
    token: 'test-token',
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AuthContext: { Provider: ({ children }: any) => <>{children}</> },
  validateStoredToken: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  queueService: {
    getCounts: vi.fn().mockResolvedValue({
      todays_action: 0,
      previously_warm: 0,
      follow_up_overdue: 0,
      no_next_action: 0,
      needs_review: 0,
      skip_trace: 0,
      skip_trace_exhausted: 0,
      do_not_contact: 0,
      missing_property_match: 0,
    }),
    getTodaysAction: vi.fn().mockResolvedValue({ leads: [], total: 0, page: 1, per_page: 20 }),
  },
  hubSpotService: {
    getPipelineStatus: vi.fn().mockResolvedValue({
      pipeline_running: false,
      matches: { total: 0, high: 0, medium: 0, unmatched: 0 },
      interactions: 0,
      tasks: 0,
      signals: 0,
    }),
  },
  analysisService: {
    getSession: vi.fn(),
    startAnalysis: vi.fn(),
    advanceToStep: vi.fn(),
    updateStepData: vi.fn(),
    goBackToStep: vi.fn(),
    generateReport: vi.fn(),
    exportToExcel: vi.fn(),
  },
  multifamilyService: {
    listDeals: vi.fn().mockResolvedValue([]),
  },
  default: {
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}))

vi.mock('@/context/PipelineStatusContext', () => ({
  PipelineStatusProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePipelineStatus: () => null,
}))

vi.mock('@/context/NotificationContext', () => ({
  NotificationProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  globalNotify: { showError: vi.fn(), showSuccess: vi.fn() },
}))

const theme = createTheme()

function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <MemoryRouter initialEntries={[initialPath]}>
          <App />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

async function getMainNav() {
  await waitFor(() => {
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
  }, { timeout: 3000 })
  return screen.getByRole('navigation', { name: 'Main navigation' })
}

describe('App sidebar — dual-rail Properties section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('shows all top-level labels with only Properties leaves expanded', async () => {
    renderApp('/properties')
    const nav = await getMainNav()

    expect(within(nav).getByText('Home')).toBeInTheDocument()
    expect(within(nav).getByText('Work Queue')).toBeInTheDocument()
    expect(within(nav).getByText('Analysis')).toBeInTheDocument()
    expect(within(nav).getByText('Properties')).toBeInTheDocument()
    expect(within(nav).getByText('Marketing')).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Navigate to Properties' })).not.toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Navigate to Quick Add' })).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Navigate to Multifamily Deals' })).not.toBeInTheDocument()
  })

  it('expands another top-level section from the accordion list', async () => {
    const user = userEvent.setup()
    renderApp('/properties')
    const nav = await getMainNav()

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: 'Navigate to Quick Add' })).toBeInTheDocument()
    })

    await user.click(within(nav).getByText('Analysis'))

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: 'Navigate to Multifamily Deals' })).toBeInTheDocument()
    })
    expect(within(nav).queryByRole('link', { name: 'Navigate to Quick Add' })).not.toBeInTheDocument()
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('can collapse the active Work Queue section', async () => {
    const user = userEvent.setup()
    renderApp('/kanban')
    const nav = await getMainNav()

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: "Navigate to Today's Action" })).toBeInTheDocument()
    })

    await user.click(within(nav).getByText('Work Queue'))

    await waitFor(() => {
      expect(within(nav).queryByRole('link', { name: "Navigate to Today's Action" })).not.toBeInTheDocument()
    })
  })

  it('selects Properties from the icon rail and navigates', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const nav = await getMainNav()

    await user.click(within(nav).getByTestId('nav-section-icon-properties'))

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: 'Navigate to Quick Add' })).toBeInTheDocument()
    })
    expect(mockNavigate).toHaveBeenCalledWith('/properties')
  })
})

describe('App sidebar — dual-rail Analysis section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('selects Analysis from the icon rail without navigate()', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const nav = await getMainNav()

    expect(within(nav).queryByRole('link', { name: 'Navigate to Multifamily Deals' })).not.toBeInTheDocument()

    await user.click(within(nav).getByTestId('nav-section-icon-analysis'))

    expect(mockNavigate).not.toHaveBeenCalled()
    expect(within(nav).queryByRole('link', { name: 'Navigate to Analysis' })).not.toBeInTheDocument()
    expect(within(nav).getByText('Analysis')).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Navigate to Multifamily Deals' })).toBeInTheDocument()
  })
})

describe('App sidebar — dual-rail Home section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('shows Home label and Activity Goals leaf on the goals dashboard', async () => {
    renderApp('/dashboard')
    const nav = await getMainNav()

    expect(within(nav).getByText('Home')).toBeInTheDocument()
    expect(within(nav).queryByRole('link', { name: 'Navigate to Home' })).not.toBeInTheDocument()
    const activityGoals = within(nav).getByRole('link', { name: 'Navigate to Activity Goals' })
    expect(activityGoals).toHaveAttribute('href', '/dashboard')
  })

  it('navigates home from the Home icon when leaving another section', async () => {
    const user = userEvent.setup()
    renderApp('/properties')
    const nav = await getMainNav()

    const home = within(nav).getByTestId('home-nav-icon')
    const workQueue = within(nav).getByTestId('nav-section-icon-kanban')
    expect(
      home.compareDocumentPosition(workQueue) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    await user.click(home)
    expect(mockNavigate).toHaveBeenCalledWith('/dashboard')
  })

  it('links the AppBar title to the goals dashboard home', async () => {
    renderApp('/properties')

    await waitFor(() => {
      expect(screen.getByTestId('app-home-title')).toBeInTheDocument()
    }, { timeout: 3000 })

    const title = screen.getByTestId('app-home-title')
    expect(title).toHaveAttribute('href', '/dashboard')
    expect(title).toHaveTextContent('Real Estate Analysis Platform')
  })
})

describe('App sidebar — Work Queue / lead context', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('does not navigate to /kanban when expanding Work Queue on a queue page', async () => {
    const user = userEvent.setup()
    renderApp('/queues/todays-action')
    const nav = await getMainNav()

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: "Navigate to Today's Action" })).toBeInTheDocument()
    })

    await user.click(within(nav).getByText('Work Queue'))
    await waitFor(() => {
      expect(
        within(nav).queryByRole('link', { name: "Navigate to Today's Action" }),
      ).not.toBeInTheDocument()
    })
    mockNavigate.mockClear()

    await user.click(within(nav).getByText('Work Queue'))
    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: "Navigate to Today's Action" })).toBeInTheDocument()
    })
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('selects Work Queue (not Home) on lead detail', async () => {
    renderApp('/leads/123')
    const nav = await getMainNav()

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: "Navigate to Today's Action" })).toBeInTheDocument()
    })
    expect(within(nav).getByTestId('nav-section-icon-kanban')).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByTestId('home-nav-icon')).not.toHaveAttribute('aria-current')
  })

  it('does not navigate away from lead detail when clicking Work Queue icon', async () => {
    const user = userEvent.setup()
    renderApp('/leads/456')
    const nav = await getMainNav()

    await waitFor(() => {
      expect(within(nav).getByTestId('nav-section-icon-kanban')).toHaveAttribute('aria-current', 'page')
    })
    mockNavigate.mockClear()
    await user.click(within(nav).getByTestId('nav-section-icon-kanban'))
    expect(mockNavigate).not.toHaveBeenCalled()
  })
})

describe('App sidebar — dual-rail secondary collapse', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('minimizes the secondary panel and expands it again', async () => {
    const user = userEvent.setup()
    renderApp('/dashboard')
    const nav = await getMainNav()

    const toggle = within(nav).getByTestId('collapse-secondary-nav')
    const workQueue = within(nav).getByTestId('nav-section-icon-kanban')
    expect(
      toggle.compareDocumentPosition(workQueue) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()

    await user.click(toggle)

    expect(within(nav).getByTestId('expand-secondary-nav')).toBeInTheDocument()
    expect(localStorage.getItem('bb.nav.secondaryExpanded')).toBe('0')
    // Collapsed rail must not keep Home's submenu mounted (that created the icon gap).
    expect(within(nav).queryByRole('link', { name: 'Navigate to Activity Goals' })).not.toBeInTheDocument()
    expect(within(nav).getByText('Home')).toBeInTheDocument()

    await user.click(within(nav).getByTestId('expand-secondary-nav'))

    expect(localStorage.getItem('bb.nav.secondaryExpanded')).toBe('1')
    expect(within(nav).getByTestId('collapse-secondary-nav')).toBeInTheDocument()
    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: 'Navigate to Activity Goals' })).toBeInTheDocument()
    })
  })

  it('re-expands the secondary panel when a section icon is clicked while collapsed', async () => {
    const user = userEvent.setup()
    localStorage.setItem('bb.nav.secondaryExpanded', '0')
    renderApp('/dashboard')

    await waitFor(() => {
      expect(screen.getByTestId('expand-secondary-nav')).toBeInTheDocument()
    }, { timeout: 3000 })

    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    await user.click(within(nav).getByTestId('nav-section-icon-properties'))

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: 'Navigate to Quick Add' })).toBeInTheDocument()
    })
  })
})
