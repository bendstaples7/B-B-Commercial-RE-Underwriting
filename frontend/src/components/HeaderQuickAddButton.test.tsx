import { describe, it, expect, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render } from '@/test/testUtils'
import { HeaderQuickAddButton } from './HeaderQuickAddButton'

function renderButton(path = '/dashboard') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HeaderQuickAddButton />
      <Routes>
        <Route path="/quick-add" element={<div>Quick add form</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

function mockBreakpoint(matchesQuery: (query: string) => boolean) {
  const original = window.matchMedia
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: matchesQuery(query),
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
  return () => {
    window.matchMedia = original
  }
}

describe('HeaderQuickAddButton', () => {
  it('opens quick add from the header plus', async () => {
    const user = userEvent.setup()
    renderButton()

    await user.click(screen.getByTestId('header-add-button'))
    expect(screen.getByText('Quick add form')).toBeInTheDocument()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('hides the plus on a phone-width screen', () => {
    const restore = mockBreakpoint((query) => query.includes('max-width'))
    try {
      renderButton()
      expect(screen.queryByTestId('header-add-button')).not.toBeInTheDocument()
    } finally {
      restore()
    }
  })

  it('hides the plus while quick add is already open', () => {
    renderButton('/quick-add')
    expect(screen.queryByTestId('header-add-button')).not.toBeInTheDocument()
    expect(screen.getByText('Quick add form')).toBeInTheDocument()
  })
})
