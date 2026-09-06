import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MotivationSignalsPanel } from './MotivationSignalsPanel'
import type { PropertyDetail } from '@/types'

const addFinding = vi.fn()
const removeFinding = vi.fn()
const getFindingCatalog = vi.fn()

vi.mock('@/services/leadApi', () => ({
  leadService: {
    getFindingCatalog: (...args: unknown[]) => getFindingCatalog(...args),
    addFinding: (...args: unknown[]) => addFinding(...args),
    removeFinding: (...args: unknown[]) => removeFinding(...args),
  },
}))

function renderPanel(lead: PropertyDetail) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MotivationSignalsPanel lead={lead} leadId={lead.id} score={null} />
    </QueryClientProvider>,
  )
}

describe('MotivationSignalsPanel findings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getFindingCatalog.mockResolvedValue({
      findings: [
        {
          finding_key: 'OWNER_SELLING_FSBO',
          label: 'Owner selling FSBO',
          severity: 'high',
          description: 'Confirmed FSBO',
          points: 12,
        },
      ],
      lead_category: 'residential',
    })
    addFinding.mockResolvedValue({
      finding: {
        id: 99,
        signal_type: 'OWNER_SELLING_FSBO',
        label: 'Owner selling FSBO',
        severity: 'high',
        points: 12,
        source: 'analyst',
        is_active: true,
        removable: true,
      },
      motivation_score: 12,
      lead_score: 55,
    })
    removeFinding.mockResolvedValue({ removed: true, signal_id: 99 })
  })

  it('renders add-finding controls and posts FSBO', async () => {
    renderPanel({
      id: 2062,
      property_street: '123 Test',
      motivation_score: 0,
      motivation_signals: [],
      motivation_signal_summary: [],
      enrichment_records: [],
      marketing_lists: [],
      analysis_session: null,
      contacts: [],
    } as unknown as PropertyDetail)

    expect(await screen.findByTestId('add-finding-form')).toBeInTheDocument()
    const addBtn = await screen.findByTestId('add-finding-button')
    await waitFor(() => expect(addBtn).toBeEnabled())
    fireEvent.click(addBtn)
    await waitFor(() => {
      expect(addFinding).toHaveBeenCalledWith(2062, 'OWNER_SELLING_FSBO', null)
    })
  })

  it('surfaces catalog loading errors and offers retry', async () => {
    getFindingCatalog
      .mockRejectedValueOnce(new Error('Catalog unavailable'))
      .mockResolvedValueOnce({
        findings: [
          {
            finding_key: 'OWNER_SELLING_FSBO',
            label: 'Owner selling FSBO',
            severity: 'high',
            description: 'Confirmed FSBO',
            points: 12,
          },
        ],
        lead_category: 'residential',
      })

    renderPanel({
      id: 2062,
      property_street: '123 Test',
      motivation_score: 0,
      motivation_signals: [],
      motivation_signal_summary: [],
      enrichment_records: [],
      marketing_lists: [],
      analysis_session: null,
      contacts: [],
    } as unknown as PropertyDetail)

    expect(await screen.findByText('Catalog unavailable')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => {
      expect(getFindingCatalog).toHaveBeenCalledTimes(2)
    })
    expect(await screen.findByTestId('finding-key-select')).toBeInTheDocument()
  })

  it('shows remove control for analyst findings', async () => {
    renderPanel({
      id: 2062,
      property_street: '123 Test',
      motivation_score: 12,
      motivation_signals: [
        {
          id: 99,
          signal_type: 'OWNER_SELLING_FSBO',
          label: 'Owner selling FSBO',
          severity: 'high',
          points: 12,
          source: 'analyst',
          is_active: true,
          removable: true,
        },
      ],
      motivation_signal_summary: [],
      enrichment_records: [],
      marketing_lists: [],
      analysis_session: null,
      contacts: [],
    } as unknown as PropertyDetail)

    const removeBtn = await screen.findByTestId('remove-finding-99')
    fireEvent.click(removeBtn)
    await waitFor(() => {
      expect(removeFinding).toHaveBeenCalledWith(2062, 99)
    })
  })
})
