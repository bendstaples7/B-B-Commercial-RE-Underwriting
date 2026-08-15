import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider, createTheme } from '@mui/material'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import type { CommandCenterPayload } from '@/types'

function renderSidebar(
  payload: Partial<CommandCenterPayload>,
  variant: 'sidebar' | 'inline' = 'sidebar',
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const theme = createTheme()
  const data = {
    id: 4490,
    property_street: '1233 West Foster Avenue',
    property_city: 'Chicago',
    property_state: 'IL',
    property_zip: '60640',
    bedrooms: 6,
    bathrooms: 6,
    units: 6,
    lead_category: 'commercial',
    property_type: 'Commercial',
    note_property_facts: {
      units: 6,
      unit_mix: [
        { units: 4, beds: 2 },
        { units: 2, beds: 3 },
      ],
    },
    ...payload,
  } as CommandCenterPayload
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <ThemeProvider theme={theme}>
          <PropertySidebar commandCenterData={data} variant={variant} />
        </ThemeProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('PropertySidebar note + assessor beds', () => {
  it('shows Notes mix and Assessor beds together for foster-shaped lead', () => {
    renderSidebar({})
    expect(screen.getByTestId('sidebar-beds-baths-dual')).toBeInTheDocument()
    expect(screen.getByText(/Notes: 4×2 bd \+ 2×3 bd/)).toBeInTheDocument()
    expect(screen.getByText(/Assessor: 6 bd \/ 6 ba/)).toBeInTheDocument()
  })

  it('renders the dual value inside labeled content for inline layout', () => {
    renderSidebar({}, 'inline')

    const row = screen.getByTestId('sidebar-beds-baths')
    const dual = screen.getByTestId('sidebar-beds-baths-dual')

    expect(row).toContainElement(dual)
    expect(row.querySelector('p [data-testid="sidebar-beds-baths-dual"]')).toBeNull()
  })
})
