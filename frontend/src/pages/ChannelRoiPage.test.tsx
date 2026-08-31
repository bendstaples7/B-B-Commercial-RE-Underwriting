import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { ChannelRoiPage } from '@/pages/ChannelRoiPage'

vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u1', email: 'a@b.com', is_admin: true } }),
}))

vi.mock('@/services/channelRoiApi', () => ({
  default: {
    getDashboard: vi.fn(),
    patchSettings: vi.fn(),
    syncFacebook: vi.fn(),
    listFacebookCampaigns: vi.fn(),
  },
  channelRoiService: {
    getDashboard: vi.fn(),
    patchSettings: vi.fn(),
    syncFacebook: vi.fn(),
    listFacebookCampaigns: vi.fn(),
  },
}))

import channelRoiService from '@/services/channelRoiApi'

const dashboard = {
  settings: {
    meta_connected: false,
    meta_ad_account_id: null,
    has_meta_token: false,
    expected_profit_per_deal: null,
    assumed_close_rate: null,
    last_synced_at: null,
    last_sync_error: null,
  },
  projection_knobs_set: false,
  channels: {
    direct_mail: {
      spend: 0,
      responses: 0,
      cost_per_response: null,
      response_rate: null,
      denominator: null,
      denominator_label: 'pieces',
      projected_roi: null,
    },
    facebook: {
      spend: 0,
      responses: 0,
      cost_per_response: null,
      response_rate: null,
      denominator: null,
      denominator_label: 'link_clicks',
      projected_roi: null,
    },
  },
  direct_mail_campaigns: [],
  facebook_campaigns: [],
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ChannelRoiPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ChannelRoiPage first-paint', () => {
  beforeEach(() => {
    vi.mocked(channelRoiService.getDashboard).mockResolvedValue(dashboard as never)
  })

  it('settles with unique Channel ROI title and rollup landmark', async () => {
    renderPage()
    expect(screen.getByTestId('channel-roi-loading')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByTestId('channel-roi-loading')).not.toBeInTheDocument()
    })
    const titles = screen.getAllByRole('heading', { level: 1 })
    expect(titles).toHaveLength(1)
    expect(titles[0]).toHaveTextContent('Channel ROI')
    expect(screen.getByTestId('channel-roi-rollup')).toBeInTheDocument()
    expect(screen.getByText(/Connect Meta ad account/i)).toBeInTheDocument()
  })
})
