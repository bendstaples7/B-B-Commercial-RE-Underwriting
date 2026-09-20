import { describe, it, expect } from 'vitest'
import userEvent from '@testing-library/user-event'
import { screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render } from '@/test/testUtils'
import { HeaderQuickAddButton } from './HeaderQuickAddButton'

function renderButton() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <HeaderQuickAddButton />
      <Routes>
        <Route path="/quick-add" element={<div>Quick add form</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HeaderQuickAddButton', () => {
  it('opens quick add from the header plus', async () => {
    const user = userEvent.setup()
    renderButton()

    await user.click(screen.getByTestId('header-add-button'))
    expect(screen.getByText('Quick add form')).toBeInTheDocument()
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})
