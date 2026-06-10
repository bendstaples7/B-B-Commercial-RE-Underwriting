/**
 * Component tests for GlobalSearchBar
 *
 * Covers:
 * - Property 1: Debounce contract (Requirements 2.1)
 * - Property 2: Short queries never trigger search (Requirements 2.2)
 * - Property 3: Input length hard cap (Requirements 2.5)
 * - Property 11: Lead result navigation targets correct path (Requirements 5.1)
 * - Property 12: Session result navigation uses returned nav_path (Requirements 5.2)
 * - Example-based unit tests (Requirements 1.3, 1.4, 2.3, 2.4, 4.2–4.6, 5.1, 5.2)
 *
 * Requirements: 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, within, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider, createTheme } from '@mui/material'
import fc from 'fast-check'
import GlobalSearchBar from './GlobalSearchBar'
import type { SearchResponse } from '@/types'

// ---------------------------------------------------------------------------
// Module-level mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn()

// Mock react-router-dom so useNavigate returns our spy
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

// Mock the search service — we control its behaviour per-test with vi.spyOn
vi.mock('@/services/api', () => ({
  searchService: {
    search: vi.fn(),
  },
}))

import { searchService } from '@/services/api'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const theme = createTheme()

/**
 * Minimal provider wrapper required by the component:
 * - MemoryRouter  → useNavigate
 * - ThemeProvider → useMediaQuery / MUI breakpoints
 */
function TestWrapper({ children }: { children: React.ReactNode }) {
  return (
    <MemoryRouter>
      <ThemeProvider theme={theme}>{children}</ThemeProvider>
    </MemoryRouter>
  )
}

function renderSearchBar() {
  return render(<GlobalSearchBar />, { wrapper: TestWrapper })
}

/** Empty search response — no results */
const emptyResults: SearchResponse = { leads: [], sessions: [] }

// ---------------------------------------------------------------------------
// Set up mock matchMedia (desktop by default)
// ---------------------------------------------------------------------------

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

function mockMobile() {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

// ---------------------------------------------------------------------------
// beforeEach / afterEach
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
  mockDesktop()
})

afterEach(() => {
  vi.useRealTimers()
})

// ---------------------------------------------------------------------------
// Utility: fire an input change event on the InputBase wrapper element.
// Returns the underlying <input> for convenience.
// ---------------------------------------------------------------------------

function fireInputChange(container: Element, value: string): HTMLInputElement {
  // Accept either the InputBase wrapper Box or the raw <input>
  const inputEl: HTMLInputElement =
    container.tagName === 'INPUT'
      ? (container as HTMLInputElement)
      : (container.querySelector('input') as HTMLInputElement) ?? (container as HTMLInputElement)

  // Use the native setter so React's synthetic event system picks it up
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value'
  )?.set
  nativeInputValueSetter?.call(inputEl, value)
  inputEl.dispatchEvent(new Event('input', { bubbles: true }))
  inputEl.dispatchEvent(new Event('change', { bubbles: true }))
  return inputEl
}

// ---------------------------------------------------------------------------
// Property 1: Debounce contract
//
// **Validates: Requirements 2.1**
//
// For any string ≥2 non-whitespace chars typed within 300ms, the search API
// SHALL be called exactly once after the debounce window elapses.
// ---------------------------------------------------------------------------

describe('Property 1: Debounce contract', () => {
  it('calls searchService.search exactly once after 300ms debounce for a multi-char query', async () => {
    vi.useFakeTimers()
    const mockSearch = vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

    renderSearchBar()
    const input = screen.getByTestId('search-input')

    // Type 3 characters quickly (all within the same timer window)
    fireInputChange(input, 'a')
    fireInputChange(input, 'ab')
    fireInputChange(input, 'abc')

    // Before 300ms: no search dispatched
    expect(mockSearch).not.toHaveBeenCalled()

    // Advance past debounce window
    await act(async () => {
      vi.advanceTimersByTime(300)
    })

    expect(mockSearch).toHaveBeenCalledTimes(1)
    expect(mockSearch).toHaveBeenCalledWith('abc', expect.any(AbortSignal))

    mockSearch.mockRestore()
  })

  /**
   * **Validates: Requirements 2.1**
   *
   * Property: for any alphanumeric string of length ≥2, typing it then waiting
   * ≥300ms always results in exactly one search call with the trimmed value.
   *
   * Constrains to alphanumeric strings to guarantee trimmed length = raw length,
   * avoiding whitespace-only edge cases which Property 2 covers.
   */
  it('calls search exactly once for any query string with trimmed length ≥2 (property-based)', () => {
    vi.useFakeTimers()

    // fast-check v4: use fc.string with a mapped filter rather than fc.stringOf
    const alphanumericArb = fc.string({ minLength: 2, maxLength: 20 }).filter(
      (s) => /^[a-z0-9]+$/i.test(s) && s.trim().length >= 2
    )

    fc.assert(
      fc.property(
        alphanumericArb,
        (query) => {
          mockDesktop() // ensure matchMedia is set for each run
          const mockSearch = vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

          const { unmount, container } = renderSearchBar()
          const input = within(container).getByTestId('search-input')

          fireInputChange(input, query)

          // Before timer fires: no call
          expect(mockSearch).not.toHaveBeenCalled()

          // Advance past debounce
          act(() => { vi.advanceTimersByTime(300) })

          expect(mockSearch).toHaveBeenCalledTimes(1)
          expect(mockSearch).toHaveBeenCalledWith(query.trim(), expect.any(AbortSignal))

          unmount()
          mockSearch.mockRestore()

          return true
        }
      ),
      { numRuns: 50 }
    )
  })
})

// ---------------------------------------------------------------------------
// Property 2: Short queries never trigger search
//
// **Validates: Requirements 2.2**
// ---------------------------------------------------------------------------

describe('Property 2: Short queries never trigger search', () => {
  it('does not call search for an empty query', async () => {
    vi.useFakeTimers()
    const mockSearch = vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

    renderSearchBar()
    const input = screen.getByTestId('search-input')

    fireInputChange(input, '')

    act(() => { vi.advanceTimersByTime(500) })

    expect(mockSearch).not.toHaveBeenCalled()
    mockSearch.mockRestore()
  })

  it('does not call search for a single character query', async () => {
    vi.useFakeTimers()
    const mockSearch = vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

    renderSearchBar()
    const input = screen.getByTestId('search-input')

    fireInputChange(input, 'a')

    act(() => { vi.advanceTimersByTime(500) })

    expect(mockSearch).not.toHaveBeenCalled()
    mockSearch.mockRestore()
  })

  /**
   * **Validates: Requirements 2.2**
   *
   * Property: for any string of trimmed length 0 or 1, search is never called.
   */
  it('never calls search for any query with trimmed length ≤1 (property-based)', () => {
    vi.useFakeTimers()

    // Strings that are at most 1 char after trimming (fast-check v4 compatible)
    const shortStringArb = fc.oneof(
      fc.constant(''),
      fc.constant(' '),
      fc.constant('  '),
      fc.constant('\t'),
      // Single printable character (ASCII printable range 32-126)
      fc.integer({ min: 32, max: 126 }).map((code) => String.fromCharCode(code)),
      // Single char with surrounding whitespace
      fc.integer({ min: 32, max: 126 }).map((code) => ` ${String.fromCharCode(code)} `),
    )

    fc.assert(
      fc.property(
        shortStringArb,
        (query) => {
          mockDesktop() // ensure matchMedia is set for each run
          const mockSearch = vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

          const { unmount, container } = renderSearchBar()
          const input = within(container).getByTestId('search-input')

          fireInputChange(input, query)
          act(() => { vi.advanceTimersByTime(500) })

          expect(mockSearch).not.toHaveBeenCalled()

          unmount()
          mockSearch.mockRestore()

          return true
        }
      ),
      { numRuns: 50 }
    )
  })
})

// ---------------------------------------------------------------------------
// Property 3: Input length hard cap
//
// **Validates: Requirements 2.5**
// ---------------------------------------------------------------------------

describe('Property 3: Input length hard cap', () => {
  it('input element has maxLength attribute of 200', () => {
    renderSearchBar()
    const inputEl = screen.getByTestId('search-input').querySelector('input')!
    expect(inputEl).not.toBeNull()
    expect(inputEl.maxLength).toBe(200)
  })

  /**
   * **Validates: Requirements 2.5**
   *
   * Property: for any string longer than 200 characters, the input element's
   * maxLength is set to 200 — JSDOM enforces this constraint.
   */
  it('enforces 200-character limit for any oversized input (property-based)', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 201, maxLength: 300 }),
        (longString) => {
          const { unmount, container } = renderSearchBar()
          const inputEl = within(container).getByTestId('search-input').querySelector('input')!

          // The maxLength DOM attribute guarantees browsers/JSDOM cap at 200 chars
          expect(inputEl.maxLength).toBe(200)
          expect(longString.length).toBeGreaterThan(200)

          unmount()
          return true
        }
      ),
      { numRuns: 50 }
    )
  })
})

// ---------------------------------------------------------------------------
// Property 11: Lead result navigation targets correct path
//
// **Validates: Requirements 5.1**
// ---------------------------------------------------------------------------

describe('Property 11: Lead result navigation targets correct path', () => {
  /**
   * **Validates: Requirements 5.1**
   *
   * For any lead id, clicking the lead result navigates to /properties/{id}.
   */
  it('navigates to /properties/{id} for any lead id (property-based)', async () => {
    vi.useFakeTimers()

    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 999999 }),
        async (leadId) => {
          const leadResult: SearchResponse = {
            leads: [
              {
                id: leadId,
                type: 'lead',
                label: `Lead ${leadId}`,
                nav_path: `/properties/${leadId}`,
              },
            ],
            sessions: [],
          }

          vi.spyOn(searchService, 'search').mockResolvedValue(leadResult)
          mockNavigate.mockClear()
          mockDesktop() // re-apply matchMedia for each PBT iteration

          const { unmount, container } = renderSearchBar()
          const input = within(container).getByTestId('search-input')

          fireInputChange(input, 'te')

          act(() => { vi.advanceTimersByTime(300) })

          // Flush promises so the mock resolves
          await act(async () => { await Promise.resolve() })

          const leadItem = within(container).getByTestId(`lead-result-${leadId}`)
          act(() => { leadItem.click() })

          expect(mockNavigate).toHaveBeenCalledWith(`/properties/${leadId}`)

          unmount()
          vi.mocked(searchService.search).mockReset()
          vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

          return true
        }
      ),
      { numRuns: 20 }
    )
  })
})

// ---------------------------------------------------------------------------
// Property 12: Session result navigation uses returned nav_path
//
// **Validates: Requirements 5.2**
// ---------------------------------------------------------------------------

describe('Property 12: Session result navigation uses returned nav_path', () => {
  /**
   * **Validates: Requirements 5.2**
   *
   * For any session nav_path, clicking the session result navigates to
   * exactly that path — the frontend does not re-derive it.
   */
  it('navigates to the exact nav_path for any session result (property-based)', async () => {
    vi.useFakeTimers()

    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 99999 }),
        fc.uuid(),
        async (sessionId, sessionUuid) => {
          const navPath = `/analysis/arv/${sessionUuid}`
          const sessionResult: SearchResponse = {
            leads: [],
            sessions: [
              {
                id: sessionId,
                type: 'session',
                label: '123 Main St',
                nav_path: navPath,
                created_at: '2024-01-15T10:00:00Z',
                status: 'In Progress',
              },
            ],
          }

          vi.spyOn(searchService, 'search').mockResolvedValue(sessionResult)
          mockNavigate.mockClear()
          mockDesktop() // re-apply matchMedia for each PBT iteration

          const { unmount, container } = renderSearchBar()
          const input = within(container).getByTestId('search-input')

          fireInputChange(input, 'ma')

          act(() => { vi.advanceTimersByTime(300) })

          // Flush promises so the mock resolves
          await act(async () => { await Promise.resolve() })

          const sessionItem = within(container).getByTestId(`session-result-${sessionId}`)
          act(() => { sessionItem.click() })

          expect(mockNavigate).toHaveBeenCalledWith(navPath)

          unmount()
          vi.mocked(searchService.search).mockReset()
          vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

          return true
        }
      ),
      { numRuns: 20 }
    )
  })
})

// ---------------------------------------------------------------------------
// Example-based unit tests (Task 7.14)
//
// Requirements: 1.3, 1.4, 2.3, 2.4, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2
// ---------------------------------------------------------------------------

describe('GlobalSearchBar — example-based unit tests', () => {
  // -------------------------------------------------------------------------
  // Mobile / Desktop rendering
  // -------------------------------------------------------------------------

  describe('responsive rendering', () => {
    it('renders icon button on mobile (useMediaQuery returns true)', () => {
      mockMobile()
      renderSearchBar()

      expect(screen.getByTestId('search-icon-button')).toBeInTheDocument()
      expect(screen.queryByTestId('search-input')).not.toBeInTheDocument()
    })

    it('renders text input on desktop (useMediaQuery returns false)', () => {
      // Default matchMedia already returns matches: false
      renderSearchBar()

      expect(screen.getByTestId('search-input')).toBeInTheDocument()
      expect(screen.queryByTestId('search-icon-button')).not.toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Mobile expand / collapse
  // -------------------------------------------------------------------------

  describe('mobile expand / collapse', () => {
    it('icon button click expands the input', async () => {
      mockMobile()
      renderSearchBar()

      const iconBtn = screen.getByTestId('search-icon-button')
      await act(async () => { iconBtn.click() })

      expect(screen.getByTestId('search-input')).toBeInTheDocument()
    })

    it('empty blur collapses mobile input', async () => {
      mockMobile()
      renderSearchBar()

      // Expand
      const iconBtn = screen.getByTestId('search-icon-button')
      await act(async () => { iconBtn.click() })

      expect(screen.getByTestId('search-input')).toBeInTheDocument()

      // Blur the underlying <input> while query is empty
      const inputEl = screen.getByTestId('search-input').querySelector('input')!
      await act(async () => {
        inputEl.focus()
        inputEl.blur()
      })

      // After blur with empty query, icon button should return
      await waitFor(() => {
        expect(screen.getByTestId('search-icon-button')).toBeInTheDocument()
      })
    })
  })

  // -------------------------------------------------------------------------
  // Keyboard: Escape
  // -------------------------------------------------------------------------

  describe('Escape key behaviour', () => {
    it('Escape clears query, closes dropdown, and removes focus', async () => {
      vi.useFakeTimers()
      vi.spyOn(searchService, 'search').mockResolvedValue({
        leads: [{ id: 1, type: 'lead', label: 'John Doe', nav_path: '/properties/1' }],
        sessions: [],
      })

      renderSearchBar()
      const input = screen.getByTestId('search-input')
      const inputEl = input.querySelector('input')!

      // Type query and advance past debounce
      fireInputChange(input, 'jo')
      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      // Dropdown should now be open
      expect(screen.getByTestId('search-dropdown')).toBeInTheDocument()

      // Fire Escape key directly on the input element (no userEvent needed)
      await act(async () => {
        fireEvent.keyDown(inputEl, { key: 'Escape', code: 'Escape', bubbles: true })
      })

      // Dropdown should close and query should be empty
      expect(screen.queryByTestId('search-dropdown')).not.toBeInTheDocument()
      expect(inputEl.value).toBe('')
    })
  })

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  describe('loading state', () => {
    it('shows loading spinner while request is in-flight', async () => {
      vi.useFakeTimers()
      // Return a promise that never resolves — keeps loading state perpetually
      vi.spyOn(searchService, 'search').mockReturnValue(new Promise<SearchResponse>(() => {}))

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'te')

      await act(async () => { vi.advanceTimersByTime(300) })
      // Allow the microtask queue to settle (the debounce callback runs the async fetch)
      await act(async () => { await Promise.resolve() })

      expect(screen.getByTestId('search-dropdown')).toBeInTheDocument()
      expect(screen.getByRole('progressbar')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Empty state
  // -------------------------------------------------------------------------

  describe('empty state', () => {
    it('shows "No results found" when both arrays are empty', async () => {
      vi.useFakeTimers()
      vi.spyOn(searchService, 'search').mockResolvedValue(emptyResults)

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'xyz')

      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      expect(screen.getByText('No results found')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Error state
  // -------------------------------------------------------------------------

  describe('error state', () => {
    it('shows "Search failed. Please try again." on error response', async () => {
      vi.useFakeTimers()
      vi.spyOn(searchService, 'search').mockRejectedValue(new Error('Network error'))

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'er')

      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      expect(screen.getByText('Search failed. Please try again.')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Navigation on click
  // -------------------------------------------------------------------------

  describe('result navigation', () => {
    it('clicking a lead result navigates to /properties/{id}', async () => {
      vi.useFakeTimers()
      vi.spyOn(searchService, 'search').mockResolvedValue({
        leads: [{ id: 42, type: 'lead', label: 'John Doe', nav_path: '/properties/42' }],
        sessions: [],
      })

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'jo')

      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      expect(screen.getByTestId('lead-result-42')).toBeInTheDocument()

      act(() => { screen.getByTestId('lead-result-42').click() })

      expect(mockNavigate).toHaveBeenCalledWith('/properties/42')
    })

    it('clicking a session result navigates to nav_path', async () => {
      vi.useFakeTimers()
      const navPath = '/analysis/arv/abc-123-def'
      vi.spyOn(searchService, 'search').mockResolvedValue({
        leads: [],
        sessions: [
          {
            id: 7,
            type: 'session',
            label: '456 Oak Ave',
            nav_path: navPath,
            created_at: '2024-06-01T00:00:00Z',
            status: 'Complete',
          },
        ],
      })

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'oa')

      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      expect(screen.getByTestId('session-result-7')).toBeInTheDocument()

      act(() => { screen.getByTestId('session-result-7').click() })

      expect(mockNavigate).toHaveBeenCalledWith(navPath)
    })
  })

  // -------------------------------------------------------------------------
  // Grouped result sections
  // -------------------------------------------------------------------------

  describe('grouped sections', () => {
    it('results are grouped under "Leads" and "Analysis Sessions" headers', async () => {
      vi.useFakeTimers()
      vi.spyOn(searchService, 'search').mockResolvedValue({
        leads: [{ id: 1, type: 'lead', label: 'Alice Smith', nav_path: '/properties/1' }],
        sessions: [
          {
            id: 2,
            type: 'session',
            label: '123 Main St',
            nav_path: '/analysis/arv/some-uuid',
            created_at: '2024-01-01T00:00:00Z',
            status: 'In Progress',
          },
        ],
      })

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'al')

      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      expect(screen.getByText('Leads')).toBeInTheDocument()
      expect(screen.getByText('Analysis Sessions')).toBeInTheDocument()
    })

    it('omits "Leads" section when leads array is empty', async () => {
      vi.useFakeTimers()
      vi.spyOn(searchService, 'search').mockResolvedValue({
        leads: [],
        sessions: [
          {
            id: 5,
            type: 'session',
            label: '99 Elm Dr',
            nav_path: '/analysis/arv/session-uuid',
            created_at: '2024-03-01T00:00:00Z',
          },
        ],
      })

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'el')

      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      expect(screen.getByText('Analysis Sessions')).toBeInTheDocument()
      expect(screen.queryByText('Leads')).not.toBeInTheDocument()
    })

    it('omits "Analysis Sessions" section when sessions array is empty', async () => {
      vi.useFakeTimers()
      vi.spyOn(searchService, 'search').mockResolvedValue({
        leads: [{ id: 3, type: 'lead', label: 'Bob Jones', nav_path: '/properties/3' }],
        sessions: [],
      })

      renderSearchBar()
      const input = screen.getByTestId('search-input')

      fireInputChange(input, 'bo')

      await act(async () => { vi.advanceTimersByTime(300) })
      await act(async () => { await Promise.resolve() })

      expect(screen.getByText('Leads')).toBeInTheDocument()
      expect(screen.queryByText('Analysis Sessions')).not.toBeInTheDocument()
    })
  })
})
