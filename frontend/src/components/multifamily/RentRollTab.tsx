/**
 * RentRollTab — table of units + rent roll entries with add/edit/delete dialogs.
 * Displays RentRollSummary (Req 2.5) including Rent_Roll_Incomplete warning.
 *
 * Requirements: 2.1–2.6
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
  FormControl,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
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
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import { multifamilyService } from '@/services/api'
import { OccupancyStatus } from '@/types'
import type { MFUnit, RentRollEntry } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(num)
}

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(1)}%`
}

// ---------------------------------------------------------------------------
// Add / Edit Unit Dialog
// ---------------------------------------------------------------------------

interface UnitDialogProps {
  open: boolean
  dealId: number
  unit?: MFUnit
  onClose: () => void
}

const EMPTY_UNIT = {
  unit_identifier: '',
  unit_type: '',
  beds: 1,
  baths: 1,
  sqft: 0,
  occupancy_status: OccupancyStatus.VACANT,
}

function UnitDialog({ open, dealId, unit, onClose }: UnitDialogProps) {
  const queryClient = useQueryClient()
  const isEdit = !!unit
  const [form, setForm] = useState(
    unit
      ? {
          unit_identifier: unit.unit_identifier,
          unit_type: unit.unit_type,
          beds: unit.beds,
          baths: unit.baths,
          sqft: unit.sqft,
          occupancy_status: unit.occupancy_status,
        }
      : EMPTY_UNIT
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
    queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'rent-roll-summary'] })
  }

  const addMutation = useMutation({
    mutationFn: () => multifamilyService.addUnit(dealId, form),
    onSuccess: () => { invalidate(); onClose() },
  })

  const editMutation = useMutation({
    mutationFn: () => multifamilyService.updateUnit(dealId, unit!.id, form),
    onSuccess: () => { invalidate(); onClose() },
  })

  const validate = () => {
    const e: Record<string, string> = {}
    if (!form.unit_identifier.trim()) e.unit_identifier = 'Required'
    if (!form.unit_type.trim()) e.unit_type = 'Required'
    if (form.sqft <= 0) e.sqft = 'Must be > 0'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = () => {
    if (!validate()) return
    isEdit ? editMutation.mutate() : addMutation.mutate()
  }

  const mutation = isEdit ? editMutation : addMutation
  const isPending = mutation.isPending

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="unit-dialog-title">
      <DialogTitle id="unit-dialog-title">{isEdit ? 'Edit Unit' : 'Add Unit'}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {mutation.isError && (
            <Alert severity="error">{(mutation.error as Error)?.message ?? 'Error'}</Alert>
          )}
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Unit ID"
              value={form.unit_identifier}
              onChange={(e) => setForm((f) => ({ ...f, unit_identifier: e.target.value }))}
              error={!!errors.unit_identifier}
              helperText={errors.unit_identifier}
              required
              sx={{ flex: 1 }}
              inputProps={{ 'aria-label': 'Unit identifier' }}
            />
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
          </Box>
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Beds"
              type="number"
              value={form.beds}
              onChange={(e) => setForm((f) => ({ ...f, beds: parseInt(e.target.value) || 0 }))}
              inputProps={{ min: 0, 'aria-label': 'Bedrooms' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Baths"
              type="number"
              value={form.baths}
              onChange={(e) => setForm((f) => ({ ...f, baths: parseFloat(e.target.value) || 0 }))}
              inputProps={{ min: 0, step: 0.5, 'aria-label': 'Bathrooms' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="SqFt"
              type="number"
              value={form.sqft}
              onChange={(e) => setForm((f) => ({ ...f, sqft: parseInt(e.target.value) || 0 }))}
              error={!!errors.sqft}
              helperText={errors.sqft}
              inputProps={{ min: 1, 'aria-label': 'Square footage' }}
              sx={{ flex: 1 }}
            />
          </Box>
          <FormControl fullWidth>
            <InputLabel id="occupancy-label">Occupancy Status</InputLabel>
            <Select
              labelId="occupancy-label"
              value={form.occupancy_status}
              label="Occupancy Status"
              onChange={(e) =>
                setForm((f) => ({ ...f, occupancy_status: e.target.value as OccupancyStatus }))
              }
              inputProps={{ 'aria-label': 'Occupancy status' }}
            >
              {Object.values(OccupancyStatus).map((s) => (
                <MenuItem key={s} value={s}>{s}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isPending}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={isPending}
          startIcon={isPending ? <CircularProgress size={16} /> : undefined}
        >
          {isPending ? 'Saving…' : isEdit ? 'Save' : 'Add Unit'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Rent Roll Entry Dialog
// ---------------------------------------------------------------------------

interface RentRollDialogProps {
  open: boolean
  dealId: number
  unit: MFUnit
  entry?: RentRollEntry
  onClose: () => void
}

function RentRollDialog({ open, dealId, unit, entry, onClose }: RentRollDialogProps) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    current_rent: entry ? parseFloat(entry.current_rent) : 0,
    lease_start_date: entry?.lease_start_date ?? '',
    lease_end_date: entry?.lease_end_date ?? '',
    notes: entry?.notes ?? '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})

  const mutation = useMutation({
    mutationFn: () =>
      multifamilyService.setRentRollEntry(dealId, unit.id, {
        current_rent: form.current_rent,
        lease_start_date: form.lease_start_date || undefined,
        lease_end_date: form.lease_end_date || undefined,
        notes: form.notes || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'rent-roll-summary'] })
      onClose()
    },
  })

  const validate = () => {
    const e: Record<string, string> = {}
    if (form.current_rent < 0) e.current_rent = 'Must be ≥ 0'
    if (
      form.lease_start_date &&
      form.lease_end_date &&
      form.lease_end_date < form.lease_start_date
    ) {
      e.lease_end_date = 'End date must be on or after start date'
    }
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = () => {
    if (!validate()) return
    mutation.mutate()
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="rr-dialog-title">
      <DialogTitle id="rr-dialog-title">
        Rent Roll — Unit {unit.unit_identifier}
      </DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {mutation.isError && (
            <Alert severity="error">{(mutation.error as Error)?.message ?? 'Error'}</Alert>
          )}
          <TextField
            label="Current Rent ($/mo)"
            type="number"
            value={form.current_rent}
            onChange={(e) =>
              setForm((f) => ({ ...f, current_rent: parseFloat(e.target.value) || 0 }))
            }
            error={!!errors.current_rent}
            helperText={errors.current_rent}
            required
            inputProps={{ min: 0, step: 50, 'aria-label': 'Current rent' }}
          />
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Lease Start"
              type="date"
              value={form.lease_start_date}
              onChange={(e) => setForm((f) => ({ ...f, lease_start_date: e.target.value }))}
              InputLabelProps={{ shrink: true }}
              sx={{ flex: 1 }}
              inputProps={{ 'aria-label': 'Lease start date' }}
            />
            <TextField
              label="Lease End"
              type="date"
              value={form.lease_end_date}
              onChange={(e) => setForm((f) => ({ ...f, lease_end_date: e.target.value }))}
              error={!!errors.lease_end_date}
              helperText={errors.lease_end_date}
              InputLabelProps={{ shrink: true }}
              sx={{ flex: 1 }}
              inputProps={{ 'aria-label': 'Lease end date' }}
            />
          </Box>
          <TextField
            label="Notes"
            value={form.notes}
            onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
            multiline
            rows={2}
            inputProps={{ 'aria-label': 'Notes' }}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={mutation.isPending}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
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

interface RentRollTabProps {
  dealId: number
  unitCount: number
}

export function RentRollTab({ dealId, unitCount }: RentRollTabProps) {
  const queryClient = useQueryClient()
  const [addUnitOpen, setAddUnitOpen] = useState(false)
  const [editUnit, setEditUnit] = useState<MFUnit | null>(null)
  const [rentRollUnit, setRentRollUnit] = useState<MFUnit | null>(null)

  const { data: deal, isLoading: dealLoading } = useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => multifamilyService.getDeal(dealId),
  })

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['deal', dealId, 'rent-roll-summary'],
    queryFn: () => multifamilyService.getRentRollSummary(dealId),
  })

  const deleteMutation = useMutation({
    mutationFn: (unitId: number) => multifamilyService.deleteUnit(dealId, unitId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
      queryClient.invalidateQueries({ queryKey: ['deal', dealId, 'rent-roll-summary'] })
    },
  })

  if (dealLoading || summaryLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading rent roll" />
      </Box>
    )
  }

  // The deal response includes units and rent_roll_entries inline
  const units: MFUnit[] = (deal as any)?.units ?? []
  const rrMap: Record<number, RentRollEntry> = {}
  if ((deal as any)?.rent_roll_entries) {
    for (const rr of (deal as any).rent_roll_entries as RentRollEntry[]) {
      rrMap[rr.unit_id] = rr
    }
  }

  return (
    <Box>
      {/* Summary cards */}
      {summary && (
        <Box sx={{ mb: 3 }}>
          {summary.rent_roll_incomplete && (
            <Alert severity="warning" icon={<WarningAmberIcon />} sx={{ mb: 2 }}>
              Rent roll is incomplete — some units are missing rent roll entries.
            </Alert>
          )}
          <Grid container spacing={2}>
            {[
              { label: 'Total Units', value: String(summary.total_unit_count) },
              { label: 'Occupied', value: String(summary.occupied_unit_count) },
              { label: 'Vacant', value: String(summary.vacant_unit_count) },
              { label: 'Occupancy Rate', value: fmtPct(summary.occupancy_rate) },
              { label: 'Total In-Place Rent', value: fmt(summary.total_in_place_rent) },
              { label: 'Avg Rent / Occupied', value: fmt(summary.average_rent_per_occupied_unit) },
            ].map(({ label, value }) => (
              <Grid item xs={6} sm={4} md={2} key={label}>
                <Paper variant="outlined" sx={{ p: 1.5, textAlign: 'center' }}>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {label}
                  </Typography>
                  <Typography variant="subtitle1" fontWeight={600}>
                    {value}
                  </Typography>
                </Paper>
              </Grid>
            ))}
          </Grid>
        </Box>
      )}

      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">
          Units ({units.length} / {unitCount})
        </Typography>
        <Button
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          onClick={() => setAddUnitOpen(true)}
          aria-label="Add unit"
        >
          Add Unit
        </Button>
      </Box>

      {/* Units table */}
      <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="Rent roll table">
          <TableHead>
            <TableRow>
              <TableCell>Unit ID</TableCell>
              <TableCell>Type</TableCell>
              <TableCell align="right">Beds</TableCell>
              <TableCell align="right">Baths</TableCell>
              <TableCell align="right">SqFt</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right">Current Rent</TableCell>
              <TableCell>Lease Start</TableCell>
              <TableCell>Lease End</TableCell>
              <TableCell align="center">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {units.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">
                    No units yet. Add your first unit.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              units.map((unit) => {
                const rr = rrMap[unit.id]
                return (
                  <TableRow key={unit.id} hover>
                    <TableCell>{unit.unit_identifier}</TableCell>
                    <TableCell>{unit.unit_type}</TableCell>
                    <TableCell align="right">{unit.beds}</TableCell>
                    <TableCell align="right">{unit.baths}</TableCell>
                    <TableCell align="right">{unit.sqft.toLocaleString()}</TableCell>
                    <TableCell>
                      <Chip
                        label={unit.occupancy_status}
                        size="small"
                        color={
                          unit.occupancy_status === OccupancyStatus.OCCUPIED
                            ? 'success'
                            : unit.occupancy_status === OccupancyStatus.VACANT
                            ? 'warning'
                            : 'default'
                        }
                      />
                    </TableCell>
                    <TableCell align="right">{rr ? fmt(rr.current_rent) : '—'}</TableCell>
                    <TableCell>{rr?.lease_start_date ?? '—'}</TableCell>
                    <TableCell>{rr?.lease_end_date ?? '—'}</TableCell>
                    <TableCell align="center">
                      <Box sx={{ display: 'flex', gap: 0.5, justifyContent: 'center' }}>
                        <Tooltip title="Edit unit">
                          <IconButton
                            size="small"
                            onClick={() => setEditUnit(unit)}
                            aria-label={`Edit unit ${unit.unit_identifier}`}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Set rent roll entry">
                          <IconButton
                            size="small"
                            onClick={() => setRentRollUnit(unit)}
                            aria-label={`Set rent roll for unit ${unit.unit_identifier}`}
                          >
                            <AddIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Delete unit">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => deleteMutation.mutate(unit.id)}
                            disabled={deleteMutation.isPending}
                            aria-label={`Delete unit ${unit.unit_identifier}`}
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {deleteMutation.isError && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {(deleteMutation.error as Error)?.message ?? 'Failed to delete unit'}
        </Alert>
      )}

      {/* Dialogs */}
      <UnitDialog open={addUnitOpen} dealId={dealId} onClose={() => setAddUnitOpen(false)} />
      {editUnit && (
        <UnitDialog
          open
          dealId={dealId}
          unit={editUnit}
          onClose={() => setEditUnit(null)}
        />
      )}
      {rentRollUnit && (
        <RentRollDialog
          open
          dealId={dealId}
          unit={rentRollUnit}
          entry={rrMap[rentRollUnit.id]}
          onClose={() => setRentRollUnit(null)}
        />
      )}
    </Box>
  )
}

export default RentRollTab
