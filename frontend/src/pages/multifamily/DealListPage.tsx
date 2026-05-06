/**
 * DealListPage — lists all multifamily deals for the current user and
 * provides a "Create Deal" dialog wired to POST /api/multifamily/deals.
 *
 * Requirements: 1.5, 14.1
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
  Alert,
  Chip,
  Tooltip,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { multifamilyService } from '@/services/api'
import type { DealCreatePayload, DealSummary } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCurrency(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function statusColor(status: string): 'default' | 'primary' | 'success' | 'warning' {
  switch (status?.toLowerCase()) {
    case 'active':
      return 'success'
    case 'under_review':
      return 'primary'
    case 'draft':
      return 'warning'
    default:
      return 'default'
  }
}

// ---------------------------------------------------------------------------
// Create Deal Dialog
// ---------------------------------------------------------------------------

interface CreateDealDialogProps {
  open: boolean
  onClose: () => void
  onCreated: (dealId: number) => void
}

const EMPTY_FORM: DealCreatePayload = {
  property_address: '',
  unit_count: 5,
  purchase_price: 0,
  close_date: '',
  property_city: '',
  property_state: '',
  property_zip: '',
}

function CreateDealDialog({ open, onClose, onCreated }: CreateDealDialogProps) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<DealCreatePayload>(EMPTY_FORM)
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof DealCreatePayload, string>>>({})

  const mutation = useMutation({
    mutationFn: (payload: DealCreatePayload) => multifamilyService.createDeal(payload),
    onSuccess: (deal) => {
      queryClient.invalidateQueries({ queryKey: ['multifamily', 'deals'] })
      setForm(EMPTY_FORM)
      setFieldErrors({})
      onCreated(deal.id)
    },
  })

  const validate = (): boolean => {
    const errors: Partial<Record<keyof DealCreatePayload, string>> = {}
    if (!form.property_address.trim()) errors.property_address = 'Address is required'
    if (!form.unit_count || form.unit_count < 5) errors.unit_count = 'Must be at least 5 units'
    if (!form.purchase_price || form.purchase_price <= 0) errors.purchase_price = 'Must be greater than 0'
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = () => {
    if (!validate()) return
    const payload: DealCreatePayload = {
      ...form,
      // Strip empty optional strings so the backend doesn't receive ""
      close_date: form.close_date || undefined,
      property_city: form.property_city || undefined,
      property_state: form.property_state || undefined,
      property_zip: form.property_zip || undefined,
    }
    mutation.mutate(payload)
  }

  const handleClose = () => {
    if (mutation.isPending) return
    setForm(EMPTY_FORM)
    setFieldErrors({})
    mutation.reset()
    onClose()
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="sm"
      fullWidth
      aria-labelledby="create-deal-dialog-title"
    >
      <DialogTitle id="create-deal-dialog-title">Create New Deal</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {mutation.isError && (
            <Alert severity="error">
              {(mutation.error as Error)?.message ?? 'Failed to create deal'}
            </Alert>
          )}

          <TextField
            label="Property Address"
            value={form.property_address}
            onChange={(e) => setForm((f) => ({ ...f, property_address: e.target.value }))}
            error={!!fieldErrors.property_address}
            helperText={fieldErrors.property_address}
            required
            fullWidth
            inputProps={{ 'aria-label': 'Property address' }}
          />

          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="City"
              value={form.property_city ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, property_city: e.target.value }))}
              fullWidth
              inputProps={{ 'aria-label': 'City' }}
            />
            <TextField
              label="State"
              value={form.property_state ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, property_state: e.target.value }))}
              sx={{ width: 100 }}
              inputProps={{ 'aria-label': 'State', maxLength: 2 }}
            />
            <TextField
              label="ZIP"
              value={form.property_zip ?? ''}
              onChange={(e) => setForm((f) => ({ ...f, property_zip: e.target.value }))}
              sx={{ width: 120 }}
              inputProps={{ 'aria-label': 'ZIP code' }}
            />
          </Box>

          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Unit Count"
              type="number"
              value={form.unit_count}
              onChange={(e) =>
                setForm((f) => ({ ...f, unit_count: parseInt(e.target.value, 10) || 0 }))
              }
              error={!!fieldErrors.unit_count}
              helperText={fieldErrors.unit_count ?? 'Minimum 5'}
              required
              inputProps={{ min: 5, 'aria-label': 'Unit count' }}
              sx={{ flex: 1 }}
            />
            <TextField
              label="Purchase Price ($)"
              type="number"
              value={form.purchase_price}
              onChange={(e) =>
                setForm((f) => ({ ...f, purchase_price: parseFloat(e.target.value) || 0 }))
              }
              error={!!fieldErrors.purchase_price}
              helperText={fieldErrors.purchase_price}
              required
              inputProps={{ min: 1, step: 1000, 'aria-label': 'Purchase price' }}
              sx={{ flex: 2 }}
            />
          </Box>

          <TextField
            label="Close Date"
            type="date"
            value={form.close_date ?? ''}
            onChange={(e) => setForm((f) => ({ ...f, close_date: e.target.value }))}
            InputLabelProps={{ shrink: true }}
            fullWidth
            inputProps={{ 'aria-label': 'Close date' }}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={mutation.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={mutation.isPending}
          startIcon={mutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {mutation.isPending ? 'Creating…' : 'Create Deal'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Deal List Table
// ---------------------------------------------------------------------------

interface DealTableProps {
  deals: DealSummary[]
  onOpen: (dealId: number) => void
}

function DealTable({ deals, onOpen }: DealTableProps) {
  if (deals.length === 0) {
    return (
      <Box sx={{ py: 8, textAlign: 'center' }}>
        <Typography color="text.secondary">
          No deals yet. Create your first deal to get started.
        </Typography>
      </Box>
    )
  }

  return (
    <TableContainer component={Paper} variant="outlined">
      <Table aria-label="Multifamily deals table">
        <TableHead>
          <TableRow>
            <TableCell>Address</TableCell>
            <TableCell align="right">Units</TableCell>
            <TableCell align="right">Purchase Price</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Created</TableCell>
            <TableCell>Updated</TableCell>
            <TableCell align="center">Open</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {deals.map((deal) => (
            <TableRow
              key={deal.id}
              hover
              sx={{ cursor: 'pointer' }}
              onClick={() => onOpen(deal.id)}
            >
              <TableCell>
                <Typography variant="body2" fontWeight={500}>
                  {deal.property_address}
                </Typography>
              </TableCell>
              <TableCell align="right">{deal.unit_count}</TableCell>
              <TableCell align="right">{formatCurrency(deal.purchase_price)}</TableCell>
              <TableCell>
                <Chip
                  label={deal.status ?? 'draft'}
                  color={statusColor(deal.status)}
                  size="small"
                />
              </TableCell>
              <TableCell>{formatDate(deal.created_at)}</TableCell>
              <TableCell>{formatDate(deal.updated_at)}</TableCell>
              <TableCell align="center">
                <Tooltip title="Open deal">
                  <IconButton
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation()
                      onOpen(deal.id)
                    }}
                    aria-label={`Open deal ${deal.property_address}`}
                  >
                    <OpenInNewIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function DealListPage() {
  const navigate = useNavigate()
  const [createOpen, setCreateOpen] = useState(false)

  const {
    data: deals,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['multifamily', 'deals'],
    queryFn: () => multifamilyService.listDeals(),
  })

  const handleCreated = (dealId: number) => {
    setCreateOpen(false)
    navigate(`/multifamily/deals/${dealId}`)
  }

  return (
    <Box>
      {/* Header */}
      <Box
        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}
      >
        <Box>
          <Typography variant="h5" component="h1" fontWeight={600}>
            Multifamily Deals
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Underwrite apartment properties (5+ units)
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateOpen(true)}
          aria-label="Create new deal"
        >
          Create Deal
        </Button>
      </Box>

      {/* Content */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress aria-label="Loading deals" />
        </Box>
      )}

      {isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(error as Error)?.message ?? 'Failed to load deals'}
        </Alert>
      )}

      {!isLoading && !isError && (
        <DealTable deals={deals ?? []} onOpen={(id) => navigate(`/multifamily/deals/${id}`)} />
      )}

      {/* Create Deal Dialog */}
      <CreateDealDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleCreated}
      />
    </Box>
  )
}

export default DealListPage
