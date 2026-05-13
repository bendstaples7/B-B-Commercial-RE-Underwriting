/**
 * OMUnitMixComparison — per-unit-type comparison table with inline rent editing.
 *
 * Renders a MUI Table with one row per unit type showing:
 *   Unit Type | Count | Sqft | Current Avg Rent | Pro Forma Rent | Market Rent Est.
 *
 * The three rent fields (current_avg_rent, proforma_rent, market_rent_estimate) are
 * editable inline. When a value is changed the row is marked user_overridden and
 * onRowsChange is called so the parent can feed the updated rows into omScenarioEngine
 * for a recalculation within 300 ms.
 *
 * Overridden fields are highlighted with an amber background and an asterisk (*) in
 * the column header tooltip.
 *
 * Requirements: 5.7, 6.3, 6.4, 6.5
 */
import React, { useCallback, useState } from 'react'
import {
  Box,
  InputAdornment,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import { UnitMixComparisonRow } from '@/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OMUnitMixComparisonProps {
  rows: UnitMixComparisonRow[]
  onRowsChange: (updatedRows: UnitMixComparisonRow[], overriddenFields: Set<string>) => void
}

/** Internal row state that tracks which fields have been overridden by the user. */
interface EditableRow extends UnitMixComparisonRow {
  overriddenFields: Set<string>
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a Decimal-as-string value as a USD currency string, or "—" if null. */
function formatCurrency(value: string | null): string {
  if (value === null || value === undefined) return '—'
  const num = parseFloat(value)
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(num)
}

/** Format sqft as a number string, or "—" if null. */
function formatSqft(value: string | null): string {
  if (value === null || value === undefined) return '—'
  const num = parseFloat(value)
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US').format(Math.round(num))
}

/** Parse a user-entered string into a Decimal-compatible string, or null if empty/invalid. */
function parseRentInput(raw: string): string | null {
  const trimmed = raw.trim()
  if (trimmed === '' || trimmed === '—') return null
  const num = parseFloat(trimmed)
  if (isNaN(num) || num < 0) return null
  return String(num)
}

/** Convert UnitMixComparisonRow[] to EditableRow[] with empty override sets. */
function toEditableRows(rows: UnitMixComparisonRow[]): EditableRow[] {
  return rows.map((row) => ({ ...row, overriddenFields: new Set<string>() }))
}

// ---------------------------------------------------------------------------
// Amber override style
// ---------------------------------------------------------------------------

const OVERRIDE_SX = {
  backgroundColor: 'warning.light',
  '& .MuiInputBase-root': {
    backgroundColor: 'warning.light',
  },
}

// ---------------------------------------------------------------------------
// Sub-component: editable rent cell
// ---------------------------------------------------------------------------

interface RentCellProps {
  value: string | null
  fieldKey: string
  rowIndex: number
  isOverridden: boolean
  onChange: (rowIndex: number, fieldKey: string, newValue: string | null) => void
}

function RentCell({ value, fieldKey, rowIndex, isOverridden, onChange }: RentCellProps) {
  const [editing, setEditing] = useState(false)
  const [inputValue, setInputValue] = useState<string>('')

  const handleFocus = () => {
    setInputValue(value !== null ? String(parseFloat(value)) : '')
    setEditing(true)
  }

  const handleBlur = () => {
    setEditing(false)
    const parsed = parseRentInput(inputValue)
    onChange(rowIndex, fieldKey, parsed)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      ;(e.target as HTMLInputElement).blur()
    }
    if (e.key === 'Escape') {
      setInputValue(value !== null ? String(parseFloat(value)) : '')
      setEditing(false)
    }
  }

  return (
    <Tooltip
      title={isOverridden ? 'User overridden *' : 'Click to edit'}
      placement="top"
      arrow
    >
      <TextField
        type="number"
        size="small"
        variant="outlined"
        value={editing ? inputValue : value !== null ? String(parseFloat(value)) : ''}
        placeholder="—"
        onFocus={handleFocus}
        onBlur={handleBlur}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        inputProps={{
          min: 0,
          step: 1,
          'aria-label': `Edit ${fieldKey}`,
        }}
        InputProps={{
          startAdornment: <InputAdornment position="start">$</InputAdornment>,
          endAdornment: isOverridden ? (
            <InputAdornment position="end">
              <Tooltip title="User overridden">
                <EditIcon fontSize="small" sx={{ color: 'warning.dark' }} />
              </Tooltip>
            </InputAdornment>
          ) : undefined,
        }}
        sx={{
          width: 140,
          ...(isOverridden ? OVERRIDE_SX : {}),
        }}
      />
    </Tooltip>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function OMUnitMixComparison({ rows, onRowsChange }: OMUnitMixComparisonProps) {
  const [editableRows, setEditableRows] = useState<EditableRow[]>(() =>
    toEditableRows(rows),
  )

  // Sync external rows changes (e.g. parent recalculation) while preserving local
  // override tracking. We only re-initialise if the row count or unit type labels change.
  const prevRowsRef = React.useRef<UnitMixComparisonRow[]>(rows)
  React.useEffect(() => {
    const prev = prevRowsRef.current
    const labelsChanged =
      prev.length !== rows.length ||
      prev.some((r, i) => r.unit_type_label !== rows[i]?.unit_type_label)

    if (labelsChanged) {
      // Structure changed — reset everything
      setEditableRows(toEditableRows(rows))
    } else {
      // Merge updated values from parent while preserving override flags
      setEditableRows((current) =>
        rows.map((row, i) => ({
          ...row,
          overriddenFields: current[i]?.overriddenFields ?? new Set<string>(),
        })),
      )
    }
    prevRowsRef.current = rows
  }, [rows])

  const handleRentChange = useCallback(
    (rowIndex: number, fieldKey: string, newValue: string | null) => {
      setEditableRows((prev) => {
        const updated = prev.map((row, i) => {
          if (i !== rowIndex) return row
          const newOverrides = new Set(row.overriddenFields)
          newOverrides.add(fieldKey)
          return { ...row, [fieldKey]: newValue, overriddenFields: newOverrides }
        })

        // Build the plain UnitMixComparisonRow[] and the global overridden field set
        const plainRows: UnitMixComparisonRow[] = updated.map(
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          ({ overriddenFields: _of, ...rest }) => rest,
        )
        const allOverridden = new Set<string>()
        updated.forEach((row, i) => {
          row.overriddenFields.forEach((f) => allOverridden.add(`unit_mix.${i}.${f}`))
        })

        onRowsChange(plainRows, allOverridden)
        return updated
      })
    },
    [onRowsChange],
  )

  if (editableRows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
        No unit mix data available.
      </Typography>
    )
  }

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 600 }}>
        Unit Mix Comparison
      </Typography>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="Unit mix comparison table">
          <TableHead>
            <TableRow sx={{ backgroundColor: 'grey.50' }}>
              <TableCell sx={{ fontWeight: 600 }}>Unit Type</TableCell>
              <TableCell align="right" sx={{ fontWeight: 600 }}>
                Count
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 600 }}>
                Sqft
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 600 }}>
                <Tooltip title="Editable — changes recalculate broker current scenario" arrow>
                  <span>Current Avg Rent</span>
                </Tooltip>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 600 }}>
                <Tooltip title="Editable — changes recalculate broker pro forma scenario" arrow>
                  <span>Pro Forma Rent</span>
                </Tooltip>
              </TableCell>
              <TableCell align="left" sx={{ fontWeight: 600 }}>
                <Tooltip title="Editable — changes recalculate realistic scenario" arrow>
                  <span>Market Rent Est. (Low – High)</span>
                </Tooltip>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {editableRows.map((row, rowIndex) => {
              const currentOverridden = row.overriddenFields.has('current_avg_rent')
              const proformaOverridden = row.overriddenFields.has('proforma_rent')
              const marketOverridden = row.overriddenFields.has('market_rent_estimate')

              return (
                <TableRow
                  key={row.unit_type_label}
                  sx={{
                    '&:last-child td, &:last-child th': { border: 0 },
                    '&:hover': { backgroundColor: 'action.hover' },
                  }}
                >
                  {/* Unit Type */}
                  <TableCell component="th" scope="row" sx={{ fontWeight: 500 }}>
                    {row.unit_type_label}
                  </TableCell>

                  {/* Count */}
                  <TableCell align="right">{row.unit_count}</TableCell>

                  {/* Sqft */}
                  <TableCell align="right">{formatSqft(row.sqft)}</TableCell>

                  {/* Current Avg Rent — editable */}
                  <TableCell
                    align="center"
                    sx={currentOverridden ? { backgroundColor: 'warning.light' } : {}}
                  >
                    <RentCell
                      value={row.current_avg_rent}
                      fieldKey="current_avg_rent"
                      rowIndex={rowIndex}
                      isOverridden={currentOverridden}
                      onChange={handleRentChange}
                    />
                  </TableCell>

                  {/* Pro Forma Rent — editable */}
                  <TableCell
                    align="center"
                    sx={proformaOverridden ? { backgroundColor: 'warning.light' } : {}}
                  >
                    <RentCell
                      value={row.proforma_rent}
                      fieldKey="proforma_rent"
                      rowIndex={rowIndex}
                      isOverridden={proformaOverridden}
                      onChange={handleRentChange}
                    />
                  </TableCell>

                  {/* Market Rent Estimate — editable (estimate only; low/high are read-only) */}
                  <TableCell
                    align="left"
                    sx={marketOverridden ? { backgroundColor: 'warning.light' } : {}}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <RentCell
                        value={row.market_rent_estimate}
                        fieldKey="market_rent_estimate"
                        rowIndex={rowIndex}
                        isOverridden={marketOverridden}
                        onChange={handleRentChange}
                      />
                      {/* Low–High range display (read-only) */}
                      {row.market_rent_low !== null && row.market_rent_high !== null && (
                        <Typography variant="caption" color="text.secondary" noWrap>
                          ({formatCurrency(row.market_rent_low)} –{' '}
                          {formatCurrency(row.market_rent_high)})
                        </Typography>
                      )}
                      {row.market_rent_estimate === null &&
                        row.market_rent_low === null &&
                        row.market_rent_high === null && (
                          <Typography variant="body2" color="text.disabled">
                            —
                          </Typography>
                        )}
                    </Box>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Legend */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 1 }}>
        <Box
          sx={{
            width: 12,
            height: 12,
            borderRadius: 0.5,
            backgroundColor: 'warning.light',
            border: '1px solid',
            borderColor: 'warning.main',
          }}
        />
        <Typography variant="caption" color="text.secondary">
          Amber background = user overridden (*)
        </Typography>
      </Box>
    </Box>
  )
}
