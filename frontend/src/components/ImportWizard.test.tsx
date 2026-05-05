import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@/test/testUtils'
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
 * For password fields, we fall back to querySelector since they don't have role="textbox".
 */
function getInput(labelText: string): HTMLInputElement {
  // MUI TextField renders a <label> with the given text, linked to the <input> via htmlFor
  const label = screen.getByText(labelText, { selector: 'label' })
  const inputId = label.getAttribute('for')
  if (inputId) {
    const input = document.getElementById(inputId)
    if (input) return input as HTMLInputElement
  }
  // Fallback: find by role
  return screen.getByRole('textbox', { name: labelText }) as HTMLInputElement
}

/** Helper: type into auth fields and submit the form */
async function fillAndSubmitAuth() {
  vi.mocked(leadService.authenticateGoogleSheets).mockResolvedValue({
    message: 'ok',
    user_id: 'user1',
  })

  await user.type(getInput('Client ID'), 'test-id')
  await user.type(getInput('Client Secret'), 'test-secret')

  // Submit the form directly (bypasses disabled button CSS issue)
  const form = screen.getByLabelText('Google OAuth2 authentication form')
  fireEvent.submit(form)

  await waitFor(() => expect(getInput('Spreadsheet ID')).toBeInTheDocument())
}

describe('ImportWizard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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

  it('shows auth form on step 0 with required fields', () => {
    render(<ImportWizard />)
    expect(getInput('Client ID')).toBeInTheDocument()
    expect(getInput('Client Secret')).toBeInTheDocument()
    expect(screen.getByLabelText('Authenticate with Google')).toBeDisabled()
  })

  it('calls authenticateGoogleSheets and advances to step 1 on success', async () => {
    vi.mocked(leadService.authenticateGoogleSheets).mockResolvedValue({
      message: 'Authenticated',
      user_id: 'user1',
    })

    render(<ImportWizard />)

    await user.type(getInput('Client ID'), 'my-client-id')
    await user.type(getInput('Client Secret'), 'my-secret')
    fireEvent.submit(screen.getByLabelText('Google OAuth2 authentication form'))

    await waitFor(() => {
      expect(getInput('Spreadsheet ID')).toBeInTheDocument()
    })
    expect(leadService.authenticateGoogleSheets).toHaveBeenCalledWith({
      client_id: 'my-client-id',
      client_secret: 'my-secret',
    })
  })

  it('shows error on auth failure', async () => {
    vi.mocked(leadService.authenticateGoogleSheets).mockRejectedValue(
      new Error('Invalid credentials'),
    )

    render(<ImportWizard />)

    await user.type(getInput('Client ID'), 'bad-id')
    await user.type(getInput('Client Secret'), 'bad-secret')
    fireEvent.submit(screen.getByLabelText('Google OAuth2 authentication form'))

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
    await fillAndSubmitAuth()

    await user.type(getInput('Spreadsheet ID'), 'sheet123')
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
    await fillAndSubmitAuth()

    await user.type(getInput('Spreadsheet ID'), 'sheet123')
    await user.click(screen.getByLabelText('Load sheets'))
    await waitFor(() => expect(screen.getByText('Leads')).toBeInTheDocument())

    await user.click(screen.getByLabelText('Select sheet Leads'))

    await waitFor(() => {
      expect(screen.getByText('Address')).toBeInTheDocument()
      expect(screen.getByText('Owner')).toBeInTheDocument()
      expect(screen.getByLabelText('Save mapping and continue')).toBeInTheDocument()
    })
  })

  it('disables save button when required fields are not mapped', async () => {
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
    await fillAndSubmitAuth()

    await user.type(getInput('Spreadsheet ID'), 'sheet123')
    await user.click(screen.getByLabelText('Load sheets'))
    await waitFor(() => expect(screen.getByText('Leads')).toBeInTheDocument())
    await user.click(screen.getByLabelText('Select sheet Leads'))

    await waitFor(() => {
      expect(screen.getByLabelText('Save mapping and continue')).toBeDisabled()
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
    await fillAndSubmitAuth()

    // Step 1 → load sheets
    await user.type(getInput('Spreadsheet ID'), 'sheet123')
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
