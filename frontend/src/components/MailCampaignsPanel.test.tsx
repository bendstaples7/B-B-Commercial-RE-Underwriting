import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MailCampaignsPanel } from './MailCampaignsPanel'

vi.mock('@/services/openLetterApi', () => ({
  default: {
    listCampaigns: vi.fn(),
    getCampaign: vi.fn(),
    getCampaignGapLeads: vi.fn(),
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

describe('MailCampaignsPanel gap captions', () => {
  beforeEach(() => {
    vi.mocked(openLetterService.listCampaigns).mockResolvedValue({
      campaigns: [
        {
          id: 2,
          status: 'submitted',
          lead_count: 501,
          staged_count: 514,
          submitted_count: 501,
          invalid_at_submit_count: 13,
          submit_drop_summary: { 'No owner mailing street address': 11 },
          scan_stats: { scanned: 0, not_scanned: 461 },
          olc_omitted_count: 40,
          creative: { sender_display_name: 'Bessy Tam' },
          response_count: 0,
          created_by: 'u1',
        },
      ],
      creative_rollup: [],
      total: 1,
    } as never)
    vi.mocked(openLetterService.getCampaignGapLeads).mockResolvedValue({
      kind: 'invalid_local',
      total: 1,
      leads: [
        {
          lead_id: 4324,
          owner_name: 'Test Owner',
          property_street: '1104 W Wellington',
          mailing_address: null,
          reason: 'No owner mailing street address',
          disposition: 'invalid_local',
          resolution: 'Skip Trace',
        },
      ],
    })
  })

  it('opens invalid gap dialog from N invalid caption (first-paint settle)', async () => {
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaign-invalid-link-2')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('mail-campaign-invalid-link-2'))
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaign-gap-leads-dialog')).toBeInTheDocument()
    })
    expect(screen.getByRole('heading', { name: /Invalid addresses — batch #2/i })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaign-gap-leads-table')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('mail-campaign-gap-leads-loading')).not.toBeInTheDocument()
    expect(screen.getByText('Test Owner')).toBeInTheDocument()
    expect(screen.getByText('Where now')).toBeInTheDocument()
    expect(screen.getByTestId('mail-gap-lead-4324')).toHaveTextContent('Skip Trace')
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await user.click(screen.getByTestId('mail-campaign-gap-copy-excel'))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalled()
    })
    expect(writeText.mock.calls[0][0]).toContain('Lead ID\tOwner')
    expect(writeText.mock.calls[0][0]).toContain('4324\tTest Owner')
    expect(openLetterService.getCampaignGapLeads).toHaveBeenCalledWith(
      2,
      'invalid_local',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('opens OLC omitted dialog from omit caption (first-paint settle)', async () => {
    vi.mocked(openLetterService.getCampaignGapLeads).mockResolvedValue({
      kind: 'olc_omitted',
      total: 1,
      leads: [
        {
          lead_id: 903,
          owner_name: 'Omitted Owner',
          property_street: '6439 N Damen Ave',
          mailing_address: '6429 N Damen Ave, Chicago, IL 60645',
          reason: 'Not on OLC order',
          disposition: 'requeued',
          omit_count: 1,
          resolution: 'Ready to Mail',
        },
      ],
    })
    const user = userEvent.setup()
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaign-olc-omit-link-2')).toBeInTheDocument()
    })
    expect(screen.getByTestId('mail-campaign-olc-omit-link-2')).toHaveTextContent('40 not on OLC')
    await user.click(screen.getByTestId('mail-campaign-olc-omit-link-2'))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Not on OLC order — batch #2/i })).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaign-gap-leads-table')).toBeInTheDocument()
    })
    expect(screen.getByText('Omitted Owner')).toBeInTheDocument()
    expect(screen.getByTestId('mail-gap-lead-903')).toHaveTextContent('Ready to Mail')
    expect(openLetterService.getCampaignGapLeads).toHaveBeenCalledWith(
      2,
      'olc_omitted',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })
})
