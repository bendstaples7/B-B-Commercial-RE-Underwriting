import { describe, it, expect } from 'vitest'
import userEvent from '@testing-library/user-event'
import { screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { render } from '@/test/testUtils'
import { HeaderQuickAddButton } from './HeaderQuickAddButton'

function renderButton() {
  return render(
    <MemoryRouter>
      <HeaderQuickAddButton />
    </MemoryRouter>,
  )
}

describe('HeaderQuickAddButton', () => {
  it('opens property-or-lead and contact capture from the header plus', async () => {
    const user = userEvent.setup()
    renderButton()

    await user.click(screen.getByTestId('header-add-button'))
    expect(screen.getByTestId('header-add-property-or-lead')).toBeInTheDocument()
    expect(screen.queryByTestId('header-add-property')).not.toBeInTheDocument()
    expect(screen.queryByTestId('header-add-lead')).not.toBeInTheDocument()
    expect(screen.getByTestId('header-add-contact')).toBeInTheDocument()

    await user.click(screen.getByTestId('header-add-contact'))
    expect(screen.getByRole('heading', { name: 'Add Contact' })).toBeInTheDocument()
    expect(screen.getByLabelText('Source')).toBeInTheDocument()
    expect(screen.getByLabelText('Why are you adding this')).toBeInTheDocument()
    expect(screen.getByLabelText('Notes')).toBeInTheDocument()
  })
})
