/**
 * Tests for QuickAddFabHost — FAB must stay mounted across route content updates.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { DndContext } from '@dnd-kit/core'
import { useState } from 'react'
import { QuickAddFabHost, applyVisualViewportPosition, FAB_MARGIN, FAB_SIZE } from './QuickAddFab'

const mockNavigate = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

const mockUseAuth = vi.fn()

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
}))

const mockUser = {
  user_id: 'test-user',
  email: 'test@example.com',
  display_name: 'Test User',
  is_admin: false,
}

function renderFabAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="*" element={<QuickAddFabHost />} />
      </Routes>
    </MemoryRouter>,
  )
}

function KanbanSimulator() {
  const [showBoard, setShowBoard] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setShowBoard(true)}>
        Load kanban
      </button>
      {showBoard ? (
        <DndContext>
          <div data-testid="kanban-board">Kanban board</div>
        </DndContext>
      ) : (
        <div data-testid="kanban-loading">Loading…</div>
      )}
      <QuickAddFabHost />
    </>
  )
}

describe('QuickAddFabHost', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
    mockUseAuth.mockReturnValue({
      user: mockUser,
      token: 'token',
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: false,
    })
  })

  it('renders FAB when user is authenticated and not on /quick-add', () => {
    renderFabAt('/kanban')
    expect(screen.getByTestId('quick-add-fab')).toBeInTheDocument()
  })

  it('hides FAB on /quick-add', () => {
    renderFabAt('/quick-add')
    expect(screen.queryByTestId('quick-add-fab')).not.toBeInTheDocument()
  })

  it('hides FAB while auth is loading', () => {
    mockUseAuth.mockReturnValue({
      user: null,
      token: null,
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: true,
    })
    renderFabAt('/kanban')
    expect(screen.queryByTestId('quick-add-fab')).not.toBeInTheDocument()
  })

  it('hides FAB when user is not authenticated', () => {
    mockUseAuth.mockReturnValue({
      user: null,
      token: null,
      login: vi.fn(),
      logout: vi.fn(),
      isLoading: false,
    })
    renderFabAt('/kanban')
    expect(screen.queryByTestId('quick-add-fab')).not.toBeInTheDocument()
  })

  it('navigates to /quick-add on click', async () => {
    const user = userEvent.setup()
    renderFabAt('/kanban')
    await user.click(screen.getByTestId('quick-add-fab'))
    expect(mockNavigate).toHaveBeenCalledWith('/quick-add')
  })

  it('remains visible after parent re-render simulating kanban load', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/kanban']}>
        <KanbanSimulator />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('quick-add-fab')).toBeInTheDocument()
    expect(screen.getByTestId('kanban-loading')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Load kanban' }))

    expect(screen.getByTestId('kanban-board')).toBeInTheDocument()
    expect(screen.getByTestId('quick-add-fab')).toBeInTheDocument()
  })

  it('positions FAB using visual viewport when layout viewport is taller', () => {
    const el = document.createElement('button')
    const setPropertySpy = vi.spyOn(el.style, 'setProperty')
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 2668 })
    Object.defineProperty(window, 'visualViewport', {
      configurable: true,
      value: {
        offsetTop: 0,
        offsetLeft: 0,
        height: 667,
        width: 375,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    })

    applyVisualViewportPosition(el)

    const top = parseFloat(el.style.getPropertyValue('top'))
    expect(top).toBe(667 - FAB_SIZE - FAB_MARGIN)
    expect(top + FAB_SIZE).toBeLessThanOrEqual(667)
    expect(el.style.getPropertyValue('left')).toBe(`${375 - FAB_SIZE - FAB_MARGIN}px`)
    expect(el.style.getPropertyValue('bottom')).toBe('auto')
    expect(el.style.getPropertyValue('right')).toBe('auto')
    expect(el.style.getPropertyValue('position')).toBe('fixed')
    expect(setPropertySpy).toHaveBeenCalledWith('top', expect.any(String), 'important')
    expect(setPropertySpy).toHaveBeenCalledWith('position', 'fixed', 'important')
    setPropertySpy.mockRestore()
  })

  it('applies visual viewport positioning on mount via callback ref', () => {
    Object.defineProperty(window, 'visualViewport', {
      configurable: true,
      value: {
        offsetTop: 0,
        offsetLeft: 0,
        height: 800,
        width: 1200,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    })

    renderFabAt('/kanban')

    const fab = screen.getByTestId('quick-add-fab')
    expect(fab.style.getPropertyValue('position')).toBe('fixed')
    expect(parseFloat(fab.style.getPropertyValue('top'))).toBe(
      800 - FAB_SIZE - FAB_MARGIN,
    )
    expect(parseFloat(fab.style.getPropertyValue('left'))).toBe(
      1200 - FAB_SIZE - FAB_MARGIN,
    )
  })

  it('re-syncs position when ResizeObserver fires after layout viewport grows', () => {
    let resizeCallback: (() => void) | undefined
    const ResizeObserverMock = vi.fn(function (this: ResizeObserver, cb: ResizeObserverCallback) {
      resizeCallback = () => cb([], this as unknown as ResizeObserver)
      return {
        observe: vi.fn(),
        disconnect: vi.fn(),
        unobserve: vi.fn(),
      }
    })
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)

    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 2668 })
    Object.defineProperty(window, 'visualViewport', {
      configurable: true,
      value: {
        offsetTop: 0,
        offsetLeft: 0,
        height: 667,
        width: 375,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    })

    renderFabAt('/kanban')

    expect(ResizeObserverMock).toHaveBeenCalled()
    expect(resizeCallback).toBeDefined()

    const fab = screen.getByTestId('quick-add-fab')
    resizeCallback!()

    const top = parseFloat(fab.style.getPropertyValue('top'))
    expect(top).toBe(667 - FAB_SIZE - FAB_MARGIN)
    expect(top + FAB_SIZE).toBeLessThanOrEqual(667)

    vi.unstubAllGlobals()
  })
})
