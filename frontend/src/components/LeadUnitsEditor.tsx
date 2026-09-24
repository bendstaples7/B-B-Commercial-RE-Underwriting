/**
 * Shared lead_units inventory editor for Quick Add and Command Center.
 * Not the multifamily Deal rent roll — CRM capture only.
 */
import {
  Box,
  Button,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import AddIcon from '@mui/icons-material/Add'

export const LEAD_UNIT_TYPES = [
  { value: 'residential', label: 'Residential' },
  { value: 'storefront', label: 'Storefront' },
  { value: 'office', label: 'Office' },
  { value: 'other', label: 'Other' },
] as const

export const LEAD_SUBTYPES = [
  { value: 'residential', label: 'Residential' },
  { value: 'mixed_use', label: 'Mixed use' },
  { value: 'commercial', label: 'Commercial' },
] as const

export type LeadUnitType = (typeof LEAD_UNIT_TYPES)[number]['value']
export type LeadSubtype = (typeof LEAD_SUBTYPES)[number]['value']

export type LeadUnitDraft = {
  key: string
  unit_label: string
  unit_type: LeadUnitType
  beds: string
  baths: string
  sqft: string
  current_rent: string
}

export function emptyLeadUnitDraft(index = 0): LeadUnitDraft {
  return {
    key: `unit-${Date.now()}-${index}`,
    unit_label: `Unit ${index + 1}`,
    unit_type: 'residential',
    beds: '',
    baths: '',
    sqft: '',
    current_rent: '',
  }
}

export function leadUnitDraftsFromApi(
  rows: Array<{
    id?: number
    unit_label?: string | null
    unit_type?: string | null
    beds?: number | null
    baths?: number | null
    sqft?: number | null
    current_rent?: number | null
  }> | null | undefined,
): LeadUnitDraft[] {
  if (!rows?.length) return []
  return rows.map((row, index) => ({
    key: row.id != null ? `unit-id-${row.id}` : `unit-${index}`,
    unit_label: row.unit_label?.trim() || `Unit ${index + 1}`,
    unit_type: (LEAD_UNIT_TYPES.some((t) => t.value === row.unit_type)
      ? row.unit_type
      : 'residential') as LeadUnitType,
    beds: row.beds != null ? String(row.beds) : '',
    baths: row.baths != null ? String(row.baths) : '',
    sqft: row.sqft != null ? String(row.sqft) : '',
    current_rent: row.current_rent != null ? String(row.current_rent) : '',
  }))
}

export function serializeLeadUnitDrafts(drafts: LeadUnitDraft[]) {
  return drafts.map((row, index) => ({
    unit_label: row.unit_label.trim() || `Unit ${index + 1}`,
    unit_type: row.unit_type,
    beds: row.beds.trim() === '' ? null : Number(row.beds),
    baths: row.baths.trim() === '' ? null : Number(row.baths),
    sqft: row.sqft.trim() === '' ? null : Number(row.sqft),
    current_rent: row.current_rent.trim() === '' ? null : Number(row.current_rent),
    sort_order: index,
  }))
}

export interface LeadUnitsEditorProps {
  units: LeadUnitDraft[]
  onChange: (units: LeadUnitDraft[]) => void
  subtype?: LeadSubtype | ''
  onSubtypeChange?: (value: LeadSubtype | '') => void
  disabled?: boolean
  testIdPrefix?: string
}

export function LeadUnitsEditor({
  units,
  onChange,
  subtype,
  onSubtypeChange,
  disabled = false,
  testIdPrefix = 'lead-units',
}: LeadUnitsEditorProps) {
  const updateRow = (key: string, patch: Partial<LeadUnitDraft>) => {
    onChange(units.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  return (
    <Box data-testid={testIdPrefix} sx={{ cursor: 'auto' }}>
      {onSubtypeChange != null && (
        <FormControl fullWidth size="small" sx={{ mb: 1.5 }} disabled={disabled}>
          <InputLabel id={`${testIdPrefix}-subtype-label`}>Property subtype</InputLabel>
          <Select
            labelId={`${testIdPrefix}-subtype-label`}
            label="Property subtype"
            value={subtype || ''}
            onChange={(e) => onSubtypeChange((e.target.value || '') as LeadSubtype | '')}
            inputProps={{ 'data-testid': `${testIdPrefix}-subtype` }}
          >
            <MenuItem value="">
              <em>Not set</em>
            </MenuItem>
            {LEAD_SUBTYPES.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      )}

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Unit mix
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Optional. Use for mixed-use or multi-unit buildings (storefront + apartments, etc.).
      </Typography>

      {units.map((unit, index) => (
        <Box
          key={unit.key}
          data-testid={`${testIdPrefix}-row-${index}`}
          sx={{
            mb: 1.5,
            p: 1.5,
            border: 1,
            borderColor: 'divider',
            borderRadius: 1,
            cursor: 'auto',
          }}
        >
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
            <Typography variant="body2" fontWeight={600}>
              Unit {index + 1}
            </Typography>
            <IconButton
              size="small"
              aria-label={`Remove unit ${index + 1}`}
              data-testid={`${testIdPrefix}-remove-${index}`}
              disabled={disabled}
              onClick={() => onChange(units.filter((row) => row.key !== unit.key))}
              sx={{ cursor: 'pointer' }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Box>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1 }}>
            <TextField
              label="Label"
              size="small"
              value={unit.unit_label}
              onChange={(e) => updateRow(unit.key, { unit_label: e.target.value })}
              disabled={disabled}
              sx={{ flex: '1 1 120px', caretColor: 'text.primary' }}
              inputProps={{ 'data-testid': `${testIdPrefix}-label-${index}` }}
            />
            <FormControl size="small" sx={{ minWidth: 140, flex: '1 1 140px' }} disabled={disabled}>
              <InputLabel id={`${testIdPrefix}-type-${index}-label`}>Type</InputLabel>
              <Select
                labelId={`${testIdPrefix}-type-${index}-label`}
                label="Type"
                value={unit.unit_type}
                onChange={(e) => updateRow(unit.key, { unit_type: e.target.value as LeadUnitType })}
                inputProps={{ 'data-testid': `${testIdPrefix}-type-${index}` }}
              >
                {LEAD_UNIT_TYPES.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <TextField
              label="Beds"
              size="small"
              type="number"
              value={unit.beds}
              onChange={(e) => updateRow(unit.key, { beds: e.target.value })}
              disabled={disabled}
              sx={{ width: 90, caretColor: 'text.primary' }}
              inputProps={{ min: 0, 'data-testid': `${testIdPrefix}-beds-${index}` }}
            />
            <TextField
              label="Baths"
              size="small"
              type="number"
              value={unit.baths}
              onChange={(e) => updateRow(unit.key, { baths: e.target.value })}
              disabled={disabled}
              sx={{ width: 90, caretColor: 'text.primary' }}
              inputProps={{ min: 0, step: 0.5, 'data-testid': `${testIdPrefix}-baths-${index}` }}
            />
            <TextField
              label="Sqft"
              size="small"
              type="number"
              value={unit.sqft}
              onChange={(e) => updateRow(unit.key, { sqft: e.target.value })}
              disabled={disabled}
              sx={{ width: 100, caretColor: 'text.primary' }}
              inputProps={{ min: 0, 'data-testid': `${testIdPrefix}-sqft-${index}` }}
            />
            <TextField
              label="Rent"
              size="small"
              type="number"
              value={unit.current_rent}
              onChange={(e) => updateRow(unit.key, { current_rent: e.target.value })}
              disabled={disabled}
              sx={{ width: 110, caretColor: 'text.primary' }}
              inputProps={{ min: 0, 'data-testid': `${testIdPrefix}-rent-${index}` }}
            />
          </Box>
        </Box>
      ))}

      <Button
        type="button"
        size="small"
        startIcon={<AddIcon />}
        onClick={() => onChange([...units, emptyLeadUnitDraft(units.length)])}
        disabled={disabled}
        data-testid={`${testIdPrefix}-add`}
        sx={{ cursor: 'pointer' }}
      >
        Add unit
      </Button>
    </Box>
  )
}

export default LeadUnitsEditor
