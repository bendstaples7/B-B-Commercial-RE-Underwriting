import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme } from '@mui/material'
import { useState } from 'react'
import { QuickAddPage } from './QuickAddPage'

const { mapsState } = vi.hoisted(() => ({
  mapsState: { availability: 'ready' as 'loading' | 'ready' | 'unavailable' },
}))

vi.mock('@/context/GoogleMapsContext', () => ({
  useGoogleMapsLoaded: () => mapsState.availability === 'ready',
  useGoogleMapsAvailability: () => mapsState.availability,
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

vi.mock('@/services/contactApi', () => ({
  contactService: {
    createContact: vi.fn(),
    linkContactToProperty: vi.fn(),
    getPropertyContacts: vi.fn(),
    deleteContact: vi.fn(),
  },
}))

const { navigateMock } = vi.hoisted(() => ({
  navigateMock: vi.fn(),
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

import { leadService } from '@/services/leadApi'
import { commandCenterService } from '@/services/api'
import openLetterService from '@/services/openLetterApi'
import { contactService } from '@/services/contactApi'

const theme = createTheme()

function renderPage(initialEntries: string[] = ['/quick-add']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <ThemeProvider theme={theme}>
          <QuickAddPage />
        </ThemeProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mapsState.availability = 'ready'
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
  vi.mocked(leadService.quickAdd).mockResolvedValue({
    created: true,
    lead_id: 99,
    hubspot_push_status: 'disabled',
  } as any)
})

describe('QuickAddPage fullscreen dialog', () => {
  it('renders a fullscreen dialog with a single Quick Add title and close control', () => {
    renderPage()

    expect(screen.getByTestId('quick-add-dialog')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Quick Add' })).toBeInTheDocument()
    expect(screen.getByTestId('quick-add-close')).toBeInTheDocument()
    expect(screen.getByLabelText('Property address')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument()
  })

  it('does not warn about a missing Maps key while the script is still loading', () => {
    mapsState.availability = 'loading'
    renderPage()
    expect(screen.queryByTestId('quick-add-maps-unavailable')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Property address')).toBeInTheDocument()
  })

  it('warns when the Maps API key is unavailable', () => {
    mapsState.availability = 'unavailable'
    renderPage()
    expect(screen.getByTestId('quick-add-maps-unavailable')).toHaveTextContent(
      'Maps API key not loaded',
    )
  })

  it('navigates back when the close button is clicked with same-origin referrer', () => {
    Object.defineProperty(document, 'referrer', {
      configurable: true,
      value: 'http://localhost:3000/kanban',
    })
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, origin: 'http://localhost:3000' },
    })
    Object.defineProperty(window.history, 'length', { configurable: true, value: 3 })
    renderPage()

    fireEvent.click(screen.getByTestId('quick-add-close'))

    expect(navigateMock).toHaveBeenCalledWith(-1)
  })

  it('falls back to kanban when referrer is missing', () => {
    Object.defineProperty(document, 'referrer', {
      configurable: true,
      value: '',
    })
    renderPage()

    fireEvent.click(screen.getByTestId('quick-add-close'))

    expect(navigateMock).toHaveBeenCalledWith('/kanban')
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

  it('preserves the full manual address on submit', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    renderPage()

    fireEvent.change(screen.getByLabelText('Property address'), {
      target: { value: '123 Main St, Chicago, IL 60601' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))

    await waitFor(() => {
      expect(leadService.quickAdd).toHaveBeenCalledWith(
        expect.objectContaining({
          property_street: '123 Main St, Chicago, IL 60601',
          property_city: null,
          property_state: null,
          property_zip: null,
          lead_status: 'skip_trace',
        }),
      )
    })
  })

  it('saves a new property in the selected pipeline status', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    renderPage()

    fireEvent.change(screen.getByLabelText('Property address'), {
      target: { value: '88 Status Ave' },
    })
    fireEvent.mouseDown(screen.getByLabelText('Pipeline status'))
    fireEvent.click(screen.getByRole('option', { name: 'Negotiating Remote' }))

    expect(screen.getByRole('button', { name: 'Save as Negotiating Remote' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save as Negotiating Remote' }))

    await waitFor(() => {
      expect(leadService.quickAdd).toHaveBeenCalledWith(
        expect.objectContaining({
          property_street: '88 Status Ave',
          lead_status: 'negotiating_remote',
        }),
      )
    })
  })

  it('links every person on the same form and does not offer a lead tab', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    vi.mocked(contactService.createContact)
      .mockResolvedValueOnce({ id: 11 } as never)
      .mockResolvedValueOnce({ id: 12 } as never)
    vi.mocked(contactService.linkContactToProperty).mockResolvedValue({} as never)
    renderPage()

    expect(screen.getByRole('heading', { name: 'Quick Add' })).toBeInTheDocument()
    expect(screen.getByLabelText('Source')).toBeInTheDocument()
    expect(screen.getByLabelText('Why are you adding this')).toBeInTheDocument()
    expect(screen.getByLabelText('Date identified')).toBeInTheDocument()
    expect(screen.getByLabelText('Notes')).toBeInTheDocument()
    expect(screen.getByText('Priority')).toBeInTheDocument()
    expect(screen.getByLabelText('Pipeline status')).toBeInTheDocument()
    expect(screen.queryByTestId('quick-add-kind')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Add lead' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.change(screen.getByLabelText('First name 1'), { target: { value: 'Ada' } })
    fireEvent.change(screen.getByLabelText('Last name 1'), { target: { value: 'Lovelace' } })
    fireEvent.change(screen.getByLabelText('Phone 1'), { target: { value: '312-555-0100' } })
    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.change(screen.getByLabelText('First name 2'), { target: { value: 'Grace' } })
    fireEvent.change(screen.getByLabelText('Email 2'), { target: { value: 'grace@example.com' } })
    fireEvent.change(screen.getByLabelText('Why are you adding this'), {
      target: { value: 'Broker sent the address' },
    })
    fireEvent.change(screen.getByLabelText('Notes'), {
      target: { value: 'Call after 5' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))

    await waitFor(() => {
      expect(leadService.quickAdd).toHaveBeenCalledWith(
        expect.objectContaining({
          capture_kind: 'lead',
          deal_source: 'Driving For Dollars',
          context: 'Broker sent the address',
          note: 'Call after 5',
        }),
      )
    })
    expect(contactService.createContact).toHaveBeenCalledTimes(2)
    expect(contactService.createContact).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        first_name: 'Ada',
        last_name: 'Lovelace',
        phones: [{ value: '312-555-0100', label: 'mobile' }],
        source: 'Driving For Dollars',
        capture_context: 'Broker sent the address',
      }),
    )
    expect(contactService.linkContactToProperty).toHaveBeenNthCalledWith(
      1,
      99,
      expect.objectContaining({ contact_id: 11, is_primary: true }),
    )
    expect(contactService.linkContactToProperty).toHaveBeenNthCalledWith(
      2,
      99,
      expect.objectContaining({ contact_id: 12, is_primary: false }),
    )
    expect(contactService.getPropertyContacts).not.toHaveBeenCalled()
  })

  it('does not mark a new person primary when the property already has one', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    vi.mocked(leadService.quickAdd).mockResolvedValue({
      created: false,
      lead_id: 99,
      hubspot_push_status: 'disabled',
    } as never)
    vi.mocked(contactService.getPropertyContacts).mockResolvedValue([
      { id: 4, is_primary: true } as never,
    ])
    vi.mocked(contactService.createContact).mockResolvedValue({ id: 11 } as never)
    vi.mocked(contactService.linkContactToProperty).mockResolvedValue({} as never)
    renderPage()

    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.change(screen.getByLabelText('First name 1'), { target: { value: 'Ada' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))

    await waitFor(() => {
      expect(contactService.linkContactToProperty).toHaveBeenCalledWith(
        99,
        expect.objectContaining({ contact_id: 11, is_primary: false }),
      )
    })
  })

  it('does not guess a primary when existing contacts cannot be loaded', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    vi.mocked(leadService.quickAdd).mockResolvedValue({
      created: false,
      lead_id: 99,
      hubspot_push_status: 'disabled',
    } as never)
    vi.mocked(contactService.getPropertyContacts).mockRejectedValue(new Error('offline'))
    vi.mocked(contactService.createContact).mockResolvedValue({ id: 11 } as never)
    vi.mocked(contactService.linkContactToProperty).mockResolvedValue({} as never)
    renderPage()

    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.change(screen.getByLabelText('First name 1'), { target: { value: 'Ada' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))

    await waitFor(() => {
      expect(contactService.linkContactToProperty).toHaveBeenCalledWith(
        99,
        expect.objectContaining({ contact_id: 11, is_primary: false }),
      )
    })
  })

  it('deletes an unlinked person and makes the next saved person primary', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    vi.mocked(contactService.createContact)
      .mockResolvedValueOnce({ id: 11 } as never)
      .mockResolvedValueOnce({ id: 12 } as never)
    vi.mocked(contactService.linkContactToProperty)
      .mockRejectedValueOnce(new Error('link failed'))
      .mockResolvedValueOnce({} as never)
    vi.mocked(contactService.deleteContact).mockResolvedValue(undefined)
    renderPage()

    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.change(screen.getByLabelText('First name 1'), { target: { value: 'Ada' } })
    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.change(screen.getByLabelText('First name 2'), { target: { value: 'Grace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))

    await waitFor(() => {
      expect(contactService.deleteContact).toHaveBeenCalledWith(11)
    })
    expect(contactService.linkContactToProperty).toHaveBeenLastCalledWith(
      99,
      expect.objectContaining({ contact_id: 12, is_primary: true }),
    )
    expect(await screen.findByText(/link failed/)).toBeInTheDocument()
  })

  it('does not save a person row that has no name', () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    renderPage()
    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))
    expect(screen.getByText(/first or last name/i)).toBeInTheDocument()
    expect(leadService.quickAdd).not.toHaveBeenCalled()
  })

  it('blocks a blank address before calling the api', () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    renderPage()
    fireEvent.change(screen.getByLabelText('Property address'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))
    expect(screen.getByText(/property address is required/i)).toBeInTheDocument()
    expect(leadService.quickAdd).not.toHaveBeenCalled()
    expect(contactService.createContact).not.toHaveBeenCalled()
  })

  it('keeps the property when a person cannot be saved', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    vi.mocked(contactService.createContact).mockRejectedValue(new Error('Invalid source'))
    renderPage()
    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.change(screen.getByLabelText('First name 1'), { target: { value: 'Ada' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))

    expect(await screen.findByText(/Invalid source/)).toBeInTheDocument()
    expect(screen.getByText(/Added to Skip Trace/)).toBeInTheDocument()
    expect(leadService.quickAdd).toHaveBeenCalledTimes(1)
  })

  it('lets you remove a blank person and save the property alone', async () => {
    vi.mocked(leadService.lookupQuickAdd).mockResolvedValue({ matches: [] })
    renderPage()
    fireEvent.click(screen.getByTestId('quick-add-add-person'))
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))
    expect(screen.getByText(/first or last name/i)).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('quick-add-remove-person-0'))
    fireEvent.click(screen.getByRole('button', { name: 'Save to Skip Trace' }))

    await waitFor(() => {
      expect(leadService.quickAdd).toHaveBeenCalledWith(
        expect.objectContaining({ capture_kind: null }),
      )
    })
    expect(contactService.createContact).not.toHaveBeenCalled()
  })
})
