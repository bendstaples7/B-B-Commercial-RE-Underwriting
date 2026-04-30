import React, { useMemo, useCallback } from 'react'
import {
  Box,
  Typography,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  Alert,
  Button,
  IconButton,
  Tooltip,
} from '@mui/material'
import RestartAltIcon from '@mui/icons-material/RestartAlt'

/** Database fields available for mapping. */
export const DATABASE_FIELDS: { value: string; label: string; required: boolean }[] = [
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

/**
 * Validate that all required database fields are mapped.
 *
 * Exported for reuse in other components (e.g. ImportWizard).
 */
export function validateMapping(
  mapping: Record<string, string>,
): { valid: boolean; missingRequired: string[] } {
  const mappedDbFields = new Set(Object.values(mapping).filter(Boolean))
  const missingRequired = REQUIRED_FIELDS.filter((f) => !mappedDbFields.has(f))
  return { valid: missingRequired.length === 0, missingRequired }
}

/** Props for the FieldMappingEditor component. */
export interface FieldMappingEditorProps {
  /** Sheet column headers to display. */
  headers: string[]
  /** Current mapping: header → database field. Includes auto-mapped fields. */
  mapping: Record<string, string>
  /** Callback when the mapping changes. */
  onMappingChange: (mapping: Record<string, string>) => void
  /** Whether the editor is read-only. */
  disabled?: boolean
  /** Whether to show validation warnings. Defaults to true. */
  showValidation?: boolean
  /** Original auto-mapping for the "Reset to Auto-Map" feature. If not provided, reset clears all mappings. */
  autoMapping?: Record<string, string>
}

/**
 * Standalone, reusable field mapping editor.
 *
 * Displays sheet column headers with dropdown selectors to choose target database fields.
 * Shows auto-mapped fields pre-selected, validates required fields, and prevents
 * mapping the same database field to multiple sheet columns.
 *
 * Requirements: 2.1, 2.2, 2.3, 2.5
 */
export const FieldMappingEditor: React.FC<FieldMappingEditorProps> = ({
  headers,
  mapping,
  onMappingChange,
  disabled = false,
  showValidation = true,
  autoMapping,
}) => {
  const usedDbFields = useMemo(() => new Set(Object.values(mapping).filter(Boolean)), [mapping])

  const { valid, missingRequired } = useMemo(() => validateMapping(mapping), [mapping])

  const handleFieldChange = useCallback(
    (header: string, dbField: string) => {
      const next = { ...mapping }
      if (dbField === '') {
        delete next[header]
      } else {
        // Remove any other header that was previously mapped to this db field
        for (const key of Object.keys(next)) {
          if (next[key] === dbField && key !== header) {
            delete next[key]
          }
        }
        next[header] = dbField
      }
      onMappingChange(next)
    },
    [mapping, onMappingChange],
  )

  const handleReset = useCallback(() => {
    onMappingChange(autoMapping ? { ...autoMapping } : {})
  }, [autoMapping, onMappingChange])

  return (
    <Box
      component="section"
      aria-label="Field mapping editor"
      sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
    >
      {/* Header row with title and reset button */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="subtitle1" component="h3" id="field-mapping-heading">
          Map Sheet Columns to Database Fields
        </Typography>
        <Tooltip title="Reset to Auto-Map">
          <span>
            <IconButton
              onClick={handleReset}
              disabled={disabled}
              aria-label="Reset to auto-map"
              size="small"
            >
              <RestartAltIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {/* Validation warning */}
      {showValidation && !valid && (
        <Alert severity="warning" role="alert" aria-label="Required fields warning">
          Required fields not yet mapped:{' '}
          {missingRequired
            .map((f) => DATABASE_FIELDS.find((d) => d.value === f)?.label || f)
            .join(', ')}
        </Alert>
      )}

      {/* Column mapping rows */}
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
          const isRequired = REQUIRED_FIELDS.includes(currentValue)

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
              <FormControl size="small" fullWidth disabled={disabled}>
                <InputLabel id={`fme-label-${header}`}>Database Field</InputLabel>
                <Select
                  labelId={`fme-label-${header}`}
                  value={currentValue}
                  label="Database Field"
                  onChange={(e) => handleFieldChange(header, e.target.value)}
                  aria-label={`Map column ${header} to database field`}
                  data-testid={`select-${header}`}
                >
                  <MenuItem value="">
                    <em>— Skip —</em>
                  </MenuItem>
                  {DATABASE_FIELDS.map((field) => {
                    const taken = usedDbFields.has(field.value) && currentValue !== field.value
                    return (
                      <MenuItem
                        key={field.value}
                        value={field.value}
                        disabled={taken}
                        data-testid={`option-${header}-${field.value}`}
                      >
                        {field.label}
                        {field.required ? ' *' : ''}
                      </MenuItem>
                    )
                  })}
                </Select>
              </FormControl>
              {isRequired && (
                <Chip label="Required" size="small" color="primary" />
              )}
            </Box>
          )
        })}
      </Box>

      {/* Reset button (text variant for additional visibility) */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-start' }}>
        <Button
          variant="text"
          startIcon={<RestartAltIcon />}
          onClick={handleReset}
          disabled={disabled}
          aria-label="Reset mapping to auto-map"
          size="small"
        >
          Reset to Auto-Map
        </Button>
      </Box>
    </Box>
  )
}
