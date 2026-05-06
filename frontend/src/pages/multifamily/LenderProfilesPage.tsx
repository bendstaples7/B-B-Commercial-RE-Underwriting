/**
 * LenderProfilesPage — CRUD UI for reusable Lender Profiles.
 * Supports both Construction_To_Perm and Self_Funded_Reno lender types
 * with per-type form fields.
 *
 * Requirements: 6.1–6.4, 14.1
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
  Divider,
  FormControl,
  FormHelperText,
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
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { multifamilyService } from '@/services/api'
import { MFLenderType } from '@/types'
import type { LenderProfile } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtRate(value: string | null): string {
  if (!value) return '—'
  const pct = (parseFloat(value) * 100).toFixed(3)
  return `${pct}%`
}

// ---------------------------------------------------------------------------
// Form state types
// ---------------------------------------------------------------------------

interface CtpFields {
  ltv_total_cost: string
  construction_rate: string
  construction_io_months: string
  construction_term_months: string
  perm_rate: string
  perm_amort_years: string
  min_interest_or_yield: string
}

interface SfrFields {
  max_purchase_ltv: string
  treasury_5y_rate: string
  spread_bps: string
  term_years: string
  amort_years: string
}

interface ProfileFormState {
  company: string
  lender_type: MFLenderType
  origination_fee_rate: string
  prepay_penalty_description: string
  ctp: CtpFields
  sfr: SfrFields
}

const EMPTY_CTP: CtpFields = {
  ltv_total_cost: '',
  construction_rate: '',
  construction_io_months: '',
  construction_term_months: '',
  perm_rate: '',
  perm_amort_years: '',
  min_interest_or_yield: '',
}

const EMPTY_SFR: SfrFields = {
  max_purchase_ltv: '',
  treasury_5y_rate: '',
  spread_bps: '',
  term_years: '',
  amort_years: '',
}

const EMPTY_FORM: ProfileFormState = {
  company: '',
  lender_type: MFLenderType.CONSTRUCTION_TO_PERM,
  origination_fee_rate: '',
  prepay_penalty_description: '',
  ctp: EMPTY_CTP,
  sfr: EMPTY_SFR,
}

function profileToForm(p: LenderProfile): ProfileFormState {
  return {
    company: p.company,
    lender_type: p.lender_type,
    origination_fee_rate: p.origination_fee_rate,
    prepay_penalty_description: p.prepay_penalty_description ?? '',
    ctp: {
      ltv_total_cost: p.ltv_total_cost ?? '',
      construction_rate: p.construction_rate ?? '',
      construction_io_months: p.construction_io_months?.toString() ?? '',
      construction_term_months: p.construction_term_months?.toString() ?? '',
      perm_rate: p.perm_rate ?? '',
      perm_amort_years: p.perm_amort_years?.toString() ?? '',
      min_interest_or_yield: p.min_interest_or_yield ?? '',
    },
    sfr: {
      max_purchase_ltv: p.max_purchase_ltv ?? '',
      treasury_5y_rate: p.treasury_5y_rate ?? '',
      spread_bps: p.spread_bps?.toString() ?? '',
      term_years: p.term_years?.toString() ?? '',
      amort_years: p.amort_years?.toString() ?? '',
    },
  }
}

function formToPayload(
  form: ProfileFormState
): Omit<LenderProfile, 'id' | 'created_by_user_id' | 'all_in_rate' | 'created_at' | 'updated_at'> {
  const isCtp = form.lender_type === MFLenderType.CONSTRUCTION_TO_PERM
  return {
    company: form.company,
    lender_type: form.lender_type,
    origination_fee_rate: form.origination_fee_rate,
    prepay_penalty_description: form.prepay_penalty_description || null,
    ltv_total_cost: isCtp ? form.ctp.ltv_total_cost || null : null,
    construction_rate: isCtp ? form.ctp.construction_rate || null : null,
    construction_io_months: isCtp ? parseInt(form.ctp.construction_io_months, 10) || null : null,
    construction_term_months: isCtp
      ? parseInt(form.ctp.construction_term_months, 10) || null
      : null,
    perm_rate: isCtp ? form.ctp.perm_rate || null : null,
    perm_amort_years: isCtp ? parseInt(form.ctp.perm_amort_years, 10) || null : null,
    min_interest_or_yield: isCtp ? form.ctp.min_interest_or_yield || null : null,
    max_purchase_ltv: !isCtp ? form.sfr.max_purchase_ltv || null : null,
    treasury_5y_rate: !isCtp ? form.sfr.treasury_5y_rate || null : null,
    spread_bps: !isCtp ? parseInt(form.sfr.spread_bps, 10) || null : null,
    term_years: !isCtp ? parseInt(form.sfr.term_years, 10) || null : null,
    amort_years: !isCtp ? parseInt(form.sfr.amort_years, 10) || null : null,
  }
}

// ---------------------------------------------------------------------------
// Profile Form Dialog
// ---------------------------------------------------------------------------

interface ProfileDialogProps {
  open: boolean
  editing: LenderProfile | null
  onClose: () => void
}

function ProfileDialog({ open, editing, onClose }: ProfileDialogProps) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<ProfileFormState>(
    editing ? profileToForm(editing) : EMPTY_FORM
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const handleOpen = () => {
    setForm(editing ? profileToForm(editing) : EMPTY_FORM)
    setErrors({})
  }

  const validate = (): boolean => {
    const e: Record<string, string> = {}
    if (!form.company.trim()) e.company = 'Company name is required'
    if (!form.origination_fee_rate) e.origination_fee_rate = 'Required'
    const origFee = parseFloat(form.origination_fee_rate)
    if (isNaN(origFee) || origFee < 0 || origFee > 0.3)
      e.origination_fee_rate = 'Must be between 0 and 0.30'

    if (form.lender_type === MFLenderType.CONSTRUCTION_TO_PERM) {
      const ltv = parseFloat(form.ctp.ltv_total_cost)
      if (!form.ctp.ltv_total_cost || isNaN(ltv) || ltv < 0 || ltv > 1)
        e.ltv_total_cost = 'Must be between 0 and 1'
      const cr = parseFloat(form.ctp.construction_rate)
      if (!form.ctp.construction_rate || isNaN(cr) || cr < 0 || cr > 0.3)
        e.construction_rate = 'Must be between 0 and 0.30'
      if (!form.ctp.construction_io_months) e.construction_io_months = 'Required'
      if (!form.ctp.perm_rate) e.perm_rate = 'Required'
      const pr = parseFloat(form.ctp.perm_rate)
      if (isNaN(pr) || pr < 0 || pr > 0.3) e.perm_rate = 'Must be between 0 and 0.30'
      if (!form.ctp.perm_amort_years) e.perm_amort_years = 'Required'
    } else {
      const ltv = parseFloat(form.sfr.max_purchase_ltv)
      if (!form.sfr.max_purchase_ltv || isNaN(ltv) || ltv < 0 || ltv > 1)
        e.max_purchase_ltv = 'Must be between 0 and 1'
      const tr = parseFloat(form.sfr.treasury_5y_rate)
      if (!form.sfr.treasury_5y_rate || isNaN(tr) || tr < 0 || tr > 0.3)
        e.treasury_5y_rate = 'Must be between 0 and 0.30'
      if (!form.sfr.spread_bps) e.spread_bps = 'Required'
      if (!form.sfr.amort_years) e.amort_years = 'Required'
    }

    setErrors(e)
    return Object.keys(e).length === 0
  }

  const createMutation = useMutation({
    mutationFn: (
      payload: Omit<
        LenderProfile,
        'id' | 'created_by_user_id' | 'all_in_rate' | 'created_at' | 'updated_at'
      >
    ) => multifamilyService.createLenderProfile(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['multifamily', 'lender-profiles'] })
      onClose()
    },
  })

  const updateMutation = useMutation({
    mutationFn: (
      payload: Omit<
        LenderProfile,
        'id' | 'created_by_user_id' | 'all_in_rate' | 'created_at' | 'updated_at'
      >
    ) => multifamilyService.updateLenderProfile(editing!.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['multifamily', 'lender-profiles'] })
      onClose()
    },
  })

  const isPending = createMutation.isPending || updateMutation.isPending
  const mutationError = createMutation.error ?? updateMutation.error

  const handleSubmit = () => {
    if (!validate()) return
    const payload = formToPayload(form)
    if (editing) {
      updateMutation.mutate(payload)
    } else {
      createMutation.mutate(payload)
    }
  }

  const setCtp = (field: keyof CtpFields, value: string) =>
    setForm((f) => ({ ...f, ctp: { ...f.ctp, [field]: value } }))

  const setSfr = (field: keyof SfrFields, value: string) =>
    setForm((f) => ({ ...f, sfr: { ...f.sfr, [field]: value } }))

  return (
    <Dialog
      open={open}
      onClose={isPending ? undefined : onClose}
      maxWidth="sm"
      fullWidth
      TransitionProps={{ onEnter: handleOpen }}
      aria-labelledby="lender-profile-dialog-title"
    >
      <DialogTitle id="lender-profile-dialog-title">
        {editing ? 'Edit Lender Profile' : 'New Lender Profile'}
      </DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {mutationError && (
            <Alert severity="error">
              {(mutationError as Error)?.message ?? 'Failed to save profile'}
            </Alert>
          )}

          {/* Lender type toggle */}
          <Box>
            <Typography variant="caption" color="text.secondary" gutterBottom display="block">
              Lender Type
            </Typography>
            <ToggleButtonGroup
              value={form.lender_type}
              exclusive
              onChange={(_, v) => v && setForm((f) => ({ ...f, lender_type: v }))}
              size="small"
              aria-label="Lender type"
              sx={{ display: 'flex' }}
            >
              <ToggleButton
                value={MFLenderType.CONSTRUCTION_TO_PERM}
                sx={{ flex: 1 }}
                aria-label="Construction to Perm"
              >
                Construction-to-Perm
              </ToggleButton>
              <ToggleButton
                value={MFLenderType.SELF_FUNDED_RENO}
                sx={{ flex: 1 }}
                aria-label="Self-Funded Reno"
              >
                Self-Funded Reno
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>

          {/* Common fields */}
          <TextField
            label="Company"
            value={form.company}
            onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
            error={!!errors.company}
            helperText={errors.company}
            required
            fullWidth
          />

          <TextField
            label="Origination Fee Rate (e.g. 0.01 = 1%)"
            type="number"
            value={form.origination_fee_rate}
            onChange={(e) => setForm((f) => ({ ...f, origination_fee_rate: e.target.value }))}
            error={!!errors.origination_fee_rate}
            helperText={errors.origination_fee_rate ?? 'Range: 0–0.30'}
            inputProps={{ step: 0.001, min: 0, max: 0.3 }}
            fullWidth
          />

          <TextField
            label="Prepay Penalty Description"
            value={form.prepay_penalty_description}
            onChange={(e) =>
              setForm((f) => ({ ...f, prepay_penalty_description: e.target.value }))
            }
            multiline
            rows={2}
            fullWidth
          />

          <Divider />

          {/* Construction-to-Perm fields */}
          {form.lender_type === MFLenderType.CONSTRUCTION_TO_PERM && (
            <>
              <Typography variant="subtitle2" color="text.secondary">
                Construction-to-Perm Terms
              </Typography>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField
                  label="LTV (Total Cost)"
                  type="number"
                  value={form.ctp.ltv_total_cost}
                  onChange={(e) => setCtp('ltv_total_cost', e.target.value)}
                  error={!!errors.ltv_total_cost}
                  helperText={errors.ltv_total_cost ?? '0–1'}
                  inputProps={{ step: 0.01, min: 0, max: 1 }}
                  sx={{ flex: 1 }}
                />
                <TextField
                  label="Construction Rate"
                  type="number"
                  value={form.ctp.construction_rate}
                  onChange={(e) => setCtp('construction_rate', e.target.value)}
                  error={!!errors.construction_rate}
                  helperText={errors.construction_rate ?? '0–0.30'}
                  inputProps={{ step: 0.001, min: 0, max: 0.3 }}
                  sx={{ flex: 1 }}
                />
              </Box>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField
                  label="IO Months"
                  type="number"
                  value={form.ctp.construction_io_months}
                  onChange={(e) => setCtp('construction_io_months', e.target.value)}
                  error={!!errors.construction_io_months}
                  helperText={errors.construction_io_months}
                  inputProps={{ min: 1 }}
                  sx={{ flex: 1 }}
                />
                <TextField
                  label="Construction Term (months)"
                  type="number"
                  value={form.ctp.construction_term_months}
                  onChange={(e) => setCtp('construction_term_months', e.target.value)}
                  inputProps={{ min: 1 }}
                  sx={{ flex: 1 }}
                />
              </Box>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField
                  label="Perm Rate"
                  type="number"
                  value={form.ctp.perm_rate}
                  onChange={(e) => setCtp('perm_rate', e.target.value)}
                  error={!!errors.perm_rate}
                  helperText={errors.perm_rate ?? '0–0.30'}
                  inputProps={{ step: 0.001, min: 0, max: 0.3 }}
                  sx={{ flex: 1 }}
                />
                <TextField
                  label="Perm Amort (years)"
                  type="number"
                  value={form.ctp.perm_amort_years}
                  onChange={(e) => setCtp('perm_amort_years', e.target.value)}
                  error={!!errors.perm_amort_years}
                  helperText={errors.perm_amort_years}
                  inputProps={{ min: 1 }}
                  sx={{ flex: 1 }}
                />
              </Box>
              <TextField
                label="Min Interest / Yield ($)"
                type="number"
                value={form.ctp.min_interest_or_yield}
                onChange={(e) => setCtp('min_interest_or_yield', e.target.value)}
                inputProps={{ min: 0 }}
                fullWidth
              />
            </>
          )}

          {/* Self-Funded Reno fields */}
          {form.lender_type === MFLenderType.SELF_FUNDED_RENO && (
            <>
              <Typography variant="subtitle2" color="text.secondary">
                Self-Funded Reno Terms
              </Typography>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField
                  label="Max Purchase LTV"
                  type="number"
                  value={form.sfr.max_purchase_ltv}
                  onChange={(e) => setSfr('max_purchase_ltv', e.target.value)}
                  error={!!errors.max_purchase_ltv}
                  helperText={errors.max_purchase_ltv ?? '0–1'}
                  inputProps={{ step: 0.01, min: 0, max: 1 }}
                  sx={{ flex: 1 }}
                />
                <TextField
                  label="Treasury 5Y Rate"
                  type="number"
                  value={form.sfr.treasury_5y_rate}
                  onChange={(e) => setSfr('treasury_5y_rate', e.target.value)}
                  error={!!errors.treasury_5y_rate}
                  helperText={errors.treasury_5y_rate ?? '0–0.30'}
                  inputProps={{ step: 0.001, min: 0, max: 0.3 }}
                  sx={{ flex: 1 }}
                />
              </Box>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField
                  label="Spread (bps)"
                  type="number"
                  value={form.sfr.spread_bps}
                  onChange={(e) => setSfr('spread_bps', e.target.value)}
                  error={!!errors.spread_bps}
                  helperText={errors.spread_bps ?? 'e.g. 200 = 2%'}
                  inputProps={{ min: 0 }}
                  sx={{ flex: 1 }}
                />
                <TextField
                  label="Term (years)"
                  type="number"
                  value={form.sfr.term_years}
                  onChange={(e) => setSfr('term_years', e.target.value)}
                  inputProps={{ min: 1 }}
                  sx={{ flex: 1 }}
                />
                <TextField
                  label="Amort (years)"
                  type="number"
                  value={form.sfr.amort_years}
                  onChange={(e) => setSfr('amort_years', e.target.value)}
                  error={!!errors.amort_years}
                  helperText={errors.amort_years}
                  inputProps={{ min: 1 }}
                  sx={{ flex: 1 }}
                />
              </Box>
            </>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={isPending}
          startIcon={isPending ? <CircularProgress size={16} /> : undefined}
        >
          {isPending ? 'Saving…' : editing ? 'Save Changes' : 'Create Profile'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Delete Confirm Dialog
// ---------------------------------------------------------------------------

interface DeleteDialogProps {
  profile: LenderProfile | null
  onClose: () => void
}

function DeleteDialog({ profile, onClose }: DeleteDialogProps) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (id: number) => multifamilyService.deleteLenderProfile(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['multifamily', 'lender-profiles'] })
      onClose()
    },
  })

  return (
    <Dialog
      open={!!profile}
      onClose={mutation.isPending ? undefined : onClose}
      maxWidth="xs"
      fullWidth
      aria-labelledby="delete-profile-dialog-title"
    >
      <DialogTitle id="delete-profile-dialog-title">Delete Lender Profile</DialogTitle>
      <DialogContent>
        {mutation.isError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {(mutation.error as Error)?.message ?? 'Failed to delete profile'}
          </Alert>
        )}
        <Typography>
          Are you sure you want to delete <strong>{profile?.company}</strong>? This cannot be
          undone.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={mutation.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          color="error"
          onClick={() => profile && mutation.mutate(profile.id)}
          disabled={mutation.isPending}
          startIcon={mutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {mutation.isPending ? 'Deleting…' : 'Delete'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Profiles Table
// ---------------------------------------------------------------------------

interface ProfilesTableProps {
  profiles: LenderProfile[]
  onEdit: (p: LenderProfile) => void
  onDelete: (p: LenderProfile) => void
}

function ProfilesTable({ profiles, onEdit, onDelete }: ProfilesTableProps) {
  if (profiles.length === 0) {
    return (
      <Box sx={{ py: 8, textAlign: 'center' }}>
        <Typography color="text.secondary">
          No lender profiles yet. Create one to attach to deals.
        </Typography>
      </Box>
    )
  }

  return (
    <TableContainer component={Paper} variant="outlined">
      <Table aria-label="Lender profiles table">
        <TableHead>
          <TableRow>
            <TableCell>Company</TableCell>
            <TableCell>Type</TableCell>
            <TableCell>Key Rate</TableCell>
            <TableCell>LTV</TableCell>
            <TableCell>Orig. Fee</TableCell>
            <TableCell align="center">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {profiles.map((p) => {
            const isCtp = p.lender_type === MFLenderType.CONSTRUCTION_TO_PERM
            return (
              <TableRow key={p.id} hover>
                <TableCell>
                  <Typography variant="body2" fontWeight={500}>
                    {p.company}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={isCtp ? 'Const-to-Perm' : 'Self-Funded'}
                    color={isCtp ? 'primary' : 'secondary'}
                    size="small"
                    variant="outlined"
                  />
                </TableCell>
                <TableCell>
                  {isCtp
                    ? `${fmtRate(p.construction_rate)} IO / ${fmtRate(p.perm_rate)} perm`
                    : fmtRate(p.all_in_rate)}
                </TableCell>
                <TableCell>
                  {isCtp ? fmtRate(p.ltv_total_cost) : fmtRate(p.max_purchase_ltv)}
                </TableCell>
                <TableCell>{fmtRate(p.origination_fee_rate)}</TableCell>
                <TableCell align="center">
                  <Tooltip title="Edit">
                    <IconButton
                      size="small"
                      onClick={() => onEdit(p)}
                      aria-label={`Edit ${p.company}`}
                    >
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Delete">
                    <IconButton
                      size="small"
                      onClick={() => onDelete(p)}
                      aria-label={`Delete ${p.company}`}
                      color="error"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function LenderProfilesPage() {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<LenderProfile | null>(null)
  const [deleting, setDeleting] = useState<LenderProfile | null>(null)
  const [typeFilter, setTypeFilter] = useState<MFLenderType | ''>('')

  const { data: profiles, isLoading, isError, error } = useQuery({
    queryKey: ['multifamily', 'lender-profiles', typeFilter],
    queryFn: () => multifamilyService.listLenderProfiles(typeFilter ? typeFilter : undefined),
  })

  const handleEdit = (p: LenderProfile) => {
    setEditing(p)
    setDialogOpen(true)
  }

  const handleCloseDialog = () => {
    setDialogOpen(false)
    setEditing(null)
  }

  return (
    <Box>
      {/* Header */}
      <Box
        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}
      >
        <Box>
          <Typography variant="h5" component="h1" fontWeight={600}>
            Lender Profiles
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Reusable lender terms for Construction-to-Perm and Self-Funded Reno scenarios
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => {
            setEditing(null)
            setDialogOpen(true)
          }}
          aria-label="Create new lender profile"
        >
          New Profile
        </Button>
      </Box>

      {/* Type filter */}
      <Box sx={{ mb: 2 }}>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel id="lender-type-filter-label">Filter by type</InputLabel>
          <Select
            labelId="lender-type-filter-label"
            value={typeFilter}
            label="Filter by type"
            onChange={(e) => setTypeFilter(e.target.value as MFLenderType | '')}
          >
            <MenuItem value="">All types</MenuItem>
            <MenuItem value={MFLenderType.CONSTRUCTION_TO_PERM}>Construction-to-Perm</MenuItem>
            <MenuItem value={MFLenderType.SELF_FUNDED_RENO}>Self-Funded Reno</MenuItem>
          </Select>
          <FormHelperText>Showing {profiles?.length ?? 0} profiles</FormHelperText>
        </FormControl>
      </Box>

      {/* Content */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress aria-label="Loading lender profiles" />
        </Box>
      )}

      {isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(error as Error)?.message ?? 'Failed to load lender profiles'}
        </Alert>
      )}

      {!isLoading && !isError && (
        <ProfilesTable profiles={profiles ?? []} onEdit={handleEdit} onDelete={setDeleting} />
      )}

      {/* Create / Edit Dialog */}
      <ProfileDialog open={dialogOpen} editing={editing} onClose={handleCloseDialog} />

      {/* Delete Confirm Dialog */}
      <DeleteDialog profile={deleting} onClose={() => setDeleting(null)} />
    </Box>
  )
}

export default LenderProfilesPage
