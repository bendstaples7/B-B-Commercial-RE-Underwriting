/**
 * FundingTab — add/edit/delete Funding_Sources (Cash, HELOC_1, HELOC_2).
 * Shows draw plan and Insufficient_Funding warning.
 *
 * Requirements: 7.1–7.6
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
  FormControl,
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
import { FundingSourceType } from '@/types'
import type { FundingSource } from '@/types'

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
// Add / Edit Funding Source Dialog
// ---------------------------------------------------------------------------

interface FundingSourceDialogProps {
  open: boolean
  dealId: number
  source?: FundingSource
  onClose: () => void
}

const EMPTY_FORM = {
  source_type: FundingSourceType.CASH as FundingSourceType,
  total_available: 0,
  interest_rate: 0,
  origination_fee_rate: 0,
}

function FundingSourceDialog({ open, dealId, source, onClose }: FundingSourceDialogProps) {
  const queryClient = useQueryClient()
  const isEdit = !!source

  const [form, setForm] = useState(
    source
      ? {
          source_type: source.source_type,
          total_available: parseFloat(source.total_available),
          interest_rate: parseFloat(source.interest_rate),
          origination_fee_rate: parseFloat(source.origination_fee_rate),
        }
      : EMPTY_FORM
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [apiError, setApiError] = useState<string | null>(null)

  const addMutation = useMutation({
    mutationFn: () =>
      multifamilyService.addFundingSource(dealId, {
        source_type: form.source_type,
        total_available: form.total_available,
        interest_rate: form.interest_rate,
        origination_fee_rate: form.origination_fee_rate,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
      setApiError(null)
      onClose()
    },
    onError: (err: Error) => {
      setApiError(err.message ?? 'Failed to add funding source')
    },
  })

  const editMutation = useMutation({
    mutationFn: () =>
      multifamilyService.updateFundingSource(dealId, source!.id, {
        total_available: form.total_available,
        interest_rate: form.interest_rate,
        origination_fee_rate: form.origination_fee_rate,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
      setApiError(null)
      onClose()
    },
    onError: (err: Error) => {
      setApiError(err.message ?? 'Failed to update funding source')
    },
  })

  const mutation = isEdit ? editMutation : addMutation

  const validate = () => {
    const e: Record<string, string> = {}
    if (form.total_available <= 0) e.total_available = 'Must be > 0'
    if (form.interest_rate < 0) e.interest_rate = 'Must be >= 0'
    if (form.origination_fee_rate < 0) e.origination_fee_rate = 'Must be >= 0'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const handleSubmit = () => {
    if (!validate()) return
    mutation.mutate()
  }

  const handleClose = () => {
    if (mutation.isPending) return
    setErrors({})
    setApiError(null)
    mutation.reset()
    onClose()
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="sm"
      fullWidth
      aria-labelledby="funding-source-dialog-title"
    >
      <DialogTitle id="funding-source-dialog-title">
        {isEdit ? 'Edit Funding Source' : 'Add Funding Source'}
      </DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {apiError && (
            <Alert severity="error">{apiError}</Alert>
          )}
          <FormControl fullWidth required disabled={isEdit}>
            <InputLabel id="source-type-label">Source Type</InputLabel>
            <Select
              labelId="source-type-label"
              value={form.source_type}
              label="Source Type"
              onChange={(e) =>
                setForm((f) => ({ ...f, source_type: e.target.value as FundingSourceType }))
              }
              inputProps={{ 'aria-label': 'Funding source type' }}
            >
              {Object.values(FundingSourceType).map((t) => (
                <MenuItem key={t} value={t}>{t}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Total Available ($)"
            type="number"
            value={form.total_available}
            onChange={(e) =>
              setForm((f) => ({ ...f, total_available: parseFloat(e.target.value) || 0 }))
            }
            error={!!errors.total_available}
            helperText={errors.total_available}
            required
            inputProps={{ min: 1, step: 1000, 'aria-label': 'Total available' }}
          />
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Interest Rate (decimal, e.g. 0.07)"
              type="number"
              value={form.interest_rate}
              onChange={(e) =>
                setForm((f) => ({ ...f, interest_rate: parseFloat(e.target.value) || 0 }))
              }
              error={!!errors.interest_rate}
              helperText={errors.interest_rate}
              inputProps={{ min: 0, step: 0.001, 'aria-label': 'Interest rate' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Origination Fee (decimal, e.g. 0.01)"
              type="number"
              value={form.origination_fee_rate}
              onChange={(e) =>
                setForm((f) => ({ ...f, origination_fee_rate: parseFloat(e.target.value) || 0 }))
              }
              error={!!errors.origination_fee_rate}
              helperText={errors.origination_fee_rate}
              inputProps={{ min: 0, step: 0.001, 'aria-label': 'Origination fee rate' }}
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
          {mutation.isPending ? 'Saving…' : isEdit ? 'Save' : 'Add'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

interface FundingTabProps {
  dealId: number
}

export function FundingTab({ dealId }: FundingTabProps) {
  const queryClient = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [editSource, setEditSource] = useState<FundingSource | null>(null)

  const { data: deal, isLoading } = useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => multifamilyService.getDeal(dealId),
  })

  const deleteMutation = useMutation({
    mutationFn: (sourceId: number) => multifamilyService.deleteFundingSource(dealId, sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
    },
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading funding sources" />
      </Box>
    )
  }

  const sources: FundingSource[] = deal?.funding_sources ?? []

  // Check for insufficient funding from pro forma result if available
  const proFormaResult = (deal as any)?.pro_forma_result
  const insufficientFunding =
    proFormaResult?.sources_and_uses_a?.shortfall > 0 ||
    proFormaResult?.sources_and_uses_b?.shortfall > 0

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h6">Funding Sources</Typography>
        <Button
          variant="contained"
          size="small"
          startIcon={<AddIcon />}
          onClick={() => setAddOpen(true)}
          aria-label="Add funding source"
        >
          Add Funding Source
        </Button>
      </Box>

      {/* Insufficient funding warning */}
      {insufficientFunding && (
        <Alert severity="warning" icon={<WarningAmberIcon />} sx={{ mb: 2 }}>
          Insufficient funding — total sources do not cover total uses. Review your funding sources.
        </Alert>
      )}

      {/* Sources table */}
      {sources.length === 0 ? (
        <Paper variant="outlined" sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            No funding sources yet. Add Cash, HELOC_1, or HELOC_2 sources.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small" aria-label="Funding sources table">
            <TableHead>
              <TableRow>
                <TableCell>Source Type</TableCell>
                <TableCell align="right">Total Available</TableCell>
                <TableCell align="right">Interest Rate</TableCell>
                <TableCell align="right">Origination Fee</TableCell>
                <TableCell align="center">Edit</TableCell>
                <TableCell align="center">Delete</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sources.map((src) => (
                <TableRow key={src.id} hover>
                  <TableCell>
                    <Typography variant="body2" fontWeight={500}>
                      {src.source_type}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">{fmtCurrency(src.total_available)}</TableCell>
                  <TableCell align="right">{fmtPct(src.interest_rate)}</TableCell>
                  <TableCell align="right">{fmtPct(src.origination_fee_rate)}</TableCell>
                  <TableCell align="center">
                    <Tooltip title="Edit funding source">
                      <IconButton
                        size="small"
                        onClick={() => setEditSource(src)}
                        aria-label={`Edit ${src.source_type} funding source`}
                      >
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                  <TableCell align="center">
                    <Tooltip title="Delete funding source">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => deleteMutation.mutate(src.id)}
                        disabled={deleteMutation.isPending}
                        aria-label={`Delete ${src.source_type} funding source`}
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
          {(deleteMutation.error as Error)?.message ?? 'Failed to delete funding source'}
        </Alert>
      )}

      {/* Add dialog */}
      <FundingSourceDialog
        open={addOpen}
        dealId={dealId}
        onClose={() => setAddOpen(false)}
      />

      {/* Edit dialog */}
      {editSource && (
        <FundingSourceDialog
          open
          dealId={dealId}
          source={editSource}
          onClose={() => setEditSource(null)}
        />
      )}
    </Box>
  )
}

export default FundingTab
