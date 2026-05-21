/**
 * RehabPlanTab — per-unit rehab entry editor with Renovate_Flag toggle.
 * Monthly rollup bar chart. Shows Stabilizes_After_Horizon warning flag.
 *
 * Requirements: 5.1–5.7
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  Paper,
  Switch,
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
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { multifamilyService } from '@/services/api'
import type { MFUnit, RehabPlanEntry, RehabMonthlyRollup } from '@/types'

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

// ---------------------------------------------------------------------------
// Edit Rehab Dialog
// ---------------------------------------------------------------------------

interface EditRehabDialogProps {
  open: boolean
  dealId: number
  unit: MFUnit
  entry: RehabPlanEntry | undefined
  onClose: () => void
}

function EditRehabDialog({ open, dealId, unit, entry, onClose }: EditRehabDialogProps) {
  const queryClient = useQueryClient()

  const [form, setForm] = useState({
    renovate_flag: entry?.renovate_flag ?? false,
    current_rent: entry ? parseFloat(entry.current_rent) : 0,
    suggested_post_reno_rent: entry?.suggested_post_reno_rent
      ? parseFloat(entry.suggested_post_reno_rent)
      : 0,
    underwritten_post_reno_rent: entry?.underwritten_post_reno_rent
      ? parseFloat(entry.underwritten_post_reno_rent)
      : 0,
    rehab_start_month: entry?.rehab_start_month ?? 1,
    downtime_months: entry?.downtime_months ?? 1,
    rehab_budget: entry?.rehab_budget ? parseFloat(entry.rehab_budget) : 0,
    scope_notes: entry?.scope_notes ?? '',
  })

  const mutation = useMutation({
    mutationFn: () =>
      multifamilyService.setRehabPlanEntry(dealId, unit.id, {
        renovate_flag: form.renovate_flag,
        current_rent: form.current_rent,
        suggested_post_reno_rent: form.suggested_post_reno_rent || undefined,
        underwritten_post_reno_rent: form.underwritten_post_reno_rent || undefined,
        rehab_start_month: form.renovate_flag ? form.rehab_start_month : undefined,
        downtime_months: form.renovate_flag ? form.downtime_months : undefined,
        rehab_budget: form.renovate_flag ? form.rehab_budget : undefined,
        scope_notes: form.scope_notes || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'rehab-rollup'] })
      onClose()
    },
  })

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="edit-rehab-dialog-title">
      <DialogTitle id="edit-rehab-dialog-title">
        Rehab Plan — Unit {unit.unit_identifier}
      </DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {mutation.isError && (
            <Alert severity="error">{(mutation.error as Error)?.message ?? 'Save failed'}</Alert>
          )}

          <FormControlLabel
            control={
              <Switch
                checked={form.renovate_flag}
                onChange={(e) => setForm((f) => ({ ...f, renovate_flag: e.target.checked }))}
                inputProps={{ 'aria-label': 'Renovate flag' }}
              />
            }
            label="Renovate this unit"
          />

          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Current Rent ($/mo)"
              type="number"
              value={form.current_rent}
              onChange={(e) => setForm((f) => ({ ...f, current_rent: parseFloat(e.target.value) || 0 }))}
              inputProps={{ min: 0, step: 50, 'aria-label': 'Current rent' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Suggested Post-Reno Rent"
              type="number"
              value={form.suggested_post_reno_rent}
              onChange={(e) =>
                setForm((f) => ({ ...f, suggested_post_reno_rent: parseFloat(e.target.value) || 0 }))
              }
              inputProps={{ min: 0, step: 50, 'aria-label': 'Suggested post-reno rent' }}
              sx={{ flex: 1 }}
            />
          </Box>

          <TextField
            label="Underwritten Post-Reno Rent ($/mo)"
            type="number"
            value={form.underwritten_post_reno_rent}
            onChange={(e) =>
              setForm((f) => ({ ...f, underwritten_post_reno_rent: parseFloat(e.target.value) || 0 }))
            }
            inputProps={{ min: 0, step: 50, 'aria-label': 'Underwritten post-reno rent' }}
          />

          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Rehab Start Month (1–24)"
              type="number"
              value={form.rehab_start_month}
              onChange={(e) =>
                setForm((f) => ({ ...f, rehab_start_month: parseInt(e.target.value) || 1 }))
              }
              disabled={!form.renovate_flag}
              inputProps={{ min: 1, max: 24, 'aria-label': 'Rehab start month' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Downtime (months)"
              type="number"
              value={form.downtime_months}
              onChange={(e) =>
                setForm((f) => ({ ...f, downtime_months: parseInt(e.target.value) || 1 }))
              }
              disabled={!form.renovate_flag}
              inputProps={{ min: 0, 'aria-label': 'Downtime months' }}
              sx={{ flex: 1 }}
            />
          </Box>

          <TextField
            label="Rehab Budget ($)"
            type="number"
            value={form.rehab_budget}
            onChange={(e) => setForm((f) => ({ ...f, rehab_budget: parseFloat(e.target.value) || 0 }))}
            disabled={!form.renovate_flag}
            inputProps={{ min: 0, step: 500, 'aria-label': 'Rehab budget' }}
          />

          <TextField
            label="Scope Notes"
            value={form.scope_notes}
            onChange={(e) => setForm((f) => ({ ...f, scope_notes: e.target.value }))}
            multiline
            rows={3}
            inputProps={{ 'aria-label': 'Scope notes' }}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={mutation.isPending}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          startIcon={mutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {mutation.isPending ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

interface RehabPlanTabProps {
  dealId: number
}

export function RehabPlanTab({ dealId }: RehabPlanTabProps) {
  const [editUnit, setEditUnit] = useState<MFUnit | null>(null)

  const { data: deal, isLoading: dealLoading } = useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => multifamilyService.getDeal(dealId),
  })

  const { data: rollup, isLoading: rollupLoading } = useQuery({
    queryKey: ['deal', dealId, 'rehab-rollup'],
    queryFn: () => multifamilyService.getRehabRollup(dealId),
  })

  if (dealLoading || rollupLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading rehab plan" />
      </Box>
    )
  }

  const units: MFUnit[] = deal?.units ?? []
  const rehabEntries: RehabPlanEntry[] = deal?.rehab_plan_entries ?? []
  const rehabMap: Record<number, RehabPlanEntry> = {}
  for (const e of rehabEntries) {
    rehabMap[e.unit_id] = e
  }

  const chartData = (rollup ?? []).map((row: RehabMonthlyRollup) => ({
    month: row.month,
    starting_rehab: row.units_starting_rehab_count,
    offline: row.units_offline_count,
    stabilizing: row.units_stabilizing_count,
    capex: parseFloat(row.capex_spend) || 0,
  }))

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 3 }}>Rehab Plan</Typography>

      {/* Units table */}
      <TableContainer component={Paper} variant="outlined" sx={{ mb: 4 }}>
        <Table size="small" aria-label="Rehab plan table">
          <TableHead>
            <TableRow>
              <TableCell>Unit ID</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Renovate?</TableCell>
              <TableCell align="right">Start Month</TableCell>
              <TableCell align="right">Downtime</TableCell>
              <TableCell align="right">Stabilized Month</TableCell>
              <TableCell align="right">Budget</TableCell>
              <TableCell>Scope</TableCell>
              <TableCell>Warning</TableCell>
              <TableCell align="center">Edit</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {units.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">No units found.</Typography>
                </TableCell>
              </TableRow>
            ) : (
              units.map((unit) => {
                const entry = rehabMap[unit.id]
                return (
                  <TableRow key={unit.id} hover>
                    <TableCell>{unit.unit_identifier}</TableCell>
                    <TableCell>{unit.unit_type}</TableCell>
                    <TableCell>
                      <Chip
                        label={entry?.renovate_flag ? 'Yes' : 'No'}
                        size="small"
                        color={entry?.renovate_flag ? 'primary' : 'default'}
                      />
                    </TableCell>
                    <TableCell align="right">{entry?.rehab_start_month ?? '—'}</TableCell>
                    <TableCell align="right">
                      {entry?.downtime_months != null ? `${entry.downtime_months} mo` : '—'}
                    </TableCell>
                    <TableCell align="right">{entry?.stabilized_month ?? '—'}</TableCell>
                    <TableCell align="right">{entry ? fmtCurrency(entry.rehab_budget) : '—'}</TableCell>
                    <TableCell
                      sx={{
                        maxWidth: 160,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      <Tooltip title={entry?.scope_notes ?? ''}>
                        <span>{entry?.scope_notes ?? '—'}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      {entry?.stabilizes_after_horizon && (
                        <Chip
                          icon={<WarningAmberIcon />}
                          label="Stabilizes after horizon"
                          size="small"
                          color="warning"
                        />
                      )}
                    </TableCell>
                    <TableCell align="center">
                      <Tooltip title="Edit rehab plan">
                        <IconButton
                          size="small"
                          onClick={() => setEditUnit(unit)}
                          aria-label={`Edit rehab plan for unit ${unit.unit_identifier}`}
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Monthly rollup chart */}
      {chartData.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
            Monthly Rehab Activity (Months 1–24)
          </Typography>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 48, left: 0, bottom: 16 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="month"
                label={{ value: 'Month', position: 'insideBottom', offset: -8 }}
              />
              <YAxis
                yAxisId="units"
                allowDecimals={false}
                label={{ value: 'Units', angle: -90, position: 'insideLeft' }}
              />
              <YAxis
                yAxisId="capex"
                orientation="right"
                tickFormatter={(v: number) =>
                  new Intl.NumberFormat('en-US', {
                    style: 'currency',
                    currency: 'USD',
                    notation: 'compact',
                    maximumFractionDigits: 1,
                  }).format(v)
                }
                label={{ value: 'CapEx', angle: 90, position: 'insideRight' }}
              />
              <RechartsTooltip
                formatter={(value: number, name: string) => {
                  if (name === 'CapEx Spend') return [fmtCurrency(value), name]
                  return [value, name]
                }}
              />
              <Legend verticalAlign="top" />
              <Bar yAxisId="units" dataKey="starting_rehab" name="Starting Rehab" fill="#1976d2" />
              <Bar yAxisId="units" dataKey="offline" name="Offline" fill="#ed6c02" />
              <Bar yAxisId="units" dataKey="stabilizing" name="Stabilizing" fill="#2e7d32" />
              <Line
                yAxisId="capex"
                type="monotone"
                dataKey="capex"
                name="CapEx Spend"
                stroke="#9c27b0"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </Paper>
      )}

      {/* Edit dialog */}
      {editUnit && (
        <EditRehabDialog
          open
          dealId={dealId}
          unit={editUnit}
          entry={rehabMap[editUnit.id]}
          onClose={() => setEditUnit(null)}
        />
      )}
    </Box>
  )
}

export default RehabPlanTab
