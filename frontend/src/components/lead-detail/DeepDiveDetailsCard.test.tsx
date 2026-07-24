import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider, createTheme } from '@mui/material'
import { DeepDiveDetailsCard } from './DeepDiveDetailsCard'

const theme = createTheme()

function renderDeepDive(initialEntry = '/leads/1') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <ThemeProvider theme={theme}>
        <DeepDiveDetailsCard>
          <div data-testid="deep-dive-child">Child tabs</div>
        </DeepDiveDetailsCard>
      </ThemeProvider>
    </MemoryRouter>,
  )
}

describe('DeepDiveDetailsCard', () => {
  it('renders with deep-dive-details id and shows children when expanded', () => {
    renderDeepDive()
    const root = screen.getByTestId('deep-dive-details')
    expect(root).toHaveAttribute('id', 'deep-dive-details')
    expect(screen.getByText('Deep Dive Details')).toBeInTheDocument()
    expect(screen.getByTestId('deep-dive-child')).toBeInTheDocument()
  })

  it('expands when ?tab= is set (deep link)', async () => {
    renderDeepDive('/leads/1?tab=score')
    await waitFor(() => {
      expect(screen.getByTestId('deep-dive-child')).toBeVisible()
    })
    expect(screen.getByTestId('deep-dive-details').className).toMatch(/Mui-expanded|expanded/i)
  })

  it('expands when location hash is #deep-dive-details', async () => {
    window.location.hash = '#deep-dive-details'
    try {
      renderDeepDive('/leads/1')
      await waitFor(() => {
        expect(screen.getByTestId('deep-dive-child')).toBeVisible()
      })
      window.dispatchEvent(new HashChangeEvent('hashchange'))
      await waitFor(() => {
        expect(screen.getByTestId('deep-dive-details')).toBeInTheDocument()
      })
    } finally {
      window.location.hash = ''
    }
  })
})
