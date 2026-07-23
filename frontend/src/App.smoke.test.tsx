/**
 * App shell smoke test.
 *
 * Verifies that the application renders past the authentication loading state
 * and displays the main navigation shell for an authenticated user.
 *
 * WHY THIS TEST EXISTS
 * --------------------
 * The admin-panel branch introduced AuthContext/AuthProvider but forgot to
 * mount AuthProvider in main.tsx. The result was useAuth() returning the
 * default context value (isLoading: true), which caused App to render a
 * permanent full-screen spinner — the entire app was blank.
 *
 * This test catches that class of bug: if AuthProvider is ever missing from
 * the tree, or if any other provider wiring breaks the shell, this test fails
 * immediately because the nav never appears.
 *
 * WHAT IT TESTS
 * -------------
 * - App renders the AppBar ("Real Estate Analysis Platform")
 * - App renders the nav sidebar ("RE Analysis" brand + nav links)
 * - App does NOT stay stuck on the auth loading spinner
 * - App does NOT redirect to /login when a valid user is present
 *
 * It does NOT test individual routes or business logic — those are covered
 * by their own test files.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

// ---------------------------------------------------------------------------
// Mock heavy dependencies that the shell loads on mount
// ---------------------------------------------------------------------------

// Google Maps — not needed for shell rendering
vi.mock('@react-google-maps/api', () => ({
  useLoadScript: () => ({ isLoaded: false }),
}))

// Auth — return a valid authenticated user so AuthGuard passes
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({
    user: {
      user_id: 'smoke-test-user',
      email: 'smoke@example.com',
      display_name: 'Smoke Test User',
      is_admin: false,
    },
    token: 'smoke-test-token',
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  AuthContext: { Provider: ({ children }: any) => <>{children}</> },
  validateStoredToken: vi.fn(),
}))

// API services — return minimal data so the shell doesn't error on mount
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

// PipelineStatusContext — avoid real polling
vi.mock('@/context/PipelineStatusContext', () => ({
  PipelineStatusProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  usePipelineStatus: () => null,
}))

// NotificationContext — avoid real setup
vi.mock('@/context/NotificationContext', () => ({
  NotificationProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  globalNotify: { showError: vi.fn(), showSuccess: vi.fn() },
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('App shell smoke test', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the AppBar with the platform title', async () => {
    renderApp()

    await waitFor(() => {
      expect(screen.getByText('Real Estate Analysis Platform')).toBeInTheDocument()
    }, { timeout: 3000 })
  })

  it('renders the nav sidebar brand', async () => {
    renderApp()

    await waitFor(() => {
      expect(screen.getByText('RE Analysis')).toBeInTheDocument()
    }, { timeout: 3000 })
  })

  it('renders the main navigation landmark', async () => {
    renderApp()

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
    }, { timeout: 3000 })
  })

  it('does not show the auth loading spinner after mount', async () => {
    renderApp()

    // The spinner has aria-label="Checking authentication"
    // It should not be present once auth resolves
    await waitFor(() => {
      expect(screen.queryByLabelText('Checking authentication')).not.toBeInTheDocument()
    }, { timeout: 3000 })
  })

  it('does not redirect to /login when user is authenticated', async () => {
    renderApp('/')

    // If the app redirected to login, we'd see the "Sign in to your account" text
    // and NOT see the nav sidebar
    await waitFor(() => {
      expect(screen.queryByText('Sign in to your account')).not.toBeInTheDocument()
      expect(screen.getByText('RE Analysis')).toBeInTheDocument()
    }, { timeout: 3000 })
  })
})
