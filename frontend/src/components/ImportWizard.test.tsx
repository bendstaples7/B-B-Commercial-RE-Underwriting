import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { ImportWizard } from './ImportWizard'
import { leadService } from '@/services/leadApi'
import { ImportJobStatus } from '@/types'
import type { SheetInfo, FieldMapping, ImportJob } from '@/types'

vi.mock('@/services/leadApi', () => ({
  leadService: {
    authenticateGoogleSheets: vi.fn(),
    listSheets: vi.fn(),
    readHeaders: vi.fn(),
    saveFieldMapping: vi.fn(),
    startImport: vi.fn(),
    getImportJob: vi.fn(),
  },
}))

const mockSheets: SheetInfo[] = [
  { sheet_id: 0, title: 'Leads', row_count: 100, column_count: 5 },
  { sheet_id: 1, title: 'Contacts', row_count: 50, column_count: 3 },
]

const mockHeaders = ['Address', 'Owner', 'Type', 'Beds', 'Baths']

const mockAutoMapping: Record<string, string> = {
  Address: 'property_street',
  Owner: 'owner_first_name',
}

const mockFieldMapping: FieldMapping = {
  id: 1,
  user_id: 'user1',
  spreadsheet_id: 'sheet123',
  sheet_name: 'Leads',
  mapping: mockAutoMapping,
  created_at: null,
  updated_at: null,
}

const mockImportJobCompleted: ImportJob = {
  id: 10,
  user_id: 'user1',
  spreadsheet_id: 'sheet123',
  sheet_name: 'Leads',
  field_mapping_id: 1,
  status: ImportJobStatus.COMPLETED,
  total_rows: 100,
  rows_processed: 100,
  rows_imported: 95,
  rows_skipped: 5,
  completed_at: '2024-01-01T00:05:00Z',
  error_log: [{ row: 3, error: 'Missing address' }],
  started_at: '2024-01-01T00:00:00Z',
  created_at: '2024-01-01T00:00:00Z',
}

const user = userEvent.setup({ pointerEventsCheck: 0 })

/**
 * Helper: get the actual <input> inside an MUI TextField by its visible label text.
 * MUI associates <label> with <input> via htmlFor/id.
 */
function getInput(labelText: string): HTMLInputElement {
  const label = screen.getByText(labelText, { selector: 'label' })
  const inputId = label.getAttribute('for')
  if (inputId) {
    const input = document.getElementById(inputId)
    if (input) return input as HTMLInputElement
  }
  // Fallback: find by role
  return screen.getByRole('textbox', { name: labelText }) as HTMLInputElement
}

const SPREADSHEET_LABEL = 'Google Sheets URL or Spreadsheet ID'

/**
 * Drive the wizard from step 0 to step 1 by mocking the auth handler to return
 * a result without `auth_url` (the "already authenticated" branch) and clicking
 * the Connect button.
 */
async function advanceToSheetStep() {
  vi.mocked(leadService.authenticateGoogleSheets).mockResolvedValue({
    message: 'ok',
    user_id: 'user1',
  })
  await user.click(screen.getByLabelText('Connect to Google Sheets'))
  await waitFor(() => expect(getInput(SPREADSHEET_LABEL)).toBeInTheDocument())
}

describe('ImportWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // The wizard reads `google_authenticated` from localStorage on mount.
    // Clear it so each test starts on step 0.
    localStorage.clear()
  })

  it('renders the wizard heading and stepper labels', () => {
    render(<ImportWizard />)
    expect(screen.getByText('Import from Google Sheets')).toBeInTheDocument()
    const stepper = screen.getByLabelText('Import wizard steps')
    expect(within(stepper).getByText('Authenticate')).toBeInTheDocument()
    expect(within(stepper).getByText('Select Sheet')).toBeInTheDocument()
    expect(within(stepper).getByText('Map Fields')).toBeInTheDocument()
    expect(within(stepper).getByText('Import')).toBeInTheDocument()
  })

  it('shows the Connect to Google Sheets button on step 0', () => {
    render(<ImportWizard />)
    expect(
      screen.getByText(
        'Connect your Google account to import leads from Google Sheets.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Connect to Google Sheets')).toBeEnabled()
  })

  it('calls authenticateGoogleSheets with redirect_uri and advances to step 1 when already authenticated', async () => {
    vi.mocked(leadService.authenticateGoogleSheets).mockResolvedValue({
      message: 'Authenticated',
      user_id: 'user1',
    })

    render(<ImportWizard />)
    await user.click(screen.getByLabelText('Connect to Google Sheets'))

    await waitFor(() => {
      expect(getInput(SPREADSHEET_LABEL)).toBeInTheDocument()
    })
    expect(leadService.authenticateGoogleSheets).toHaveBeenCalledWith({
      redirect_uri: expect.stringContaining('/import/callback'),
    })
  })

  it('shows error on auth failure', async () => {
    vi.mocked(leadService.authenticateGoogleSheets).mockRejectedValue(
      new Error('Invalid credentials'),
    )

    render(<ImportWizard />)
    await user.click(screen.getByLabelText('Connect to Google Sheets'))

    await waitFor(() => {
      expect(screen.getByText('Invalid credentials')).toBeInTheDocument()
    })
  })

  it('calls onCancel when cancel button is clicked', async () => {
    const onCancel = vi.fn()
    render(<ImportWizard onCancel={onCancel} />)
    await user.click(screen.getByLabelText('Cancel import'))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('loads and displays sheets on step 1', async () => {
    vi.mocked(leadService.listSheets).mockResolvedValue({
      spreadsheet_id: 'sheet123',
      sheets: mockSheets,
    })

    render(<ImportWizard />)
    await advanceToSheetStep()

    await user.type(getInput(SPREADSHEET_LABEL), 'sheet123')
    await user.click(screen.getByLabelText('Load sheets'))

    await waitFor(() => {
      expect(screen.getByText('Leads')).toBeInTheDocument()
      expect(screen.getByText('Contacts')).toBeInTheDocument()
      expect(screen.getByText('100 rows, 5 columns')).toBeInTheDocument()
    })
  })

  it('advances to field mapping step after selecting a sheet', async () => {
    vi.mocked(leadService.listSheets).mockResolvedValue({
      spreadsheet_id: 'sheet123',
      sheets: mockSheets,
    })
    vi.mocked(leadService.readHeaders).mockResolvedValue({
      spreadsheet_id: 'sheet123',
      sheet_name: 'Leads',
      headers: mockHeaders,
      auto_mapping: mockAutoMapping,
    })

    render(<ImportWizard />)
    await advanceToSheetStep()

    await user.type(getInput(SPREADSHEET_LABEL), 'sheet123')
    await user.click(screen.getByLabelText('Load sheets'))
    await waitFor(() => expect(screen.getByText('Leads')).toBeInTheDocument())

    await user.click(screen.getByLabelText('Select sheet Leads'))

    await waitFor(() => {
      expect(screen.getByText('Address')).toBeInTheDocument()
      expect(screen.getByText('Owner')).toBeInTheDocument()
      expect(screen.getByLabelText('Save mapping and continue')).toBeInTheDocument()
    })
  })

  it('enables save button once a sheet is selected (no required fields configured)', async () => {
    // The current DATABASE_FIELDS list has no entries marked required, so the
    // save button is enabled as soon as headers are loaded. This replaces the
    // previous "disables save button when required fields are not mapped"
    // test, which relied on a required-field check that no longer exists.
    vi.mocked(leadService.listSheets).mockResolvedValue({
      spreadsheet_id: 'sheet123',
      sheets: mockSheets,
    })
    vi.mocked(leadService.readHeaders).mockResolvedValue({
      spreadsheet_id: 'sheet123',
      sheet_name: 'Leads',
      headers: mockHeaders,
      auto_mapping: {},
    })

    render(<ImportWizard />)
    await advanceToSheetStep()

    await user.type(getInput(SPREADSHEET_LABEL), 'sheet123')
    await user.click(screen.getByLabelText('Load sheets'))
    await waitFor(() => expect(screen.getByText('Leads')).toBeInTheDocument())
    await user.click(screen.getByLabelText('Select sheet Leads'))

    await waitFor(() => {
      expect(screen.getByLabelText('Save mapping and continue')).toBeEnabled()
    })
  })

  it('shows import completion summary with row counts', async () => {
    vi.mocked(leadService.listSheets).mockResolvedValue({
      spreadsheet_id: 'sheet123',
      sheets: mockSheets,
    })
    vi.mocked(leadService.readHeaders).mockResolvedValue({
      spreadsheet_id: 'sheet123',
      sheet_name: 'Leads',
      headers: mockHeaders,
      auto_mapping: mockAutoMapping,
    })
    vi.mocked(leadService.saveFieldMapping).mockResolvedValue(mockFieldMapping)
    vi.mocked(leadService.startImport).mockResolvedValue(mockImportJobCompleted)
    vi.mocked(leadService.getImportJob).mockResolvedValue(mockImportJobCompleted)

    const onComplete = vi.fn()
    render(<ImportWizard onComplete={onComplete} />)

    // Step 0 → 1
    await advanceToSheetStep()

    // Step 1 → load sheets
    await user.type(getInput(SPREADSHEET_LABEL), 'sheet123')
    await user.click(screen.getByLabelText('Load sheets'))
    await waitFor(() => expect(screen.getByText('Leads')).toBeInTheDocument())

    // Select sheet → step 2
    await user.click(screen.getByLabelText('Select sheet Leads'))
    await waitFor(() => expect(screen.getByLabelText('Save mapping and continue')).toBeEnabled())

    // Step 2 → 3
    await user.click(screen.getByLabelText('Save mapping and continue'))
    await waitFor(() => expect(screen.getByLabelText('Start import')).toBeInTheDocument())

    // Start import
    await user.click(screen.getByLabelText('Start import'))

    // Should show completion summary
    await waitFor(() => {
      expect(screen.getByText('Import completed successfully.')).toBeInTheDocument()
      expect(screen.getByText('100')).toBeInTheDocument()
      expect(screen.getByText('95')).toBeInTheDocument()
      expect(screen.getByText('5')).toBeInTheDocument()
    })

    // Click Done
    await user.click(screen.getByLabelText('Finish import'))
    expect(onComplete).toHaveBeenCalledOnce()
  })
})
