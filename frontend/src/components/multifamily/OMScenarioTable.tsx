/**
 * OMScenarioTable — side-by-side three-scenario metrics table for OM intake review.
 *
 * Displays Broker Current, Broker Pro Forma, and Realistic scenario metrics
 * in a 4-column MUI Table. Shows variance and cap rate flags as Chips.
 *
 * Requirements: 5.1, 5.2, 5.3, 5.4, 5.6
 */
import {
  Box,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import TrendingDownIcon from '@mui/icons-material/TrendingDown'
import type { ScenarioComparison, ScenarioMetrics } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCurrency(value: string | null): string {
  if (value === null || value === undefined) return '—'
  const num = parseFloat(value)
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

function fmtPercent(value: string | null): string {
  if (value === null || value === undefined) return '—'
  const num = parseFloat(value)
  if (isNaN(num)) return '—'
  // Backend stores as decimal (e.g. 0.065 = 6.5%)
  return `${(num * 100).toFixed(2)}%`
}

function fmtNumber(value: string | null, decimals = 2): string {
  if (value === null || value === undefined) return '—'
  const num = parseFloat(value)
  if (isNaN(num)) return '—'
  return num.toFixed(decimals)
}

// ---------------------------------------------------------------------------
// Row definitions
// ---------------------------------------------------------------------------

type RowFormatter = (value: string | null) => string

interface MetricRowDef {
  label: string
  field: keyof ScenarioMetrics
  format: RowFormatter
  isNOI?: boolean
}

const METRIC_ROWS: MetricRowDef[] = [
  {
    label: 'Gross Potential Income (Annual)',
    field: 'gross_potential_income_annual',
    format: fmtCurrency,
  },
  {
    label: 'Effective Gross Income (Annual)',
    field: 'effective_gross_income_annual',
    format: fmtCurrency,
  },
  {
    label: 'Gross Expenses (Annual)',
    field: 'gross_expenses_annual',
    format: fmtCurrency,
  },
  {
    label: 'NOI (Annual)',
    field: 'noi_annual',
    format: fmtCurrency,
    isNOI: true,
  },
  {
    label: 'Cap Rate',
    field: 'cap_rate',
    format: fmtPercent,
  },
  {
    label: 'GRM',
    field: 'grm',
    format: (v) => fmtNumber(v, 2),
  },
  {
    label: 'Monthly Rent Total',
    field: 'monthly_rent_total',
    format: fmtCurrency,
  },
  {
    label: 'DSCR',
    field: 'dscr',
    format: (v) => fmtNumber(v, 2),
  },
  {
    label: 'Cash on Cash',
    field: 'cash_on_cash',
    format: fmtPercent,
  },
]

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface OMScenarioTableProps {
  comparison: ScenarioComparison
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OMScenarioTable({ comparison }: OMScenarioTableProps) {
  const { broker_current, broker_proforma, realistic, significant_variance_flag, realistic_cap_rate_below_proforma } = comparison

  return (
    <Box>
      {/* Variance flags */}
      {(significant_variance_flag || realistic_cap_rate_below_proforma) && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
          {significant_variance_flag && (
            <Chip
              icon={<WarningAmberIcon />}
              label="Significant variance between realistic and pro forma NOI (>10%)"
              color="warning"
              size="small"
            />
          )}
          {realistic_cap_rate_below_proforma && (
            <Chip
              icon={<TrendingDownIcon />}
              label="Realistic cap rate is below pro forma"
              color="error"
              size="small"
            />
          )}
        </Box>
      )}

      <TableContainer>
        <Table size="small" aria-label="Scenario comparison table">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 600, minWidth: 220 }}>Metric</TableCell>
              <TableCell align="right" sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                Broker Current
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                Broker Pro Forma
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                Realistic
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {METRIC_ROWS.map((row) => (
              <TableRow
                key={row.field}
                sx={{
                  '&:last-child td, &:last-child th': { border: 0 },
                  ...(row.isNOI && {
                    backgroundColor: 'action.hover',
                    '& td': { fontWeight: 600 },
                  }),
                }}
              >
                <TableCell component="th" scope="row">
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="body2">{row.label}</Typography>
                    {row.isNOI && significant_variance_flag && (
                      <Chip
                        icon={<WarningAmberIcon />}
                        label=">10% variance"
                        color="warning"
                        size="small"
                        sx={{ height: 20, '& .MuiChip-label': { px: 0.75, fontSize: '0.65rem' } }}
                      />
                    )}
                  </Box>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {row.format(broker_current[row.field] as string | null)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {row.format(broker_proforma[row.field] as string | null)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {row.format(realistic[row.field] as string | null)}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )
}

export default OMScenarioTable
