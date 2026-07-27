import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { MarketingHub } from './MarketingHub'

vi.mock('./OpenLetterSetupPanel', () => ({
  OpenLetterSetupPanel: () => <div data-testid="open-letter-setup">Setup</div>,
}))

vi.mock('./MailCampaignsPanel', () => ({
  MailCampaignsPanel: () => <div data-testid="mail-campaigns-panel">Campaigns</div>,
}))

function renderHub(mode?: 'setup' | 'batches') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MarketingHub mode={mode} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MarketingHub', () => {
  it('renders Direct Mail Setup with one primary title', () => {
    renderHub('setup')
    expect(screen.getByTestId('direct-mail-setup-page')).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { name: 'Direct Mail Setup', level: 1 })).toHaveLength(1)
    expect(screen.getByTestId('open-letter-setup')).toBeInTheDocument()
  })

  it('renders Mail Batches with one primary title and campaigns panel', () => {
    renderHub('batches')
    expect(screen.getByTestId('mail-batches-page')).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { name: 'Mail Batches', level: 1 })).toHaveLength(1)
    expect(screen.getByTestId('mail-campaigns-panel')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Campaign History' })).not.toBeInTheDocument()
    expect(screen.getByText(/Local development does not include production sends/i)).toBeInTheDocument()
  })
})
