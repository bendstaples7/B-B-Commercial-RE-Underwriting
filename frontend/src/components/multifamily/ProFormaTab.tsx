/**
 * ProFormaTab — 24-month table of MonthlyRow values.
 * Recharts line chart for NOI and cash flow. "Force recompute" button.
 *
 * Requirements: 8.1–8.14
 */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { multifamilyService } from '@/services/api'
import type { ProFormaResult, MonthlyRow } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCompact(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(num)
}

function toNum(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null
  const n = parseFloat(value)
  return isNaN(n) ? null : n
}

// ---------------------------------------------------------------------------
// Chart
// ---------------------------------------------------------------------------

interface ProFormaChartProps {
  rows: MonthlyRow[]
}

function ProFormaChart({ rows }: ProFormaChartProps) {
  const data = rows.map((row) => ({
    month: row.month,
    noi: toNum(row.noi),
    net_cf: toNum(row.net_cash_flow),
    cfad_a: toNum(row.cash_flow_after_debt_a),
    cfad_b: toNum(row.cash_flow_after_debt_b),
  }))

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
        Cash Flow Overview (Months 1–24)
      </Typography>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            dataKey="month"
            label={{ value: 'Month', position: 'insideBottom', offset: -8 }}
          />
          <YAxis
            tickFormatter={(v: number) =>
              new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'USD',
                notation: 'compact',
                maximumFractionDigits: 1,
              }).format(v)
            }
          />
          <RechartsTooltip
            formatter={(value: number, name: string) => [fmtCompact(value), name]}
          />
          <Legend verticalAlign="top" />
          <Line
            type="monotone"
            dataKey="noi"
            name="NOI"
            stroke="#1976d2"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="net_cf"
            name="Net Cash Flow"
            stroke="#2e7d32"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="cfad_a"
            name="CF After Debt A"
            stroke="#ed6c02"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="cfad_b"
            name="CF After Debt B"
            stroke="#9c27b0"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </Paper>
  )
}

// ---------------------------------------------------------------------------
// Monthly Table
// ---------------------------------------------------------------------------

interface MonthlyTableProps {
  rows: MonthlyRow[]
}

function MonthlyTable({ rows }: MonthlyTableProps) {
  return (
    <TableContainer component={Paper} variant="outlined" sx={{ maxHeight: 480 }}>
      <Table size="small" stickyHeader aria-label="Pro forma monthly schedule">
        <TableHead>
          <TableRow>
            {[
              'Month', 'GSR', 'EGI', 'OpEx', 'NOI', 'Reserves',
              'Net CF', 'DS-A', 'DS-B', 'CFAD-A', 'CFAD-B',
              'CapEx', 'CFAC-A', 'CFAC-B',
            ].map((label) => (
              <TableCell
                key={label}
                align={label === 'Month' ? 'left' : 'right'}
                sx={{ whiteSpace: 'nowrap', fontWeight: 600 }}
              >
                {label}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.month} hover>
              <TableCell>{row.month}</TableCell>
              <TableCell align="right">{fmtCompact(row.gsr)}</TableCell>
              <TableCell align="right">{fmtCompact(row.egi)}</TableCell>
              <TableCell align="right">{fmtCompact(row.opex_total)}</TableCell>
              <TableCell align="right">{fmtCompact(row.noi)}</TableCell>
              <TableCell align="right">{fmtCompact(row.replacement_reserves)}</TableCell>
              <TableCell align="right">{fmtCompact(row.net_cash_flow)}</TableCell>
              <TableCell align="right">{fmtCompact(row.debt_service_a)}</TableCell>
              <TableCell align="right">{fmtCompact(row.debt_service_b)}</TableCell>
              <TableCell align="right">{fmtCompact(row.cash_flow_after_debt_a)}</TableCell>
              <TableCell align="right">{fmtCompact(row.cash_flow_after_debt_b)}</TableCell>
              <TableCell align="right">{fmtCompact(row.capex_spend)}</TableCell>
              <TableCell align="right">{fmtCompact(row.cash_flow_after_capex_a)}</TableCell>
              <TableCell align="right">{fmtCompact(row.cash_flow_after_capex_b)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

interface ProFormaTabProps {
  dealId: number
}

export function ProFormaTab({ dealId }: ProFormaTabProps) {
  const queryClient = useQueryClient()

  const { data: proForma, isLoading, isError, error } = useQuery({
    queryKey: ['deal', dealId, 'pro-forma'],
    queryFn: () => multifamilyService.getProForma(dealId),
  })

  const recomputeMutation = useMutation({
    mutationFn: () => multifamilyService.recomputeProForma(dealId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'pro-forma'] })
    },
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading pro forma" />
      </Box>
    )
  }

  if (isError) {
    return (
      <Alert severity="error">
        {(error as Error)?.message ?? 'Failed to load pro forma'}
      </Alert>
    )
  }

  const result = proForma as ProFormaResult
  const rows: MonthlyRow[] = result?.monthly_schedule ?? []

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h6">Pro Forma</Typography>
          {result?.computed_at && (
            <Typography variant="caption" color="text.secondary">
              Last computed: {new Date(result.computed_at).toLocaleString()}
            </Typography>
          )}
        </Box>
        <Button
          variant="outlined"
          size="small"
          startIcon={recomputeMutation.isPending ? <CircularProgress size={16} /> : <RefreshIcon />}
          onClick={() => recomputeMutation.mutate()}
          disabled={recomputeMutation.isPending}
          aria-label="Force recompute pro forma"
        >
          {recomputeMutation.isPending ? 'Recomputing…' : 'Force Recompute'}
        </Button>
      </Box>

      {recomputeMutation.isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(recomputeMutation.error as Error)?.message ?? 'Recompute failed'}
        </Alert>
      )}

      {/* Missing inputs warnings */}
      {result?.missing_inputs_a && result.missing_inputs_a.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          <strong>Scenario A missing inputs:</strong>{' '}
          {result.missing_inputs_a.join(', ')}
        </Alert>
      )}
      {result?.missing_inputs_b && result.missing_inputs_b.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          <strong>Scenario B missing inputs:</strong>{' '}
          {result.missing_inputs_b.join(', ')}
        </Alert>
      )}

      {rows.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            No pro forma data available. Ensure all required inputs are set and click Force Recompute.
          </Typography>
        </Paper>
      ) : (
        <>
          <ProFormaChart rows={rows} />
          <MonthlyTable rows={rows} />
        </>
      )}
    </Box>
  )
}

export default ProFormaTab
