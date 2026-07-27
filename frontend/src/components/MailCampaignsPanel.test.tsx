import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MailCampaignsPanel } from './MailCampaignsPanel'

vi.mock('@/services/openLetterApi', () => ({
  default: {
    listCampaigns: vi.fn(),
    getCampaign: vi.fn(),
    cancelCampaign: vi.fn(),
  },
}))

import openLetterService from '@/services/openLetterApi'

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MailCampaignsPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MailCampaignsPanel typeface / density', () => {
  beforeEach(() => {
    vi.mocked(openLetterService.listCampaigns).mockResolvedValue({
      campaigns: [
        {
          id: 1,
          status: 'mailed',
          lead_count: 10,
          submitted_count: 10,
          creative: {
            sender_display_name: 'Bessy Tam',
            envelope_color: 'Blue',
            font_color: '#25408F',
            include_email: true,
            include_website: false,
          },
          scan_rate: 0.1,
          response_rate: 0.02,
          created_by: 'u1',
        },
      ],
      creative_rollup: [
        {
          sender_display_name: 'Bessy Tam',
          envelope_color: 'Blue',
          font_color: '#25408F',
          include_email: true,
          include_website: false,
          campaign_count: 1,
          lead_count: 10,
          response_count: 0,
          scan_rate: 0.1,
          response_rate: 0,
        },
      ],
      total: 1,
      page: 1,
      per_page: 100,
    } as never)
  })

  it('settles with Ink headers and no Font / typeface labels', async () => {
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaigns-table')).toBeInTheDocument()
    })
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByText('Go to queues')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ready to Mail' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Skip Trace' })).toBeInTheDocument()
    expect(screen.getByText('Mailer campaigns')).toBeInTheDocument()
    expect(screen.getAllByText('Ink').length).toBeGreaterThan(0)
    expect(screen.queryByText('Font')).not.toBeInTheDocument()
    expect(screen.queryByText('Scan rate')).not.toBeInTheDocument()
    expect(screen.queryByText(/QR open proxy/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Waiting for the Sunrise/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Internal Connect typeface/i)).not.toBeInTheDocument()
    expect(screen.getAllByText('#25408F').length).toBeGreaterThan(0)
  })
})
