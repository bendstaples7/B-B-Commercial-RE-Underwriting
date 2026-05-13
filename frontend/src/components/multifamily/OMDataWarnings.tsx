/**
 * OMDataWarnings — renders the "Data Warnings" section for an OM intake review.
 *
 * Displays consistency warnings produced by the backend (unit count mismatch,
 * NOI inconsistency, cap rate inconsistency, GRM inconsistency, insufficient
 * data, and unrecognized expense labels). Warnings are informational only and
 * do NOT block the user from confirming the intake.
 *
 * Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
 */
import { Alert, Box, Typography } from '@mui/material'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface OMDataWarningsProps {
  warnings: Array<Record<string, unknown>> | null | undefined
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a number as USD currency (no cents for large values). */
function formatCurrency(value: unknown): string {
  const num = Number(value)
  if (!isFinite(num)) return String(value ?? '')
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

/** Format a number as a percentage (e.g. 0.065 → "6.50%"). */
function formatPercent(value: unknown): string {
  const num = Number(value)
  if (!isFinite(num)) return String(value ?? '')
  return `${(num * 100).toFixed(2)}%`
}

/** Format a plain decimal number to 2 decimal places. */
function formatDecimal(value: unknown): string {
  const num = Number(value)
  if (!isFinite(num)) return String(value ?? '')
  return num.toFixed(2)
}

// ---------------------------------------------------------------------------
// Warning message builders
// ---------------------------------------------------------------------------

function buildWarningMessage(warning: Record<string, unknown>): string {
  const type = warning.type as string | undefined

  switch (type) {
    case 'unit_count_mismatch_warning': {
      const computed = warning.computed
      const stated = warning.stated
      const delta = warning.delta
      return `Unit count mismatch: sum of unit mix rows (${computed}) ≠ stated unit count (${stated}), delta: ${delta}`
    }

    case 'noi_consistency_warning': {
      const computed = formatCurrency(warning.computed)
      const stated = formatCurrency(warning.stated)
      const delta = formatCurrency(warning.delta)
      return `NOI inconsistency: computed NOI (${computed}) ≠ stated NOI (${stated}), delta: ${delta}`
    }

    case 'cap_rate_consistency_warning': {
      const computed = formatPercent(warning.computed)
      const stated = formatPercent(warning.stated)
      const delta = formatPercent(warning.delta)
      return `Cap rate inconsistency: computed cap rate (${computed}) ≠ stated cap rate (${stated}), delta: ${delta}`
    }

    case 'grm_consistency_warning': {
      const computed = formatDecimal(warning.computed)
      const stated = formatDecimal(warning.stated)
      const delta = formatDecimal(warning.delta)
      return `GRM inconsistency: computed GRM (${computed}) ≠ stated GRM (${stated}), delta: ${delta}`
    }

    case 'insufficient_data_warning': {
      const field = warning.field ?? 'unknown field'
      const reason = warning.reason ?? 'missing data'
      return `Insufficient data for ${field} check: ${reason}`
    }

    case 'unmatched_expense_items': {
      const items = warning.items
      if (Array.isArray(items) && items.length > 0) {
        const labels = items
          .map((item: unknown) => {
            if (item && typeof item === 'object' && 'label' in item) {
              return String((item as Record<string, unknown>).label)
            }
            return String(item)
          })
          .join(', ')
        return `Unrecognized expense labels: ${labels}`
      }
      return 'Unrecognized expense labels: (none listed)'
    }

    default: {
      // Fallback: render whatever message or type is available
      if (warning.message) return String(warning.message)
      if (type) return `Warning: ${type}`
      return 'Unknown warning'
    }
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OMDataWarnings({ warnings }: OMDataWarningsProps) {
  // Render nothing when there are no warnings
  if (!warnings || warnings.length === 0) {
    return null
  }

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Data Warnings
      </Typography>

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {warnings.map((warning, index) => (
          <Alert
            key={index}
            severity="warning"
          >
            {buildWarningMessage(warning)}
          </Alert>
        ))}
      </Box>
    </Box>
  )
}

export default OMDataWarnings
