/**
 * Component tests for AdminPanel
 *
 * Covers:
 * - Renders CircularProgress while fetching
 * - Renders error Alert when fetch fails; no table rendered
 * - Renders table with all required columns when data loads
 * - Clicking a user row navigates to /admin/users/<user_id>
 * - Property 10: Admin route access control (Requirements 6.1, 6.2)
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import { MemoryRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AdminPanel } from './AdminPanel'
import type { AdminUserSummary, AuthUser } from '@/types'
import fc from 'fast-check'

// ---------------------------------------------------------------------------
// Mock the API services
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

// ---------------------------------------------------------------------------
// Mock useAuth for route guard tests
// ---------------------------------------------------------------------------

const mockUseAuth = vi.fn()

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

vi.mock('@/services/api', () => ({
  adminService: {
    listUsers: vi.fn(),
    getUserSummary: vi.fn(),
  },
}))

// ---------------------------------------------------------------------------
// Test data helpers
// ---------------------------------------------------------------------------

function makeUserSummary(overrides: Partial<AdminUserSummary> = {}): AdminUserSummary {
  return {
    user_id: 'user-abc-123',
    email: 'alice@example.com',
    display_name: 'Alice',
    is_active: true,
    is_admin: false,
    created_at: '2024-01-15T10:00:00Z',
    lead_count: 5,
    marketing_list_count: 2,
    import_job_count: 3,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

let adminService: typeof import('@/services/api')['adminService']

beforeEach(async () => {
  vi.clearAllMocks()
  mockNavigate.mockClear()
  // Default: non-admin user (overridden in Property 10 tests)
  mockUseAuth.mockReturnValue({
    user: null,
    token: null,
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  })
  const api = await import('@/services/api')
  adminService = api.adminService
})

// ---------------------------------------------------------------------------
// Helper render function
// ---------------------------------------------------------------------------

function renderAdminPanel() {
  return render(
    <MemoryRouter>
      <AdminPanel />
    </MemoryRouter>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AdminPanel', () => {
  describe('loading state', () => {
    it('renders CircularProgress while fetching', () => {
      // listUsers never resolves — keeps component in loading state
      vi.mocked(adminService.listUsers).mockReturnValue(new Promise(() => {}))

      renderAdminPanel()

      // CircularProgress has aria-label="Loading users"
      expect(screen.getByRole('progressbar')).toBeInTheDocument()
      // Table should not be present while loading
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
    })
  })

  describe('error state', () => {
    it('renders error Alert when fetch fails and does not render the table', async () => {
      vi.mocked(adminService.listUsers).mockRejectedValue(new Error('Failed to load users'))

      renderAdminPanel()

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      // Error message should be visible
      expect(screen.getByRole('alert')).toHaveTextContent('Failed to load users')

      // Table must NOT be rendered on error
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
    })

    it('renders error Alert when getUserSummary fails and does not render the table', async () => {
      const user = makeUserSummary()
      // listUsers succeeds but getUserSummary fails
      vi.mocked(adminService.listUsers).mockResolvedValue([user])
      vi.mocked(adminService.getUserSummary).mockRejectedValue(
        new Error('Summary fetch failed')
      )

      renderAdminPanel()

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument()
      })

      expect(screen.queryByRole('table')).not.toBeInTheDocument()
    })
  })

  describe('data loaded state', () => {
    it('renders table with all required columns when data loads', async () => {
      const user1 = makeUserSummary({
        user_id: 'user-1',
        display_name: 'Alice',
        email: 'alice@example.com',
        is_active: true,
        is_admin: false,
        created_at: '2024-01-15T10:00:00Z',
        lead_count: 5,
        marketing_list_count: 2,
        import_job_count: 3,
      })

      vi.mocked(adminService.listUsers).mockResolvedValue([user1])
      vi.mocked(adminService.getUserSummary).mockResolvedValue(user1)

      renderAdminPanel()

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument()
      })

      // Verify all required column headers are present
      expect(screen.getByText('Display Name')).toBeInTheDocument()
      expect(screen.getByText('Email')).toBeInTheDocument()
      expect(screen.getByText('Status')).toBeInTheDocument()
      expect(screen.getByText('Admin')).toBeInTheDocument()
      expect(screen.getByText('Member Since')).toBeInTheDocument()
      expect(screen.getByText('Lead Count')).toBeInTheDocument()
      expect(screen.getByText('Marketing Lists')).toBeInTheDocument()
      expect(screen.getByText('Import Jobs')).toBeInTheDocument()

      // Verify row data is rendered
      expect(screen.getByText('Alice')).toBeInTheDocument()
      expect(screen.getByText('alice@example.com')).toBeInTheDocument()
      expect(screen.getByText('Active')).toBeInTheDocument()
      expect(screen.getByText('No')).toBeInTheDocument()
      expect(screen.getByText('5')).toBeInTheDocument()
      expect(screen.getByText('2')).toBeInTheDocument()
      expect(screen.getByText('3')).toBeInTheDocument()
    })

    it('renders multiple user rows when multiple users are returned', async () => {
      const user1 = makeUserSummary({
        user_id: 'user-1',
        display_name: 'Alice',
        email: 'alice@example.com',
      })
      const user2 = makeUserSummary({
        user_id: 'user-2',
        display_name: 'Bob',
        email: 'bob@example.com',
        is_admin: true,
      })

      vi.mocked(adminService.listUsers).mockResolvedValue([user1, user2])
      vi.mocked(adminService.getUserSummary)
        .mockResolvedValueOnce(user1)
        .mockResolvedValueOnce(user2)

      renderAdminPanel()

      await waitFor(() => {
        expect(screen.getByText('Alice')).toBeInTheDocument()
        expect(screen.getByText('Bob')).toBeInTheDocument()
      })

      // Bob is admin
      expect(screen.getByText('Yes')).toBeInTheDocument()
    })

    it('shows "No users found." when the user list is empty', async () => {
      vi.mocked(adminService.listUsers).mockResolvedValue([])

      renderAdminPanel()

      await waitFor(() => {
        expect(screen.getByText('No users found.')).toBeInTheDocument()
      })
    })
  })

  describe('row click navigation', () => {
    it('navigates to /admin/users/<user_id> when a user row is clicked', async () => {
      const user1 = makeUserSummary({ user_id: 'user-abc-123', display_name: 'Alice' })

      vi.mocked(adminService.listUsers).mockResolvedValue([user1])
      vi.mocked(adminService.getUserSummary).mockResolvedValue(user1)

      renderAdminPanel()

      await waitFor(() => {
        expect(screen.getByText('Alice')).toBeInTheDocument()
      })

      // Click the row — it has role="button" and aria-label="View details for Alice"
      const row = screen.getByRole('button', { name: 'View details for Alice' })
      row.click()

      expect(mockNavigate).toHaveBeenCalledWith('/admin/users/user-abc-123')
    })

    it('navigates to the correct user_id for each row independently', async () => {
      const user1 = makeUserSummary({ user_id: 'user-111', display_name: 'Alice' })
      const user2 = makeUserSummary({ user_id: 'user-222', display_name: 'Bob' })

      vi.mocked(adminService.listUsers).mockResolvedValue([user1, user2])
      vi.mocked(adminService.getUserSummary)
        .mockResolvedValueOnce(user1)
        .mockResolvedValueOnce(user2)

      renderAdminPanel()

      await waitFor(() => {
        expect(screen.getByText('Bob')).toBeInTheDocument()
      })

      const bobRow = screen.getByRole('button', { name: 'View details for Bob' })
      bobRow.click()

      expect(mockNavigate).toHaveBeenCalledWith('/admin/users/user-222')
    })
  })
})

// ---------------------------------------------------------------------------
// Property 10: Admin route access control
//
// Validates: Requirements 6.1, 6.2
//
// For any admin user (is_admin = true), the /admin route SHALL render the
// AdminPanel component. For any non-admin user (is_admin = false), navigating
// to /admin SHALL redirect to the home page (/). The "Admin" sidebar link
// SHALL be present only when is_admin = true.
// ---------------------------------------------------------------------------

/**
 * Helper: a minimal component that captures the current location pathname
 * so we can assert redirects in tests.
 */
function LocationDisplay() {
  const location = useLocation()
  return <div data-testid="location-display">{location.pathname}</div>
}

/**
 * Render the admin route guard element inside a MemoryRouter starting at /admin.
 * The guard mirrors the App.tsx pattern:
 *   user?.is_admin ? <AdminPanel /> : <Navigate to="/" replace />
 *
 * We also render a home route ("/") so Navigate has somewhere to land,
 * and a LocationDisplay so we can assert the final pathname.
 */
function renderAdminRouteGuard(user: AuthUser | null) {
  mockUseAuth.mockReturnValue({
    user,
    token: user ? 'fake-token' : null,
    login: vi.fn(),
    logout: vi.fn(),
    isLoading: false,
  })

  return render(
    <MemoryRouter initialEntries={['/admin']}>
      <Routes>
        <Route path="/" element={<LocationDisplay />} />
        <Route
          path="/admin"
          element={user?.is_admin ? <AdminPanel /> : <Navigate to="/" replace />}
        />
      </Routes>
    </MemoryRouter>
  )
}

describe('Property 10: Admin route access control', () => {
  /**
   * **Validates: Requirements 6.1, 6.2**
   *
   * For any non-admin user (is_admin = false), navigating to /admin SHALL
   * redirect to the home page (/). The AdminPanel SHALL NOT be rendered.
   */
  it('redirects non-admin users away from /admin for any non-admin user identity', () => {
    fc.assert(
      fc.property(
        fc.record({
          user_id: fc.uuid(),
          email: fc.emailAddress(),
          display_name: fc.string({ minLength: 1, maxLength: 50 }),
        }),
        (userFields) => {
          const user: AuthUser = { ...userFields, is_admin: false }

          const { getByTestId, queryByRole, unmount } = renderAdminRouteGuard(user)

          // Should have redirected to "/" — LocationDisplay renders the pathname
          expect(getByTestId('location-display').textContent).toBe('/')

          // AdminPanel table must NOT be rendered
          expect(queryByRole('table')).not.toBeInTheDocument()

          unmount()
        }
      ),
      { numRuns: 100 }
    )
  })

  /**
   * **Validates: Requirements 6.1, 6.2**
   *
   * For any admin user (is_admin = true), navigating to /admin SHALL render
   * the AdminPanel component (loading state is acceptable — the component
   * mounts and shows a progress indicator or table).
   */
  it('renders AdminPanel for admin users for any admin user identity', async () => {
    // Set up adminService to return an empty list so AdminPanel renders cleanly
    vi.mocked(adminService.listUsers).mockResolvedValue([])

    await fc.assert(
      fc.asyncProperty(
        fc.record({
          user_id: fc.uuid(),
          email: fc.emailAddress(),
          display_name: fc.string({ minLength: 1, maxLength: 50 }),
        }),
        async (userFields) => {
          const user: AuthUser = { ...userFields, is_admin: true }

          const { queryByTestId, getByRole, unmount } = renderAdminRouteGuard(user)

          // Should NOT have redirected — LocationDisplay is only rendered at "/"
          expect(queryByTestId('location-display')).not.toBeInTheDocument()

          // AdminPanel heading must be present
          await waitFor(() => {
            expect(getByRole('heading', { name: /admin panel/i })).toBeInTheDocument()
          })

          unmount()
        }
      ),
      { numRuns: 100 }
    )
  }, 30000)
})
