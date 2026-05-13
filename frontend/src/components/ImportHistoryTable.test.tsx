import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { ImportHistoryTable } from './ImportHistoryTable'
import { leadService } from '@/services/leadApi'
import { ImportJobStatus } from '@/types'
import type { ImportJob, ImportJobListResponse } from '@/types'

vi.mock('@/services/leadApi', () => ({
  leadService: {
    listImportJobs: vi.fn(),
    rerunImport: vi.fn(),
  },
}))

const user = userEvent.setup({ pointerEventsCheck: 0 })

function makeJob(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 1,
    user_id: 'user1',
    spreadsheet_id: 'sheet-abc',
    sheet_name: 'Leads',
    field_mapping_id: 1,
    status: ImportJobStatus.COMPLETED,
    total_rows: 100,
    rows_processed: 100,
    rows_imported: 95,
    rows_skipped: 5,
    error_log: [],
    started_at: '2024-06-01T10:00:00Z',
    completed_at: '2024-06-01T10:05:00Z',
    created_at: '2024-06-01T10:00:00Z',
    ...overrides,
  }
}

function makeListResponse(
  jobs: ImportJob[],
  overrides: Partial<ImportJobListResponse> = {},
): ImportJobListResponse {
  return {
    jobs,
    total: jobs.length,
    page: 1,
    per_page: 10,
    pages: 1,
    ...overrides,
  }
}

describe('ImportHistoryTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the heading and fetches import jobs on mount', async () => {
    const jobs = [
      makeJob({ id: 1, sheet_name: 'Leads', status: ImportJobStatus.COMPLETED }),
      makeJob({ id: 2, sheet_name: 'Contacts', status: ImportJobStatus.FAILED }),
    ]
    vi.mocked(leadService.listImportJobs).mockResolvedValue(makeListResponse(jobs))

    render(<ImportHistoryTable />)

    expect(screen.getByText('Import History')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText('Leads')).toBeInTheDocument()
      expect(screen.getByText('Contacts')).toBeInTheDocument()
    })

    expect(leadService.listImportJobs).toHaveBeenCalledWith({
      page: 1,
      per_page: 10,
    })
  })

  it('shows loading spinner while fetching', () => {
    vi.mocked(leadService.listImportJobs).mockReturnValue(new Promise(() => {}))

    render(<ImportHistoryTable />)

    expect(screen.getByLabelText('Loading import history')).toBeInTheDocument()
  })

  it('shows empty state when no jobs exist', async () => {
    vi.mocked(leadService.listImportJobs).mockResolvedValue(makeListResponse([]))

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(
        screen.getByText(/No imports found/),
      ).toBeInTheDocument()
    })
  })

  it('shows error alert when fetch fails', async () => {
    vi.mocked(leadService.listImportJobs).mockRejectedValue(
      new Error('Network error'),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
  })

  it('renders correct status chip colors', async () => {
    const jobs = [
      makeJob({ id: 1, status: ImportJobStatus.PENDING }),
      makeJob({ id: 2, status: ImportJobStatus.IN_PROGRESS }),
      makeJob({ id: 3, status: ImportJobStatus.COMPLETED }),
      makeJob({ id: 4, status: ImportJobStatus.FAILED }),
    ]
    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse(jobs),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      const pendingChip = screen.getByLabelText('Status: pending')
      const inProgressChip = screen.getByLabelText('Status: in_progress')
      const completedChip = screen.getByLabelText('Status: completed')
      const failedChip = screen.getByLabelText('Status: failed')

      // MUI Chip applies color classes — check the chip elements exist with correct labels
      expect(pendingChip).toBeInTheDocument()
      expect(inProgressChip).toBeInTheDocument()
      expect(completedChip).toBeInTheDocument()
      expect(failedChip).toBeInTheDocument()

      // Verify MUI color classes
      expect(pendingChip.closest('.MuiChip-root')).toHaveClass('MuiChip-colorDefault')
      expect(inProgressChip.closest('.MuiChip-root')).toHaveClass('MuiChip-colorInfo')
      expect(completedChip.closest('.MuiChip-root')).toHaveClass('MuiChip-colorSuccess')
      expect(failedChip.closest('.MuiChip-root')).toHaveClass('MuiChip-colorError')
    })
  })

  it('expands a row to show error log when clicking the expand button', async () => {
    const job = makeJob({
      id: 1,
      rows_skipped: 2,
      error_log: [
        { row: 3, error: 'Missing address' },
        { row: 7, error: 'Invalid phone number' },
      ],
    })
    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse([job]),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(screen.getByText('Leads')).toBeInTheDocument()
    })

    // Error log should not be visible initially
    expect(screen.queryByText('Missing address')).not.toBeInTheDocument()

    // Click expand button
    const expandBtn = screen.getByLabelText('Expand error log for job 1')
    await user.click(expandBtn)

    // Error log should now be visible
    await waitFor(() => {
      expect(screen.getByText('Missing address')).toBeInTheDocument()
      expect(screen.getByText('Invalid phone number')).toBeInTheDocument()
      expect(screen.getByText('Error Log (2 errors)')).toBeInTheDocument()
    })

    // Collapse it
    const collapseBtn = screen.getByLabelText('Collapse error log for job 1')
    await user.click(collapseBtn)

    // After collapse animation, content should be removed (unmountOnExit)
    await waitFor(() => {
      expect(screen.queryByText('Missing address')).not.toBeInTheDocument()
    })
  })

  it('does not show expand button for jobs without errors', async () => {
    const job = makeJob({ id: 1, error_log: [] })
    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse([job]),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(screen.getByText('Leads')).toBeInTheDocument()
    })

    expect(
      screen.queryByLabelText('Expand error log for job 1'),
    ).not.toBeInTheDocument()
  })

  it('calls rerunImport and refreshes when re-run button is clicked', async () => {
    const job = makeJob({ id: 5, status: ImportJobStatus.COMPLETED })
    const newJob = makeJob({ id: 6, status: ImportJobStatus.IN_PROGRESS })

    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse([job]),
    )
    vi.mocked(leadService.rerunImport).mockResolvedValue({
      ...newJob,
      original_job_id: 5,
    })

    const onImportStarted = vi.fn()
    render(<ImportHistoryTable onImportStarted={onImportStarted} />)

    await waitFor(() => {
      expect(screen.getByLabelText('Re-run import job 5')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Re-run import job 5'))

    await waitFor(() => {
      expect(leadService.rerunImport).toHaveBeenCalledWith(5)
      expect(onImportStarted).toHaveBeenCalledWith(
        expect.objectContaining({ id: 6, original_job_id: 5 }),
      )
    })

    // Should have refreshed the table
    expect(leadService.listImportJobs).toHaveBeenCalledTimes(2)
  })

  it('does not show re-run button for non-completed jobs', async () => {
    const jobs = [
      makeJob({ id: 1, status: ImportJobStatus.PENDING }),
      makeJob({ id: 2, status: ImportJobStatus.IN_PROGRESS }),
      makeJob({ id: 3, status: ImportJobStatus.FAILED }),
    ]
    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse(jobs),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(screen.getByLabelText('Status: pending')).toBeInTheDocument()
    })

    expect(screen.queryByText('Re-run')).not.toBeInTheDocument()
  })

  it('renders pagination when there are multiple pages', async () => {
    const jobs = [makeJob({ id: 1 })]
    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse(jobs, { total: 25, pages: 3, page: 1 }),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(
        screen.getByLabelText('Import history pagination'),
      ).toBeInTheDocument()
    })

    // Click page 2
    const page2Button = screen.getByLabelText('Go to page 2')
    await user.click(page2Button)

    await waitFor(() => {
      expect(leadService.listImportJobs).toHaveBeenCalledWith({
        page: 2,
        per_page: 10,
      })
    })
  })

  it('does not render pagination for a single page', async () => {
    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse([makeJob()], { total: 5, pages: 1 }),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(screen.getByText('Leads')).toBeInTheDocument()
    })

    expect(
      screen.queryByLabelText('Import history pagination'),
    ).not.toBeInTheDocument()
  })

  it('displays row counts correctly', async () => {
    const job = makeJob({
      id: 1,
      total_rows: 200,
      rows_imported: 180,
      rows_skipped: 20,
    })
    vi.mocked(leadService.listImportJobs).mockResolvedValue(
      makeListResponse([job]),
    )

    render(<ImportHistoryTable />)

    await waitFor(() => {
      expect(screen.getByText('200')).toBeInTheDocument()
      expect(screen.getByText('180')).toBeInTheDocument()
      expect(screen.getByText('20')).toBeInTheDocument()
    })
  })
})
