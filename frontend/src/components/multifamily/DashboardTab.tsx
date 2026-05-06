/**
 * DashboardTab — side-by-side Scenario_A / Scenario_B cards with every
 * field from Req 11.1. When a scenario has missing_inputs, renders summary
 * fields as "—" and displays the missing_inputs list.
 *
 * Requirements: 11.1, 11.2
 */
import { useQuery } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Card,
  CardContent,
  CardHeader,
  CircularProgress,
  Divider,
  Grid,
  Typography,
} from '@mui/material'
import { multifamilyService } from '@/services/api'
import { DealScenario } from '@/types'
import type { Dashboard, DashboardScenario } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCurrency(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

function fmtPct(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return `${(num * 100).toFixed(2)}%`
}

function fmtNum(value: string | number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return num.toFixed(decimals)
}

// ---------------------------------------------------------------------------
// Field Row
// ---------------------------------------------------------------------------

interface FieldRowProps {
  label: string
  value: string
}

function FieldRow({ label, value }: FieldRowProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        py: 0.5,
        borderBottom: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>
        {label}
      </Typography>
      <Typography variant="body2" fontWeight={500} sx={{ textAlign: 'right' }}>
        {value}
      </Typography>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Section Header
// ---------------------------------------------------------------------------

function SectionHeader({ title }: { title: string }) {
  return (
    <Typography
      variant="caption"
      color="text.secondary"
      sx={{
        display: 'block',
        mt: 2,
        mb: 0.5,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
        fontWeight: 600,
      }}
    >
      {title}
    </Typography>
  )
}

// ---------------------------------------------------------------------------
// Scenario Card
// ---------------------------------------------------------------------------

interface ScenarioCardProps {
  scenario: DashboardScenario
}

function ScenarioCard({ scenario }: ScenarioCardProps) {
  const hasMissingInputs = scenario.missing_inputs.length > 0
  const dash = '—'

  // When missing inputs, computed fields show "—"
  const computed = (
    v: string | null | undefined,
    formatter: (x: string | null | undefined) => string
  ) => (hasMissingInputs ? dash : formatter(v))

  const title =
    scenario.scenario === DealScenario.A
      ? 'Scenario A — Construction-to-Perm'
      : 'Scenario B — Self-Funded Reno'

  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardHeader
        title={title}
        titleTypographyProps={{ variant: 'subtitle1', fontWeight: 600 }}
        sx={{ pb: 0 }}
      />
      <CardContent>
        {hasMissingInputs && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <strong>Missing inputs:</strong> {scenario.missing_inputs.join(', ')}
          </Alert>
        )}

        {/* Loan Terms */}
        <SectionHeader title="Loan Terms" />
        <FieldRow label="Purchase Price" value={fmtCurrency(scenario.purchase_price)} />
        <FieldRow label="Loan Amount" value={computed(scenario.loan_amount, fmtCurrency)} />
        <FieldRow label="Interest Rate" value={computed(scenario.interest_rate, fmtPct)} />
        <FieldRow
          label="Amortization (years)"
          value={
            hasMissingInputs
              ? dash
              : scenario.amort_years != null
              ? String(scenario.amort_years)
              : dash
          }
        />
        <FieldRow
          label="IO Period (months)"
          value={
            hasMissingInputs
              ? dash
              : scenario.io_period_months != null
              ? String(scenario.io_period_months)
              : dash
          }
        />

        {/* NOI & DSCR */}
        <SectionHeader title="NOI & DSCR" />
        <FieldRow label="In-Place NOI" value={computed(scenario.in_place_noi, fmtCurrency)} />
        <FieldRow label="Stabilized NOI" value={computed(scenario.stabilized_noi, fmtCurrency)} />
        <FieldRow
          label="In-Place DSCR"
          value={computed(scenario.in_place_dscr, (v) => fmtNum(v, 2))}
        />
        <FieldRow
          label="Stabilized DSCR"
          value={computed(scenario.stabilized_dscr, (v) => fmtNum(v, 2))}
        />

        {/* Ratios */}
        <SectionHeader title="Ratios" />
        <FieldRow
          label="Price-to-Rent Ratio"
          value={computed(scenario.price_to_rent_ratio, (v) => fmtNum(v, 2))}
        />

        {/* Valuation at Cap Rate */}
        <SectionHeader title="Valuation at Cap Rate" />
        <FieldRow label="Min" value={computed(scenario.valuation_at_cap_rate_min, fmtCurrency)} />
        <FieldRow
          label="Median"
          value={computed(scenario.valuation_at_cap_rate_median, fmtCurrency)}
        />
        <FieldRow
          label="Average"
          value={computed(scenario.valuation_at_cap_rate_average, fmtCurrency)}
        />
        <FieldRow label="Max" value={computed(scenario.valuation_at_cap_rate_max, fmtCurrency)} />

        {/* Valuation at PPU */}
        <SectionHeader title="Valuation at PPU" />
        <FieldRow label="Min" value={computed(scenario.valuation_at_ppu_min, fmtCurrency)} />
        <FieldRow label="Median" value={computed(scenario.valuation_at_ppu_median, fmtCurrency)} />
        <FieldRow label="Average" value={computed(scenario.valuation_at_ppu_average, fmtCurrency)} />
        <FieldRow label="Max" value={computed(scenario.valuation_at_ppu_max, fmtCurrency)} />

        {/* Sources & Uses */}
        <SectionHeader title="Sources & Uses" />
        <FieldRow
          label="Total Uses"
          value={computed(scenario.sources_and_uses?.total_uses, fmtCurrency)}
        />
        <FieldRow
          label="Total Sources"
          value={computed(scenario.sources_and_uses?.total_sources, fmtCurrency)}
        />
        <FieldRow
          label="Initial Cash Investment"
          value={computed(scenario.initial_cash_investment, fmtCurrency)}
        />

        {/* Cash Flow */}
        <SectionHeader title="Cash Flow" />
        <FieldRow
          label="Month 1 Net CF"
          value={computed(scenario.month_1_net_cash_flow, fmtCurrency)}
        />
        <FieldRow
          label="Month 24 Net CF"
          value={computed(scenario.month_24_net_cash_flow, fmtCurrency)}
        />
        <FieldRow
          label="Cash-on-Cash Return"
          value={computed(scenario.cash_on_cash_return, fmtPct)}
        />

        <Divider sx={{ mt: 2 }} />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

interface DashboardTabProps {
  dealId: number
}

export function DashboardTab({ dealId }: DashboardTabProps) {
  const { data: dashboard, isLoading, isError, error } = useQuery({
    queryKey: ['deal', dealId, 'dashboard'],
    queryFn: () => multifamilyService.getDashboard(dealId),
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading dashboard" />
      </Box>
    )
  }

  if (isError) {
    return (
      <Alert severity="error">
        {(error as Error)?.message ?? 'Failed to load dashboard'}
      </Alert>
    )
  }

  const data = dashboard as Dashboard

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 3 }}>Dashboard</Typography>
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <ScenarioCard scenario={data.scenario_a} />
        </Grid>
        <Grid item xs={12} md={6}>
          <ScenarioCard scenario={data.scenario_b} />
        </Grid>
      </Grid>
    </Box>
  )
}

export default DashboardTab
