import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme } from '@mui/material'
import { useState } from 'react'
import { QuickAddPage } from './QuickAddPage'

vi.mock('@/context/GoogleMapsContext', () => ({
  useGoogleMapsLoaded: () => true,
}))

vi.mock('use-places-autocomplete', () => ({
  default: () => {
    const [value, setValue] = useState('123 Main St')
    return {
      ready: true,
      value,
      suggestions: { status: '', data: [] },
      setValue,
      clearSuggestions: vi.fn(),
      init: vi.fn(),
    }
  },
}))

vi.mock('@/services/leadApi', () => ({
  leadService: {
    lookupQuickAdd: vi.fn(),
    quickAdd: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({
  commandCenterService: {
    updateStatus: vi.fn(),
  },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {
    enqueue: vi.fn(),
  },
}))

import { leadService } from '@/services/leadApi'
import { commandCenterService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'

const theme = createTheme()

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ThemeProvider theme={theme}>
          <QuickAddPage />
        </ThemeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(navigator, 'geolocation', {
    configurable: true,
    value: {
      getCurrentPosition: vi.fn((_success: PositionCallback, error: PositionErrorCallback) =>
        error({ code: 1, message: 'unavailable' } as GeolocationPositionError)),
    },
  })
  vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({
    matches: [
      {
        lead_id: 42,
        property_street: '123 Main St',
        lead_status: 'deprioritize',
        deal_source: 'Driving For Dollars',
        date_identified: null,
      },
    ],
  })
  vi.mocked(commandCenterService.updateStatus).mockResolvedValue({
    lead_status: 'mailing_no_contact_made',
  })
})

describe('QuickAddPage deprioritized matches', () => {
  it('reactivates an existing lead for outreach', async () => {
    renderPage()

    const action = await screen.findByRole('button', {
      name: 'Reactivate 123 Main St for outreach',
    })
    fireEvent.click(action)

    await waitFor(() => {
      expect(commandCenterService.updateStatus).toHaveBeenCalledWith(
        42,
        'mailing_no_contact_made',
      )
    })
    expect(openLetterService.enqueue).not.toHaveBeenCalled()
    expect(
      await screen.findByText(/appropriate outreach flow/i),
    ).toBeInTheDocument()
  })

  it('reactivates before adding an existing lead to mail', async () => {
    const order: string[] = []
    vi.mocked(commandCenterService.updateStatus).mockImplementation(async () => {
      order.push('reactivate')
      return { lead_status: 'mailing_no_contact_made' }
    })
    vi.mocked(openLetterService.enqueue).mockImplementation(async () => {
      order.push('mail')
      return {
        added: 1,
        skipped: 0,
        invalid: 0,
        results: [{ lead_id: 42, status: 'queued' }],
        queued_count: 1,
        batch_minimum: 1,
        allow_send_below_minimum: true,
        can_send: true,
        items: [],
      }
    })
    renderPage()

    fireEvent.click(
      await screen.findByRole('button', {
        name: 'Reactivate 123 Main St and add to mail',
      }),
    )

    await waitFor(() => {
      expect(openLetterService.enqueue).toHaveBeenCalledWith([42], 'quick-add')
    })
    expect(order).toEqual(['reactivate', 'mail'])
    expect(await screen.findByText(/added to the mail queue/i)).toBeInTheDocument()
  })

  it('hides stale reactivation actions while a new address is debouncing', async () => {
    renderPage()
    expect(
      await screen.findByRole('button', {
        name: 'Reactivate 123 Main St for outreach',
      }),
    ).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Property address'), {
      target: { value: '456 Other St' },
    })

    expect(
      screen.queryByRole('button', {
        name: 'Reactivate 123 Main St for outreach',
      }),
    ).not.toBeInTheDocument()
  })
})
