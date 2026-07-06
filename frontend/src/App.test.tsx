/**
 * App.test.tsx — frontend sidebar interaction tests
 *
 * Validates Requirement 10.1: the Properties section header has two separate
 * click targets:
 *  - The label ListItemButton → is a Link to '/properties' (does NOT toggle section)
 *  - The chevron IconButton   → toggles expand/collapse (does NOT navigate)
 *
 * Tests use React Testing Library + userEvent and mock heavy dependencies
 * (auth, API services, Google Maps, routing) so the component renders quickly
 * in jsdom without network requests.
 *
 * Navigation via the Properties label is tested by verifying the anchor element's
 * href attribute (React Router Link renders an <a> tag). The `useNavigate` mock
 * is used to confirm the chevron does NOT trigger programmatic navigation.
 *
 * **Validates: Requirements 10.1**
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

// ---------------------------------------------------------------------------
// Capture the navigate mock so tests can assert against it
// ---------------------------------------------------------------------------
const mockNavigate = vi.fn()

// Mock react-router-dom — keep everything real except useNavigate, which we
// capture. MemoryRouter supplies the actual routing context so Link renders
// correctly and href attributes are populated.
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    // Link must still work so ListItemButton component={Link} renders properly
    Link: actual.Link,
  }
})

// ---------------------------------------------------------------------------
// Mock heavy/external dependencies (same pattern as App.smoke.test.tsx)
// ---------------------------------------------------------------------------

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
// Tests — Requirement 10.1
// ---------------------------------------------------------------------------

describe('App sidebar — Properties section navigation vs. toggle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('the Properties label is a link to /properties and does NOT toggle the section on click', async () => {
    const user = userEvent.setup()
    renderApp()

    // Wait for the nav to render
    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
    }, { timeout: 3000 })

    // The label ListItemButton renders as an <a> tag (component={Link} to="/properties")
    // with aria-label="Navigate to Properties"
    const propertiesLabel = screen.getByRole('link', { name: 'Navigate to Properties' })
    expect(propertiesLabel).toBeInTheDocument()

    // Verify the href points to /properties — this confirms it's a navigation link,
    // not a button that calls toggleSection. React Router Link renders with href.
    expect(propertiesLabel).toHaveAttribute('href', '/properties')

    const propertiesSection = propertiesLabel.closest('div')?.parentElement
    expect(propertiesSection).toBeTruthy()

    // Record the Properties chevron state BEFORE clicking the label
    const chevronBefore = within(propertiesSection!).getByRole('button', {
      name: /collapse section|expand section/i,
    })
    const initialAriaLabel = chevronBefore.getAttribute('aria-label')

    // Click the Properties label (Link navigates via router history, not mockNavigate)
    await user.click(propertiesLabel)

    // The chevron aria-label should NOT have changed — clicking the label does not
    // call toggleSection (the section expand/collapse state is unaffected)
    const chevronAfter = within(propertiesSection!).getByRole('button', {
      name: /collapse section|expand section/i,
    })
    expect(chevronAfter.getAttribute('aria-label')).toBe(initialAriaLabel)

    // mockNavigate should NOT have been called — navigation is handled by Link
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('clicking the Properties chevron toggles the section and does NOT call navigate', async () => {
    const user = userEvent.setup()
    renderApp()

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
    }, { timeout: 3000 })

    const propertiesLabel = screen.getByRole('link', { name: 'Navigate to Properties' })
    const propertiesSection = propertiesLabel.closest('div')?.parentElement
    expect(propertiesSection).toBeTruthy()

    // The Properties section starts expanded, so chevron initially says "Collapse section"
    const chevron = within(propertiesSection!).getByRole('button', { name: 'Collapse section' })
    expect(chevron).toBeInTheDocument()

    // Click the chevron
    await user.click(chevron)

    // navigate should NOT have been called
    expect(mockNavigate).not.toHaveBeenCalled()

    // After clicking, the chevron label should flip to "Expand section"
    await waitFor(() => {
      expect(within(propertiesSection!).getByRole('button', { name: 'Expand section' })).toBeInTheDocument()
    })

    // Click the chevron again — section expands back
    const chevronAgain = within(propertiesSection!).getByRole('button', { name: 'Expand section' })
    await user.click(chevronAgain)

    expect(mockNavigate).not.toHaveBeenCalled()

    await waitFor(() => {
      expect(within(propertiesSection!).getByRole('button', { name: 'Collapse section' })).toBeInTheDocument()
    })
  })
})

// ---------------------------------------------------------------------------
// Tests — Requirement 10.3
// ---------------------------------------------------------------------------

describe('App sidebar — Analysis section toggles only (does not navigate)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // Validates: Requirement 10.3
  it('the Analysis section header is a single ListItemButton that toggles expand/collapse and does NOT call navigate', async () => {
    const user = userEvent.setup()
    renderApp()

    // Wait for the nav to render
    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
    }, { timeout: 3000 })

    // The Analysis section header is a single ListItemButton (not split into label + chevron).
    // Its accessible name comes from the "Analysis" text content — no separate aria-label.
    // It renders as a div[role="button"] containing the text.
    const analysisHeader = screen.getByRole('button', { name: /^analysis$/i })
    expect(analysisHeader).toBeInTheDocument()

    // Confirm it is NOT a link — the Analysis header should NOT have an href attribute
    // (unlike the Properties label which renders as an <a> tag via component={Link})
    expect(analysisHeader).not.toHaveAttribute('href')

    // Analysis starts expanded (default: true). Record initial child item visibility.
    // One of the Analysis child items is "Multifamily Deals" — it should be visible now.
    expect(screen.getByRole('link', { name: 'Navigate to Multifamily Deals' })).toBeInTheDocument()

    // Click the Analysis header — this should toggle (collapse) the section
    await user.click(analysisHeader)

    // mockNavigate must NOT have been called — the Analysis header only toggles, never navigates
    expect(mockNavigate).not.toHaveBeenCalled()

    // After collapsing, the child items should disappear from the DOM
    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Navigate to Multifamily Deals' })).not.toBeInTheDocument()
    })

    // Click again — section expands back
    await user.click(analysisHeader)
    expect(mockNavigate).not.toHaveBeenCalled()

    // Child items reappear
    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'Navigate to Multifamily Deals' })).toBeInTheDocument()
    })
  })
})
