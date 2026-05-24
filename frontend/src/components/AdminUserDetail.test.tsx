/**
 * Component tests for AdminUserDetail
 *
 * Tests:
 * - Renders user profile fields from summary data
 * - Renders leads table with correct columns
 * - Back button navigates to /admin
 *
 * Requirements: 6.7
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AdminUserDetail from './AdminUserDetail'

// ---------------------------------------------------------------------------
// Mock @/services/api
// ---------------------------------------------------------------------------
vi.mock('@/services/api', () => ({
  adminService: {
    getUserSummary: vi.fn(),
    listLeads: vi.fn(),
  },
}))

import { adminService } from '@/services/api'

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------
const mockSummary = {
  user_id: 'user-abc-123',
  email: 'alice@example.com',
  display_name: 'Alice Smith',
  is_active: true,
  is_admin: false,
  created_at: '2024-01-15T10:00:00Z',
  lead_count: 5,
  marketing_list_count: 2,
  import_job_count: 3,
}

const mockLeadsResponse = {
  leads: [
    {
      id: 1,
      owner_user_id: 'user-abc-123',
      owner_display_name: 'Alice Smith',
      property_street: '123 Main St',
      property_city: 'Chicago',
      property_state: 'IL',
      lead_status: 'new',
      lead_score: 75,
      created_at: '2024-02-01T08:00:00Z',
    },
    {
      id: 2,
      owner_user_id: 'user-abc-123',
      owner_display_name: 'Alice Smith',
      property_street: '456 Oak Ave',
      property_city: 'Evanston',
      property_state: 'IL',
      lead_status: 'active',
      lead_score: 88,
      created_at: '2024-02-10T09:00:00Z',
    },
  ],
  total_count: 2,
  page: 1,
  page_size: 50,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
}

/**
 * Renders AdminUserDetail inside the required providers, with the route
 * param set to the given userId.
 */
function renderComponent(userId = 'user-abc-123') {
  const queryClient = createQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/admin/users/${userId}`]}>
        <Routes>
          <Route path="/admin/users/:userId" element={<AdminUserDetail />} />
          <Route path="/admin" element={<div data-testid="admin-panel">Admin Panel</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('AdminUserDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // -------------------------------------------------------------------------
  // Test 1: Renders user profile fields from summary data
  // -------------------------------------------------------------------------
  it('renders user profile fields from summary data', async () => {
    vi.mocked(adminService.getUserSummary).mockResolvedValue(mockSummary)
    vi.mocked(adminService.listLeads).mockResolvedValue(mockLeadsResponse)

    renderComponent()

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByText('Alice Smith')).toBeInTheDocument()
    })

    // Display name (rendered as Typography h5)
    expect(screen.getByText('Alice Smith')).toBeInTheDocument()

    // Email
    expect(screen.getByText('alice@example.com')).toBeInTheDocument()

    // Status chip — active
    expect(screen.getByText('Active')).toBeInTheDocument()

    // Admin chip — No
    expect(screen.getByText('No')).toBeInTheDocument()

    // Member Since — formatted date
    const memberSince = new Date('2024-01-15T10:00:00Z').toLocaleDateString()
    expect(screen.getByText(memberSince)).toBeInTheDocument()

    // Lead count
    expect(screen.getByText('5')).toBeInTheDocument()

    // Marketing lists count
    expect(screen.getByText('2')).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Test 2: Renders leads table with correct columns
  // -------------------------------------------------------------------------
  it('renders leads table with correct columns', async () => {
    vi.mocked(adminService.getUserSummary).mockResolvedValue(mockSummary)
    vi.mocked(adminService.listLeads).mockResolvedValue(mockLeadsResponse)

    renderComponent()

    // Wait for the table to appear
    await waitFor(() => {
      expect(screen.getByText('Property Address')).toBeInTheDocument()
    })

    // All required column headers — "Status" also appears as a profile field
    // label, so we use getAllByText and confirm at least one is a table header.
    expect(screen.getByText('Property Address')).toBeInTheDocument()
    expect(screen.getByText('City')).toBeInTheDocument()
    expect(screen.getByText('State')).toBeInTheDocument()
    const statusElements = screen.getAllByText('Status')
    expect(statusElements.some((el) => el.tagName === 'TH')).toBe(true)
    expect(screen.getByText('Score')).toBeInTheDocument()
    expect(screen.getByText('Created At')).toBeInTheDocument()

    // Lead row data — both rows share state "IL" so use getAllByText
    expect(screen.getByText('123 Main St')).toBeInTheDocument()
    expect(screen.getByText('Chicago')).toBeInTheDocument()
    expect(screen.getAllByText('IL').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('new')).toBeInTheDocument()
    expect(screen.getByText('75')).toBeInTheDocument()

    expect(screen.getByText('456 Oak Ave')).toBeInTheDocument()
    expect(screen.getByText('Evanston')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('88')).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Test 3: Back button navigates to /admin
  // -------------------------------------------------------------------------
  it('back button navigates to /admin', async () => {
    vi.mocked(adminService.getUserSummary).mockResolvedValue(mockSummary)
    vi.mocked(adminService.listLeads).mockResolvedValue(mockLeadsResponse)

    renderComponent()

    // Wait for the component to finish loading
    await waitFor(() => {
      expect(screen.getByText('Alice Smith')).toBeInTheDocument()
    })

    // Find and click the back button
    const backButton = screen.getByRole('button', { name: /back to admin/i })
    expect(backButton).toBeInTheDocument()

    await userEvent.click(backButton)

    // After clicking, the /admin route should render
    await waitFor(() => {
      expect(screen.getByTestId('admin-panel')).toBeInTheDocument()
    })
  })
})
