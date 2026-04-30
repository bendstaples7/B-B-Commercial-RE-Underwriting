import React, { useState, useCallback, useEffect, useRef } from 'react'
import {
  Box,
  Paper,
  Typography,
  Button,
  Stepper,
  Step,
  StepLabel,
  TextField,
  CircularProgress,
  Alert,
  LinearProgress,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Chip,
} from '@mui/material'
import type { SheetInfo, ImportJob, FieldMapping } from '@/types'
import { ImportJobStatus } from '@/types'
import { leadService } from '@/services/leadApi'

/** Database fields available for mapping. */
const DATABASE_FIELDS: { value: string; label: string; required: boolean }[] = [
  { value: 'property_street', label: 'Property Street', required: false },
  { value: 'property_city', label: 'Property City', required: false },
  { value: 'property_state', label: 'Property State', required: false },
  { value: 'property_zip', label: 'Property Zip', required: false },
  { value: 'owner_first_name', label: 'Owner First Name', required: false },
  { value: 'owner_last_name', label: 'Owner Last Name', required: false },
  { value: 'property_type', label: 'Property Type', required: false },
  { value: 'bedrooms', label: 'Bedrooms', required: false },
  { value: 'bathrooms', label: 'Bathrooms', required: false },
  { value: 'square_footage', label: 'Square Footage', required: false },
  { value: 'lot_size', label: 'Lot Size', required: false },
  { value: 'year_built', label: 'Year Built', required: false },
  { value: 'ownership_type', label: 'Ownership Type', required: false },
  { value: 'acquisition_date', label: 'Acquisition Date', required: false },
  { value: 'phone_1', label: 'Phone 1', required: false },
  { value: 'phone_2', label: 'Phone 2', required: false },
  { value: 'phone_3', label: 'Phone 3', required: false },
  { value: 'email_1', label: 'Email 1', required: false },
  { value: 'email_2', label: 'Email 2', required: false },
  { value: 'mailing_address', label: 'Mailing Address', required: false },
  { value: 'mailing_city', label: 'Mailing City', required: false },
  { value: 'mailing_state', label: 'Mailing State', required: false },
  { value: 'mailing_zip', label: 'Mailing Zip', required: false },
  // Additional property details
  { value: 'units', label: 'Units', required: false },
  { value: 'units_allowed', label: 'Units Allowed', required: false },
  { value: 'zoning', label: 'Zoning', required: false },
  { value: 'county_assessor_pin', label: 'County Assessor PIN', required: false },
  { value: 'tax_bill_2021', label: 'Tax Bill 2021', required: false },
  { value: 'most_recent_sale', label: 'Most Recent Sale', required: false },
  // Second owner
  { value: 'owner_2_first_name', label: 'Owner 2 First Name', required: false },
  { value: 'owner_2_last_name', label: 'Owner 2 Last Name', required: false },
  // Additional contact
  { value: 'phone_4', label: 'Phone 4', required: false },
  { value: 'phone_5', label: 'Phone 5', required: false },
  { value: 'phone_6', label: 'Phone 6', required: false },
  { value: 'phone_7', label: 'Phone 7', required: false },
  { value: 'email_3', label: 'Email 3', required: false },
  { value: 'email_4', label: 'Email 4', required: false },
  { value: 'email_5', label: 'Email 5', required: false },
  { value: 'socials', label: 'Socials', required: false },
  // Additional address & mailing
  { value: 'address_2', label: 'Address 2', required: false },
  { value: 'returned_addresses', label: 'Returned Addresses', required: false },
  { value: 'up_next_to_mail', label: 'Up Next to Mail', required: false },
  { value: 'mailer_history', label: 'Mailer History', required: false },
  // Research tracking
  { value: 'source', label: 'Source', required: false },
  { value: 'date_identified', label: 'Date Identified', required: false },
  { value: 'notes', label: 'Notes', required: false },
  { value: 'needs_skip_trace', label: 'Needs Skip Trace', required: false },
  { value: 'skip_tracer', label: 'Skip Tracer', required: false },
  { value: 'date_skip_traced', label: 'Date Skip Traced', required: false },
  { value: 'date_added_to_hubspot', label: 'Date Added to HubSpot', required: false },
]

const REQUIRED_FIELDS = DATABASE_FIELDS.filter((f) => f.required).map((f) => f.value)

const STEP_LABELS = ['Authenticate', 'Select Sheet', 'Map Fields', 'Import']

/**
 * Extract a Google Sheets spreadsheet ID from a URL or return the input as-is
 * if it already looks like a bare ID.
 *
 * Accepted formats:
 * - https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=0
 * - https://docs.google.com/spreadsheets/d/SPREADSHEET_ID
 * - SPREADSHEET_ID (bare)
 */
function extractSpreadsheetId(input: string): string {
  const trimmed = input.trim()
  const match = trimmed.match(/\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/)
  return match ? match[1] : trimmed
}

/** Props for the ImportWizard component. */
export interface ImportWizardProps {
  /** Called when the import finishes successfully. */
  onComplete?: () => void
  /** Called when the user cancels the wizard. */
  onCancel?: () => void
}

/**
 * Multi-step import wizard: OAuth Auth → Sheet Selection → Field Mapping → Import Progress.
 *
 * Requirements: 1.1, 1.2, 1.3, 2.1, 3.7
 */
export const ImportWizard: React.FC<ImportWizardProps> = ({ onComplete, onCancel }) => {
  // ---- Wizard step ----
  const [activeStep, setActiveStep] = useState(0)

  // ---- Step 0: Auth ----
  const [authLoading, setAuthLoading] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [authenticated, setAuthenticated] = useState(
    () => localStorage.getItem('google_authenticated') === 'true',
  )
  const [userId, setUserId] = useState<string>(
    () => localStorage.getItem('user_id') || '',
  )

  // If returning from OAuth callback, auto-advance to step 1
  useEffect(() => {
    if (authenticated && activeStep === 0) {
      setActiveStep(1)
    }
  }, [authenticated, activeStep])

  // ---- Step 1: Sheet Selection ----
  const [spreadsheetId, setSpreadsheetId] = useState('')
  const [sheets, setSheets] = useState<SheetInfo[]>([])
  const [sheetsLoading, setSheetsLoading] = useState(false)
  const [sheetsError, setSheetsError] = useState<string | null>(null)
  const [selectedSheet, setSelectedSheet] = useState<SheetInfo | null>(null)

  // ---- Step 2: Field Mapping ----
  const [headers, setHeaders] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [mappingLoading, setMappingLoading] = useState(false)
  const [mappingError, setMappingError] = useState<string | null>(null)
  const [savedMapping, setSavedMapping] = useState<FieldMapping | null>(null)

  // ---- Step 3: Import Progress ----
  const [importJob, setImportJob] = useState<ImportJob | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [importStarting, setImportStarting] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
      }
    }
  }, [])

  // ---- Validation helpers ----
  const requiredFieldsMapped = REQUIRED_FIELDS.every((field) =>
    Object.values(mapping).includes(field),
  )

  // ---- Step 0: Authenticate - redirect to Google ----
  const handleAuthenticate = async () => {
    setAuthLoading(true)
    setAuthError(null)
    try {
      const result = await leadService.authenticateGoogleSheets({
        redirect_uri: `${window.location.origin}/import/callback`,
      })
      if (result.auth_url) {
        // Redirect the current window to Google's consent screen
        window.location.href = result.auth_url
      } else {
        // Already authenticated
        setUserId(result.user_id)
        setAuthenticated(true)
        localStorage.setItem('google_authenticated', 'true')
        localStorage.setItem('user_id', result.user_id)
        setActiveStep(1)
      }
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to connect to Google. Please try again.'
      setAuthError(message)
      setAuthLoading(false)
    }
  }

  // ---- Step 1: List sheets ----
  const handleListSheets = async () => {
    if (!spreadsheetId.trim()) return
    setSheetsLoading(true)
    setSheetsError(null)
    setSheets([])
    setSelectedSheet(null)
    try {
      const result = await leadService.listSheets(extractSpreadsheetId(spreadsheetId), userId)
      setSheets(result.sheets)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to load sheets. Check the spreadsheet ID.'
      // If auth expired or token missing, send user back to auth step
      if (message.includes('authenticate') || message.includes('Authentication') || message.includes('OAuth') || message.includes('token')) {
        localStorage.removeItem('google_authenticated')
        setAuthenticated(false)
        setActiveStep(0)
        setAuthError('Your Google session has expired. Please reconnect.')
        return
      }
      setSheetsError(message)
    } finally {
      setSheetsLoading(false)
    }
  }

  const handleSelectSheet = async (sheet: SheetInfo) => {
    setSelectedSheet(sheet)
    setMappingLoading(true)
    setMappingError(null)
    try {
      const result = await leadService.readHeaders(extractSpreadsheetId(spreadsheetId), sheet.title, userId)
      setHeaders(result.headers)
      // Use auto-mapping as the initial mapping
      setMapping(result.auto_mapping || {})
      setActiveStep(2)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to read sheet headers.'
      setMappingError(message)
    } finally {
      setMappingLoading(false)
    }
  }

  // ---- Step 2: Field Mapping ----
  const handleMappingChange = useCallback(
    (header: string, dbField: string) => {
      setMapping((prev) => {
        const next = { ...prev }
        if (dbField === '') {
          delete next[header]
        } else {
          // Remove any other header that was mapped to this db field
          for (const key of Object.keys(next)) {
            if (next[key] === dbField && key !== header) {
              delete next[key]
            }
          }
          next[header] = dbField
        }
        return next
      })
    },
    [],
  )

  const handleSaveMapping = async () => {
    if (!selectedSheet) return
    setMappingLoading(true)
    setMappingError(null)
    try {
      const result = await leadService.saveFieldMapping({
        spreadsheet_id: extractSpreadsheetId(spreadsheetId),
        sheet_name: selectedSheet.title,
        mapping,
      })
      setSavedMapping(result)
      setActiveStep(3)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to save field mapping.'
      setMappingError(message)
    } finally {
      setMappingLoading(false)
    }
  }

  // ---- Step 3: Import ----
  const startPolling = useCallback(
    (jobId: number) => {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        try {
          const job = await leadService.getImportJob(jobId)
          setImportJob(job)
          if (
            job.status === ImportJobStatus.COMPLETED ||
            job.status === ImportJobStatus.FAILED
          ) {
            if (pollRef.current) clearInterval(pollRef.current)
            pollRef.current = null
          }
        } catch {
          // Polling failure is non-critical; keep trying
        }
      }, 2000)
    },
    [],
  )

  const handleStartImport = async () => {
    if (!selectedSheet) return
    setImportStarting(true)
    setImportError(null)
    try {
      const job = await leadService.startImport({
        spreadsheet_id: extractSpreadsheetId(spreadsheetId),
        sheet_name: selectedSheet.title,
        field_mapping_id: savedMapping?.id,
      })
      setImportJob(job)
      startPolling(job.id)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to start import.'
      setImportError(message)
    } finally {
      setImportStarting(false)
    }
  }

  // ---- Derived state for import progress ----
  const importInProgress =
    importJob?.status === ImportJobStatus.IN_PROGRESS ||
    importJob?.status === ImportJobStatus.PENDING
  const importCompleted = importJob?.status === ImportJobStatus.COMPLETED
  const importFailed = importJob?.status === ImportJobStatus.FAILED
  const progressPercent =
    importJob && importJob.total_rows > 0
      ? Math.round((importJob.rows_processed / importJob.total_rows) * 100)
      : 0

  // ---- Render helpers per step ----

  const renderAuthStep = () => (
    <Box
      sx={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center', py: 2 }}
      aria-label="Google OAuth2 authentication"
    >
      <Typography variant="body1" sx={{ textAlign: 'center' }}>
        Connect your Google account to import leads from Google Sheets.
      </Typography>
      {authError && (
        <Alert severity="error" role="alert" sx={{ width: '100%' }}>
          {authError}
        </Alert>
      )}
      <Box sx={{ display: 'flex', gap: 1 }}>
        {onCancel && (
          <Button onClick={onCancel} aria-label="Cancel import">
            Cancel
          </Button>
        )}
        <Button
          variant="contained"
          size="large"
          onClick={handleAuthenticate}
          disabled={authLoading}
          aria-label="Connect to Google Sheets"
        >
          {authLoading ? <CircularProgress size={20} aria-label="Connecting" /> : 'Connect to Google Sheets'}
        </Button>
      </Box>
    </Box>
  )

  const renderSheetSelectionStep = () => (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }} aria-label="Sheet selection">
      <Typography variant="body1">
        Paste your Google Sheets link below and select a sheet to import.
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
        <TextField
          label="Google Sheets URL or Spreadsheet ID"
          placeholder="https://docs.google.com/spreadsheets/d/..."
          value={spreadsheetId}
          onChange={(e) => setSpreadsheetId(e.target.value)}
          fullWidth
          aria-label="Google Sheets URL or Spreadsheet ID"
        />
        <Button
          variant="contained"
          onClick={handleListSheets}
          disabled={sheetsLoading || !spreadsheetId.trim()}
          sx={{ mt: 1, whiteSpace: 'nowrap' }}
          aria-label="Load sheets"
        >
          {sheetsLoading ? <CircularProgress size={20} aria-label="Loading sheets" /> : 'Load Sheets'}
        </Button>
      </Box>
      {sheetsError && (
        <Alert severity="error" role="alert">
          {sheetsError}
        </Alert>
      )}
      {mappingError && (
        <Alert severity="error" role="alert">
          {mappingError}
        </Alert>
      )}
      {sheets.length > 0 && (
        <Paper variant="outlined">
          <List aria-label="Available sheets">
            {sheets.map((sheet) => (
              <ListItem key={sheet.sheet_id} disablePadding>
                <ListItemButton
                  selected={selectedSheet?.sheet_id === sheet.sheet_id}
                  onClick={() => handleSelectSheet(sheet)}
                  disabled={mappingLoading}
                  aria-label={`Select sheet ${sheet.title}`}
                >
                  <ListItemText
                    primary={sheet.title}
                    secondary={`${sheet.row_count} rows, ${sheet.column_count} columns`}
                  />
                  {mappingLoading && selectedSheet?.sheet_id === sheet.sheet_id && (
                    <CircularProgress size={20} aria-label="Loading headers" />
                  )}
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        </Paper>
      )}
      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        {onCancel && (
          <Button onClick={onCancel} aria-label="Cancel import">
            Cancel
          </Button>
        )}
        <Button onClick={() => setActiveStep(0)} aria-label="Go back to authentication">
          Back
        </Button>
      </Box>
    </Box>
  )

  const renderFieldMappingStep = () => {
    const usedDbFields = new Set(Object.values(mapping))
    const missingRequired = REQUIRED_FIELDS.filter((f) => !usedDbFields.has(f))

    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }} aria-label="Field mapping">
        <Typography variant="body1">
          Map each sheet column to a database field. Required fields are marked with *.
        </Typography>
        {missingRequired.length > 0 && (
          <Alert severity="warning" role="alert">
            Required fields not yet mapped:{' '}
            {missingRequired
              .map((f) => DATABASE_FIELDS.find((d) => d.value === f)?.label || f)
              .join(', ')}
          </Alert>
        )}
        {mappingError && (
          <Alert severity="error" role="alert">
            {mappingError}
          </Alert>
        )}
        <Box
          sx={{
            maxHeight: 400,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 1.5,
          }}
          role="group"
          aria-label="Column to field mapping"
        >
          {headers.map((header) => {
            const currentValue = mapping[header] || ''
            return (
              <Box
                key={header}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 2,
                }}
              >
                <Typography
                  variant="body2"
                  sx={{ minWidth: 160, fontWeight: 500 }}
                  title={header}
                >
                  {header}
                </Typography>
                <FormControl size="small" fullWidth>
                  <InputLabel id={`mapping-label-${header}`}>Database Field</InputLabel>
                  <Select
                    labelId={`mapping-label-${header}`}
                    value={currentValue}
                    label="Database Field"
                    onChange={(e) => handleMappingChange(header, e.target.value)}
                    aria-label={`Map column ${header} to database field`}
                  >
                    <MenuItem value="">
                      <em>— Skip —</em>
                    </MenuItem>
                    {DATABASE_FIELDS.map((field) => {
                      const taken = usedDbFields.has(field.value) && currentValue !== field.value
                      return (
                        <MenuItem key={field.value} value={field.value} disabled={taken}>
                          {field.label}
                          {field.required ? ' *' : ''}
                        </MenuItem>
                      )
                    })}
                  </Select>
                </FormControl>
                {currentValue && REQUIRED_FIELDS.includes(currentValue) && (
                  <Chip label="Required" size="small" color="primary" />
                )}
              </Box>
            )
          })}
        </Box>
        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          {onCancel && (
            <Button onClick={onCancel} aria-label="Cancel import">
              Cancel
            </Button>
          )}
          <Button onClick={() => setActiveStep(1)} aria-label="Go back to sheet selection">
            Back
          </Button>
          <Button
            variant="contained"
            onClick={handleSaveMapping}
            disabled={!requiredFieldsMapped || mappingLoading}
            aria-label="Save mapping and continue"
          >
            {mappingLoading ? (
              <CircularProgress size={20} aria-label="Saving mapping" />
            ) : (
              'Save & Continue'
            )}
          </Button>
        </Box>
      </Box>
    )
  }

  const renderImportProgressStep = () => (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }} aria-label="Import progress">
      {!importJob && !importError && (
        <>
          <Typography variant="body1">
            Ready to import from sheet &quot;{selectedSheet?.title}&quot;. Click Start Import to
            begin.
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
            {onCancel && (
              <Button onClick={onCancel} aria-label="Cancel import">
                Cancel
              </Button>
            )}
            <Button onClick={() => setActiveStep(2)} aria-label="Go back to field mapping">
              Back
            </Button>
            <Button
              variant="contained"
              onClick={handleStartImport}
              disabled={importStarting}
              aria-label="Start import"
            >
              {importStarting ? (
                <CircularProgress size={20} aria-label="Starting import" />
              ) : (
                'Start Import'
              )}
            </Button>
          </Box>
        </>
      )}

      {importError && (
        <Alert severity="error" role="alert">
          {importError}
        </Alert>
      )}

      {importJob && importInProgress && (
        <Box aria-live="polite">
          <Typography variant="body1" gutterBottom>
            Importing rows…
          </Typography>
          <LinearProgress
            variant="determinate"
            value={progressPercent}
            aria-label="Import progress"
            aria-valuenow={progressPercent}
            aria-valuemin={0}
            aria-valuemax={100}
          />
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {importJob.rows_processed} / {importJob.total_rows} rows processed ({progressPercent}%)
          </Typography>
        </Box>
      )}

      {importJob && importCompleted && (
        <Box aria-live="polite">
          <Alert severity="success" role="alert" sx={{ mb: 2 }}>
            Import completed successfully.
          </Alert>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: 1,
              maxWidth: 360,
            }}
          >
            <Typography variant="body2" color="text.secondary">
              Total rows:
            </Typography>
            <Typography variant="body2">{importJob.total_rows}</Typography>
            <Typography variant="body2" color="text.secondary">
              Rows imported:
            </Typography>
            <Typography variant="body2">{importJob.rows_imported}</Typography>
            <Typography variant="body2" color="text.secondary">
              Rows skipped:
            </Typography>
            <Typography variant="body2">{importJob.rows_skipped}</Typography>
          </Box>
          {importJob.error_log && importJob.error_log.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Alert severity="warning" role="alert" sx={{ mb: 1 }}>
                {importJob.error_log.length} row(s) skipped due to validation errors.
              </Alert>
              <Box sx={{ maxHeight: 200, overflowY: 'auto', bgcolor: 'grey.50', borderRadius: 1, p: 1 }}>
                {importJob.error_log.map((entry, idx) => (
                  <Typography key={idx} variant="body2" sx={{ fontSize: '0.8rem', fontFamily: 'monospace', mb: 0.5 }}>
                    Row {entry.row}: {typeof entry.error === 'string' ? entry.error : (Array.isArray(entry.errors) ? entry.errors.join('; ') : JSON.stringify(entry))}
                  </Typography>
                ))}
              </Box>
            </Box>
          )}
          <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end', mt: 2 }}>
            <Button
              variant="contained"
              onClick={() => onComplete?.()}
              aria-label="Finish import"
            >
              Done
            </Button>
          </Box>
        </Box>
      )}

      {importJob && importFailed && (
        <Box aria-live="polite">
          <Alert severity="error" role="alert" sx={{ mb: 2 }}>
            Import failed.
          </Alert>
          {importJob.error_log && importJob.error_log.length > 0 && (
            <Typography variant="body2" color="text.secondary">
              Errors: {importJob.error_log.map((e) => `Row ${e.row}: ${e.error}`).join('; ')}
            </Typography>
          )}
          <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end', mt: 2 }}>
            <Button onClick={() => setActiveStep(2)} aria-label="Go back to field mapping">
              Back
            </Button>
            <Button
              variant="contained"
              onClick={handleStartImport}
              disabled={importStarting}
              aria-label="Retry import"
            >
              Retry
            </Button>
          </Box>
        </Box>
      )}
    </Box>
  )

  const stepContent = [renderAuthStep, renderSheetSelectionStep, renderFieldMappingStep, renderImportProgressStep]

  return (
    <Box
      component="section"
      aria-labelledby="import-wizard-heading"
      sx={{ maxWidth: 720, mx: 'auto', px: { xs: 1, sm: 2 } }}
    >
      <Typography variant="h5" id="import-wizard-heading" component="h2" sx={{ mb: 2 }}>
        Import from Google Sheets
      </Typography>

      <Stepper activeStep={activeStep} alternativeLabel sx={{ mb: 3 }} aria-label="Import wizard steps">
        {STEP_LABELS.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>{stepContent[activeStep]()}</Paper>
    </Box>
  )
}
