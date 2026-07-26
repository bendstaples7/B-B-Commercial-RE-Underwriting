import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import openLetterService from '@/services/openLetterApi'
import { OpenLetterSetupPanel } from './OpenLetterSetupPanel'

vi.mock('@/services/openLetterApi', () => ({
  default: {
    getConfig: vi.fn(),
    listProducts: vi.fn(),
    listTemplates: vi.fn(),
    getTemplateStyle: vi.fn(),
    saveConfig: vi.fn(),
  },
}))

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OpenLetterSetupPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('OpenLetterSetupPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(openLetterService.getConfig).mockResolvedValue({
      configured: true,
      use_demo_api: false,
      default_product_id: 11,
      default_template_id: 22,
      default_template_name: 'Standard',
      batch_minimum: 50,
      allow_send_below_minimum: false,
      estimated_cost_per_piece: 1.25,
      estimated_cost_source_sent_at: '2026-07-12T15:00:00Z',
      return_address: null,
      creative_presets: [],
    })
    vi.mocked(openLetterService.listProducts).mockResolvedValue({
      data: [
        {
          id: 11,
          name: 'Personal Letters',
          productType: 'Personal letters',
          deliveryType: 'First Class',
          postageType: 'Live',
        },
      ],
    })
    vi.mocked(openLetterService.listTemplates).mockResolvedValue({
      data: [{ id: 22, title: 'Standard' }],
    })
    vi.mocked(openLetterService.saveConfig).mockResolvedValue({
      configured: true,
      estimated_cost_per_piece: 1.25,
      estimated_cost_source_sent_at: '2026-07-12T15:00:00Z',
    })
  })

  it('saves mail settings without a manual estimated $/piece field', async () => {
    const user = userEvent.setup()
    renderPanel()

    expect(screen.queryByLabelText(/Estimated \$\/piece/i)).not.toBeInTheDocument()
    expect(
      await screen.findByText(/based on mailer cost from the batch sent on/i),
    ).toBeInTheDocument()

    await user.click(await screen.findByRole('button', { name: 'Save mail settings' }))

    await waitFor(() => {
      expect(openLetterService.saveConfig).toHaveBeenCalled()
    })
    const payload = vi.mocked(openLetterService.saveConfig).mock.calls[0][0]
    expect(payload).not.toHaveProperty('estimated_cost_per_piece')
    expect(await screen.findByText('Mail settings saved.')).toBeInTheDocument()
  })

  it('explains that estimates appear after the first sent batch when cost is unknown', async () => {
    vi.mocked(openLetterService.getConfig).mockResolvedValue({
      configured: true,
      use_demo_api: false,
      default_product_id: 11,
      default_template_id: 22,
      default_template_name: 'Standard',
      batch_minimum: 50,
      allow_send_below_minimum: false,
      estimated_cost_per_piece: null,
      return_address: null,
      creative_presets: [],
    })

    renderPanel()

    expect(
      await screen.findByText(/Estimated totals on Ready to Mail will appear after your first batch/i),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText(/Estimated \$\/piece/i)).not.toBeInTheDocument()
  })
})
