/**
 * MarketRentsTab — per-unit-type assumption editor + rent comps list.
 * Auto-computes rent_per_sqft. Shows rollups (avg/median/avg_per_sqft).
 *
 * Requirements: 3.1–3.5
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
  Divider,
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
import SaveIcon from '@mui/icons-material/Save'
import { multifamilyService } from '@/services/api'
import type { RentCompRollup, RentComp } from '@/types'

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

function fmtDecimal(value: string | number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return num.toFixed(decimals)
}

// ---------------------------------------------------------------------------
// Add Comp Dialog
// ---------------------------------------------------------------------------

interface AddCompDialogProps {
  open: boolean
  dealId: number
  onClose: () => void
}

const EMPTY_COMP = {
  address: '',
  neighborhood: '',
  unit_type: '',
  observed_rent: 0,
  sqft: 0,
  observation_date: '',
  source_url: '',
}

function AddCompDialog({ open, dealId, onClose }: AddCompDialogProps) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(EMPTY_COMP)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const mutation = useMutation({
    mutationFn: () =>
      multifamilyService.addRentComp(dealId, {
        address: form.address,
        neighborhood: form.neighborhood || undefined,
        unit_type: form.unit_type,
        observed_rent: form.observed_rent,
        sqft: form.sqft,
        observation_date: form.observation_date,
        source_url: form.source_url || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'rent-comp-rollup'] })
      setForm(EMPTY_COMP)
      setErrors({})
      onClose()
    },
  })

  const validate = () => {
    const e: Record<string, string> = {}
    if (!form.address.trim()) e.address = 'Required'
    if (!form.unit_type.trim()) e.unit_type = 'Required'
    if (form.observed_rent <= 0) e.observed_rent = 'Must be > 0'
    if (form.sqft <= 0) e.sqft = 'Must be > 0'
    if (!form.observation_date) e.observation_date = 'Required'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = () => {
    if (!validate()) return
    mutation.mutate()
  }

  const handleClose = () => {
    if (mutation.isPending) return
    setForm(EMPTY_COMP)
    setErrors({})
    mutation.reset()
    onClose()
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth aria-labelledby="add-comp-dialog-title">
      <DialogTitle id="add-comp-dialog-title">Add Rent Comp</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {mutation.isError && (
            <Alert severity="error">{(mutation.error as Error)?.message ?? 'Failed to add comp'}</Alert>
          )}
          <TextField
            label="Address"
            value={form.address}
            onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
            error={!!errors.address}
            helperText={errors.address}
            required
            fullWidth
            inputProps={{ 'aria-label': 'Comp address' }}
          />
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Unit Type"
              value={form.unit_type}
              onChange={(e) => setForm((f) => ({ ...f, unit_type: e.target.value }))}
              error={!!errors.unit_type}
              helperText={errors.unit_type ?? 'e.g. 2BR/1BA'}
              required
              sx={{ flex: 1 }}
              inputProps={{ 'aria-label': 'Unit type' }}
            />
            <TextField
              label="Neighborhood"
              value={form.neighborhood}
              onChange={(e) => setForm((f) => ({ ...f, neighborhood: e.target.value }))}
              sx={{ flex: 1 }}
              inputProps={{ 'aria-label': 'Neighborhood' }}
            />
          </Box>
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Observed Rent ($/mo)"
              type="number"
              value={form.observed_rent}
              onChange={(e) => setForm((f) => ({ ...f, observed_rent: parseFloat(e.target.value) || 0 }))}
              error={!!errors.observed_rent}
              helperText={errors.observed_rent}
              required
              inputProps={{ min: 1, step: 50, 'aria-label': 'Observed rent' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="SqFt"
              type="number"
              value={form.sqft}
              onChange={(e) => setForm((f) => ({ ...f, sqft: parseInt(e.target.value) || 0 }))}
              error={!!errors.sqft}
              helperText={errors.sqft}
              required
              inputProps={{ min: 1, 'aria-label': 'Square footage' }}
              sx={{ flex: 1 }}
            />
          </Box>
          <TextField
            label="Observation Date"
            type="date"
            value={form.observation_date}
            onChange={(e) => setForm((f) => ({ ...f, observation_date: e.target.value }))}
            error={!!errors.observation_date}
            helperText={errors.observation_date}
            required
            InputLabelProps={{ shrink: true }}
            inputProps={{ 'aria-label': 'Observation date' }}
          />
          <TextField
            label="Source URL"
            value={form.source_url}
            onChange={(e) => setForm((f) => ({ ...f, source_url: e.target.value }))}
            inputProps={{ 'aria-label': 'Source URL' }}
          />
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
          {mutation.isPending ? 'Adding…' : 'Add Comp'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Assumption Editor (inline per unit type group)
// ---------------------------------------------------------------------------

interface AssumptionEditorProps {
  dealId: number
  unitType: string
  targetRent: string | null
  postRenoTargetRent: string | null
}

function AssumptionEditor({ dealId, unitType, targetRent, postRenoTargetRent }: AssumptionEditorProps) {
  const queryClient = useQueryClient()
  const [target, setTarget] = useState(targetRent ? parseFloat(targetRent) : 0)
  const [postReno, setPostReno] = useState(postRenoTargetRent ? parseFloat(postRenoTargetRent) : 0)

  const mutation = useMutation({
    mutationFn: () =>
      multifamilyService.setMarketRentAssumption(dealId, unitType, {
        target_rent: target || undefined,
        post_reno_target_rent: postReno || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'rent-comp-rollup'] })
    },
  })

  return (
    <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap', mt: 1 }}>
      <TextField
        label="Target Rent ($/mo)"
        type="number"
        value={target}
        onChange={(e) => setTarget(parseFloat(e.target.value) || 0)}
        size="small"
        inputProps={{ min: 0, step: 50, 'aria-label': `Target rent for ${unitType}` }}
        sx={{ width: 180 }}
      />
      <TextField
        label="Post-Reno Target Rent ($/mo)"
        type="number"
        value={postReno}
        onChange={(e) => setPostReno(parseFloat(e.target.value) || 0)}
        size="small"
        inputProps={{ min: 0, step: 50, 'aria-label': `Post-reno target rent for ${unitType}` }}
        sx={{ width: 220 }}
      />
      <Button
        variant="outlined"
        size="small"
        startIcon={mutation.isPending ? <CircularProgress size={14} /> : <SaveIcon />}
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        aria-label={`Save market rent assumptions for ${unitType}`}
      >
        {mutation.isPending ? 'Saving…' : 'Save'}
      </Button>
      {mutation.isError && (
        <Alert severity="error" sx={{ py: 0 }}>
          {(mutation.error as Error)?.message ?? 'Save failed'}
        </Alert>
      )}
      {mutation.isSuccess && (
        <Alert severity="success" sx={{ py: 0 }}>Saved</Alert>
      )}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Unit Type Group
// ---------------------------------------------------------------------------

interface UnitTypeGroupProps {
  dealId: number
  rollup: RentCompRollup
  onAddComp: () => void
}

function UnitTypeGroup({ dealId, rollup, onAddComp }: UnitTypeGroupProps) {
  const queryClient = useQueryClient()

  const deleteMutation = useMutation({
    mutationFn: (compId: number) => multifamilyService.deleteRentComp(dealId, compId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'rent-comp-rollup'] })
    },
  })

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle1" fontWeight={600}>
          {rollup.unit_type}
        </Typography>
        <Button
          size="small"
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={onAddComp}
          aria-label={`Add rent comp for ${rollup.unit_type}`}
        >
          Add Comp
        </Button>
      </Box>

      {/* Rollup stats */}
      <Box sx={{ display: 'flex', gap: 3, mb: 2, flexWrap: 'wrap' }}>
        <Box>
          <Typography variant="caption" color="text.secondary">Avg Rent</Typography>
          <Typography variant="body2" fontWeight={500}>{fmtCurrency(rollup.average_observed_rent)}</Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary">Median Rent</Typography>
          <Typography variant="body2" fontWeight={500}>{fmtCurrency(rollup.median_observed_rent)}</Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary">Avg $/SqFt</Typography>
          <Typography variant="body2" fontWeight={500}>
            {rollup.average_rent_per_sqft ? `$${fmtDecimal(rollup.average_rent_per_sqft)}` : '—'}
          </Typography>
        </Box>
      </Box>

      {/* Assumption editor */}
      <AssumptionEditor
        dealId={dealId}
        unitType={rollup.unit_type}
        targetRent={null}
        postRenoTargetRent={null}
      />

      <Divider sx={{ my: 2 }} />

      {/* Comps table */}
      {rollup.comps.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
          No comps yet for this unit type.
        </Typography>
      ) : (
        <TableContainer>
          <Table size="small" aria-label={`Rent comps for ${rollup.unit_type}`}>
            <TableHead>
              <TableRow>
                <TableCell>Address</TableCell>
                <TableCell>Neighborhood</TableCell>
                <TableCell align="right">Rent</TableCell>
                <TableCell align="right">SqFt</TableCell>
                <TableCell align="right">$/SqFt</TableCell>
                <TableCell>Date</TableCell>
                <TableCell align="center">Delete</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rollup.comps.map((comp: RentComp) => (
                <TableRow key={comp.id} hover>
                  <TableCell>{comp.address}</TableCell>
                  <TableCell>{comp.neighborhood ?? '—'}</TableCell>
                  <TableCell align="right">{fmtCurrency(comp.observed_rent)}</TableCell>
                  <TableCell align="right">{comp.sqft.toLocaleString()}</TableCell>
                  <TableCell align="right">
                    {comp.rent_per_sqft ? `$${fmtDecimal(comp.rent_per_sqft)}` : '—'}
                  </TableCell>
                  <TableCell>{comp.observation_date}</TableCell>
                  <TableCell align="center">
                    <Tooltip title="Delete comp">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => deleteMutation.mutate(comp.id)}
                        disabled={deleteMutation.isPending}
                        aria-label={`Delete comp at ${comp.address}`}
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
          {(deleteMutation.error as Error)?.message ?? 'Failed to delete comp'}
        </Alert>
      )}
    </Paper>
  )
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

interface MarketRentsTabProps {
  dealId: number
}

export function MarketRentsTab({ dealId }: MarketRentsTabProps) {
  const [addCompOpen, setAddCompOpen] = useState(false)

  const { data: rollups, isLoading, isError, error } = useQuery({
    queryKey: ['deal', dealId, 'rent-comp-rollup'],
    queryFn: () => multifamilyService.getRentCompRollup(dealId),
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading market rents" />
      </Box>
    )
  }

  if (isError) {
    return (
      <Alert severity="error">
        {(error as Error)?.message ?? 'Failed to load rent comp rollup'}
      </Alert>
    )
  }

  const groups = rollups ?? []

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h6">Market Rents &amp; Rent Comps</Typography>
        <Button
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          onClick={() => setAddCompOpen(true)}
          aria-label="Add rent comp"
        >
          Add Comp
        </Button>
      </Box>

      {groups.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            No rent comps yet. Add comps to see rollup statistics by unit type.
          </Typography>
        </Paper>
      ) : (
        groups.map((rollup) => (
          <UnitTypeGroup
            key={rollup.unit_type}
            dealId={dealId}
            rollup={rollup}
            onAddComp={() => setAddCompOpen(true)}
          />
        ))
      )}

      <AddCompDialog
        open={addCompOpen}
        dealId={dealId}
        onClose={() => setAddCompOpen(false)}
      />
    </Box>
  )
}

export default MarketRentsTab
