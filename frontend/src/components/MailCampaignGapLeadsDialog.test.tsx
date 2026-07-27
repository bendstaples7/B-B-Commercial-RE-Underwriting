import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ComponentProps } from 'react'
import { MailCampaignGapLeadsDialog } from './MailCampaignGapLeadsDialog'
import openLetterService from '@/services/openLetterApi'

vi.mock('@/services/openLetterApi', () => ({
  default: {
    getCampaignGapLeads: vi.fn(),
  },
}))

function renderDialog(
  props: Partial<ComponentProps<typeof MailCampaignGapLeadsDialog>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MailCampaignGapLeadsDialog
          open
          onClose={() => undefined}
          campaignId={2}
          kind="olc_omitted"
          {...props}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MailCampaignGapLeadsDialog', () => {
  beforeEach(() => {
    vi.mocked(openLetterService.getCampaignGapLeads).mockReset()
  })

  it('shows empty omit-cache copy when API returns no leads', async () => {
    vi.mocked(openLetterService.getCampaignGapLeads).mockResolvedValue({
      kind: 'olc_omitted',
      total: 0,
      leads: [],
    })
    renderDialog()
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaign-gap-leads-empty')).toBeInTheDocument()
    })
    expect(screen.getByTestId('mail-campaign-gap-leads-empty')).toHaveTextContent(
      /No cached OLC-omitted list/i,
    )
  })

  it('copies TSV when Copy for Excel is clicked', async () => {
    vi.mocked(openLetterService.getCampaignGapLeads).mockResolvedValue({
      kind: 'olc_omitted',
      total: 1,
      leads: [
        {
          lead_id: 9,
          owner_name: 'Pat',
          property_street: '1 Main',
          mailing_address: '2 Mail',
          reason: 'Not on OLC order',
          resolution: 'Ready to Mail',
          omit_count: 1,
        },
      ],
    })
    const user = userEvent.setup()
    renderDialog()
    await waitFor(() => {
      expect(screen.getByTestId('mail-campaign-gap-leads-table')).toBeInTheDocument()
    })
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    await user.click(screen.getByTestId('mail-campaign-gap-copy-excel'))
    await waitFor(() => {
      expect(writeText).toHaveBeenCalled()
    })
    expect(writeText.mock.calls[0][0]).toContain('Lead ID\tOwner')
    expect(writeText.mock.calls[0][0]).toContain('9\tPat')
  })
})
