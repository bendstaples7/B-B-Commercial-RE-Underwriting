import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { CondoReviewPage } from './CondoReviewPage'
import { condoFilterService } from '@/services/condoFilterApi'
import type { CondoAnalysisSummary, CondoFilterResultsResponse } from '@/types'

vi.mock('@/services/condoFilterApi', () => ({
  condoFilterService: {
    runAnalysis: vi.fn(),
    getResults: vi.fn(),
    getDetail: vi.fn(),
    applyOverride: vi.fn(),
    exportCsv: vi.fn(),
  },
}))

const mockSummary: CondoAnalysisSummary = {
  total_groups: 10,
  total_properties: 25,
  by_status: {
    likely_condo: 3,
    likely_not_condo: 4,
    partial_condo_possible: 1,
    needs_review: 2,
    unknown: 0,
  },
  by_building_sale: {
    yes: 4,
    no: 3,
    maybe: 1,
    unknown: 2,
  },
}

const mockResultsResponse: CondoFilterResultsResponse = {
  results: [],
  total: 0,
  page: 1,
  per_page: 20,
  pages: 0,
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

describe('CondoReviewPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(condoFilterService.getResults).mockResolvedValue(mockResultsResponse)
  })

  it('renders with "Run Analysis" button', async () => {
    render(<CondoReviewPage />)

    expect(screen.getByRole('button', { name: /run analysis/i })).toBeInTheDocument()
  })

  it('renders with "Export CSV" button', async () => {
    render(<CondoReviewPage />)

    expect(screen.getByRole('button', { name: /export csv/i })).toBeInTheDocument()
  })

  it('renders the page heading', async () => {
    render(<CondoReviewPage />)

    expect(screen.getByText('Condo Filter')).toBeInTheDocument()
  })

  it('"Run Analysis" triggers API call and displays results summary', async () => {
    vi.mocked(condoFilterService.runAnalysis).mockResolvedValue(mockSummary)

    render(<CondoReviewPage />)

    const runButton = screen.getByRole('button', { name: /run analysis/i })
    await user.click(runButton)

    await waitFor(() => {
      expect(condoFilterService.runAnalysis).toHaveBeenCalledTimes(1)
    })

    await waitFor(() => {
      expect(
        screen.getByText(/analysis complete: 10 address groups, 25 properties processed/i),
      ).toBeInTheDocument()
    })
  })

  it('"Run Analysis" shows error alert on failure', async () => {
    vi.mocked(condoFilterService.runAnalysis).mockRejectedValue(
      new Error('Analysis failed due to database error'),
    )

    render(<CondoReviewPage />)

    const runButton = screen.getByRole('button', { name: /run analysis/i })
    await user.click(runButton)

    await waitFor(() => {
      expect(screen.getByText('Analysis failed due to database error')).toBeInTheDocument()
    })
  })

  it('CSV export button triggers download', async () => {
    const mockBlob = new Blob(['csv,data'], { type: 'text/csv' })
    vi.mocked(condoFilterService.exportCsv).mockResolvedValue(mockBlob)

    const createObjectURLMock = vi.fn(() => 'blob:http://localhost/fake-url')
    const revokeObjectURLMock = vi.fn()
    global.URL.createObjectURL = createObjectURLMock
    global.URL.revokeObjectURL = revokeObjectURLMock

    const appendChildSpy = vi.spyOn(document.body, 'appendChild')
    const removeChildSpy = vi.spyOn(document.body, 'removeChild')

    render(<CondoReviewPage />)

    const exportButton = screen.getByRole('button', { name: /export csv/i })
    await user.click(exportButton)

    await waitFor(() => {
      expect(condoFilterService.exportCsv).toHaveBeenCalledTimes(1)
    })

    await waitFor(() => {
      expect(createObjectURLMock).toHaveBeenCalledWith(mockBlob)
    })

    expect(appendChildSpy).toHaveBeenCalled()
    expect(removeChildSpy).toHaveBeenCalled()
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:http://localhost/fake-url')

    appendChildSpy.mockRestore()
    removeChildSpy.mockRestore()
  })
})
