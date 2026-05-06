/**
 * SaleCompsTab — sale comps list + add/delete.
 * Displays Cap Rate and PPU min/median/average/max.
 * Shows Sale_Comps_Insufficient warning when < 3.
 *
 * Requirements: 4.1–4.5
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  IconButton,
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
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { multifamilyService } from '@/services/api'
import type { MFSaleComp, SaleCompRollup } from '@/types'

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

// ---------------------------------------------------------------------------
// Add Sale Comp Dialog
// ---------------------------------------------------------------------------

interface AddSaleCompDialogProps {
  open: boolean
  dealId: number
  onClose: () => void
}

const EMPTY_SALE_COMP = {
  address: '',
  unit_count: 0,
  status: '',
  sale_price: 0,
  close_date: '',
  observed_cap_rate: 0,
  distance_miles: '',
}

function AddSaleCompDialog({ open, dealId, onClose }: AddSaleCompDialogProps) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(EMPTY_SALE_COMP)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const mutation = useMutation({
    mutationFn: () =>
      multifamilyService.addSaleComp(dealId, {
        address: form.address,
        unit_count: form.unit_count,
        status: form.status,
        sale_price: form.sale_price,
        close_date: form.close_date,
        observed_cap_rate: form.observed_cap_rate,
        distance_miles: form.distance_miles ? parseFloat(form.distance_miles) : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'sale-comp-rollup'] })
      setForm(EMPTY_SALE_COMP)
      setErrors({})
      onClose()
    },
  })

  const validate = () => {
    const e: Record<string, string> = {}
    if (!form.address.trim()) e.address = 'Required'
    if (form.unit_count <= 0) e.unit_count = 'Must be > 0'
    if (!form.status.trim()) e.status = 'Required'
    if (form.sale_price <= 0) e.sale_price = 'Must be > 0'
    if (!form.close_date) e.close_date = 'Required'
    if (form.observed_cap_rate <= 0) e.observed_cap_rate = 'Must be > 0'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = () => {
    if (!validate()) return
    mutation.mutate()
  }

  const handleClose = () => {
    if (mutation.isPending) return
    setForm(EMPTY_SALE_COMP)
    setErrors({})
    mutation.reset()
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth aria-labelledby="add-sale-comp-dialog-title">
      <DialogTitle id="add-sale-comp-dialog-title">Add Sale Comp</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {mutation.isError && (
            <Alert severity="error">{(mutation.error as Error)?.message ?? 'Failed to add sale comp'}</Alert>
          )}
          <TextField
            label="Address"
            value={form.address}
            onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
            error={!!errors.address}
            helperText={errors.address}
            required
            fullWidth
            inputProps={{ 'aria-label': 'Sale comp address' }}
          />
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Units"
              type="number"
              value={form.unit_count}
              onChange={(e) => setForm((f) => ({ ...f, unit_count: parseInt(e.target.value) || 0 }))}
              error={!!errors.unit_count}
              helperText={errors.unit_count}
              required
              inputProps={{ min: 1, 'aria-label': 'Unit count' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Status"
              value={form.status}
              onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
              error={!!errors.status}
              helperText={errors.status ?? 'e.g. Sold, Active'}
              required
              sx={{ flex: 1 }}
              inputProps={{ 'aria-label': 'Property status' }}
            />
          </Box>
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Sale Price ($)"
              type="number"
              value={form.sale_price}
              onChange={(e) => setForm((f) => ({ ...f, sale_price: parseFloat(e.target.value) || 0 }))}
              error={!!errors.sale_price}
              helperText={errors.sale_price}
              required
              inputProps={{ min: 1, step: 1000, 'aria-label': 'Sale price' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Close Date"
              type="date"
              value={form.close_date}
              onChange={(e) => setForm((f) => ({ ...f, close_date: e.target.value }))}
              error={!!errors.close_date}
              helperText={errors.close_date}
              required
              InputLabelProps={{ shrink: true }}
              sx={{ flex: 1 }}
              inputProps={{ 'aria-label': 'Close date' }}
            />
          </Box>
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Cap Rate (decimal, e.g. 0.065)"
              type="number"
              value={form.observed_cap_rate}
              onChange={(e) => setForm((f) => ({ ...f, observed_cap_rate: parseFloat(e.target.value) || 0 }))}
              error={!!errors.observed_cap_rate}
              helperText={errors.observed_cap_rate}
              required
              inputProps={{ min: 0, step: 0.001, 'aria-label': 'Observed cap rate' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Distance (miles)"
              type="number"
              value={form.distance_miles}
              onChange={(e) => setForm((f) => ({ ...f, distance_miles: e.target.value }))}
              inputProps={{ min: 0, step: 0.1, 'aria-label': 'Distance in miles' }}
              sx={{ flex: 1 }}
            />
          </Box>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={mutation.isPending}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={mutation.isPending}
          startIcon={mutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {mutation.isPending ? 'Adding…' : 'Add Sale Comp'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Rollup Stats Card
// ---------------------------------------------------------------------------

interface StatCardProps {
  label: string
  min: string | null
  median: string | null
  average: string | null
  max: string | null
  formatter: (v: string | null) => string
}

function StatCard({ label, min, median, average, max, formatter }: StatCardProps) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2" color="text.secondary" gutterBottom>
        {label}
      </Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.5 }}>
        {[
          { key: 'Min', val: min },
          { key: 'Median', val: median },
          { key: 'Avg', val: average },
          { key: 'Max', val: max },
        ].map(({ key, val }) => (
          <Box key={key}>
            <Typography variant="caption" color="text.secondary">{key}</Typography>
            <Typography variant="body2" fontWeight={500}>{formatter(val)}</Typography>
          </Box>
        ))}
      </Box>
    </Paper>
  )
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

interface SaleCompsTabProps {
  dealId: number
}

export function SaleCompsTab({ dealId }: SaleCompsTabProps) {
  const queryClient = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)

  const { data: rollup, isLoading, isError, error } = useQuery({
    queryKey: ['deal', dealId, 'sale-comp-rollup'],
    queryFn: () => multifamilyService.getSaleCompRollup(dealId),
  })

  const deleteMutation = useMutation({
    mutationFn: (compId: number) => multifamilyService.deleteSaleComp(dealId, compId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'sale-comp-rollup'] })
    },
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading sale comps" />
      </Box>
    )
  }

  if (isError) {
    return (
      <Alert severity="error">
        {(error as Error)?.message ?? 'Failed to load sale comp rollup'}
      </Alert>
    )
  }

  const comps: MFSaleComp[] = (rollup as SaleCompRollup)?.comps ?? []

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h6">Sale Comps</Typography>
        <Button
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          onClick={() => setAddOpen(true)}
          aria-label="Add sale comp"
        >
          Add Sale Comp
        </Button>
      </Box>

      {/* Insufficient warning */}
      {rollup?.sale_comps_insufficient && (
        <Alert severity="warning" icon={<WarningAmberIcon />} sx={{ mb: 2 }}>
          Insufficient sale comps — at least 3 are required for reliable valuation statistics.
        </Alert>
      )}

      {/* Rollup stats */}
      {rollup && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} sm={6}>
            <StatCard
              label="Cap Rate"
              min={rollup.cap_rate_min}
              median={rollup.cap_rate_median}
              average={rollup.cap_rate_average}
              max={rollup.cap_rate_max}
              formatter={fmtPct}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <StatCard
              label="Price Per Unit (PPU)"
              min={rollup.ppu_min}
              median={rollup.ppu_median}
              average={rollup.ppu_average}
              max={rollup.ppu_max}
              formatter={fmtCurrency}
            />
          </Grid>
        </Grid>
      )}

      {/* Comps table */}
      {comps.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            No sale comps yet. Add comps to compute valuation statistics.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small" aria-label="Sale comps table">
            <TableHead>
              <TableRow>
                <TableCell>Address</TableCell>
                <TableCell align="right">Units</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Sale Price</TableCell>
                <TableCell>Close Date</TableCell>
                <TableCell align="right">Cap Rate</TableCell>
                <TableCell align="right">PPU</TableCell>
                <TableCell align="right">Distance</TableCell>
                <TableCell align="center">Delete</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {comps.map((comp: MFSaleComp) => (
                <TableRow key={comp.id} hover>
                  <TableCell>{comp.address}</TableCell>
                  <TableCell align="right">{comp.unit_count}</TableCell>
                  <TableCell>{comp.status}</TableCell>
                  <TableCell align="right">{fmtCurrency(comp.sale_price)}</TableCell>
                  <TableCell>{comp.close_date}</TableCell>
                  <TableCell align="right">{fmtPct(comp.observed_cap_rate)}</TableCell>
                  <TableCell align="right">{fmtCurrency(comp.observed_ppu)}</TableCell>
                  <TableCell align="right">
                    {comp.distance_miles ? `${parseFloat(comp.distance_miles).toFixed(1)} mi` : '—'}
                  </TableCell>
                  <TableCell align="center">
                    <Tooltip title="Delete sale comp">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => deleteMutation.mutate(comp.id)}
                        disabled={deleteMutation.isPending}
                        aria-label={`Delete sale comp at ${comp.address}`}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {deleteMutation.isError && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {(deleteMutation.error as Error)?.message ?? 'Failed to delete sale comp'}
        </Alert>
      )}

      <AddSaleCompDialog
        open={addOpen}
        dealId={dealId}
        onClose={() => setAddOpen(false)}
      />
    </Box>
  )
}

export default SaleCompsTab
