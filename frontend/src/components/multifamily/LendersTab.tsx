/**
 * LendersTab — select up to 3 Lender_Profiles per scenario (A, B) with one
 * marked Primary. Attach/detach. Surfaces LenderAttachmentLimitError.
 *
 * Requirements: 6.5–6.7
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import StarIcon from '@mui/icons-material/Star'
import { multifamilyService } from '@/services/api'
import { DealScenario, MFLenderType } from '@/types'
import type { LenderProfile, DealLenderSelection } from '@/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SCENARIO_LABELS: Record<DealScenario, string> = {
  [DealScenario.A]: 'Scenario A — Construction-to-Perm',
  [DealScenario.B]: 'Scenario B — Self-Funded Reno',
}

const SCENARIO_LENDER_TYPE: Record<DealScenario, MFLenderType> = {
  [DealScenario.A]: MFLenderType.CONSTRUCTION_TO_PERM,
  [DealScenario.B]: MFLenderType.SELF_FUNDED_RENO,
}

// ---------------------------------------------------------------------------
// Attach Lender Dialog
// ---------------------------------------------------------------------------

interface AttachLenderDialogProps {
  open: boolean
  dealId: number
  scenario: DealScenario
  profiles: LenderProfile[]
  onClose: () => void
}

function AttachLenderDialog({ open, dealId, scenario, profiles, onClose }: AttachLenderDialogProps) {
  const queryClient = useQueryClient()
  const [selectedProfileId, setSelectedProfileId] = useState<number | ''>('')
  const [isPrimary, setIsPrimary] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)

  const preferredType = SCENARIO_LENDER_TYPE[scenario]
  const filteredProfiles = profiles.filter((p) => p.lender_type === preferredType)

  const mutation = useMutation({
    mutationFn: () =>
      multifamilyService.attachLenderToDeal(dealId, scenario, {
        lender_profile_id: selectedProfileId as number,
        is_primary: isPrimary,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
      setSelectedProfileId('')
      setIsPrimary(false)
      setApiError(null)
      onClose()
    },
    onError: (err: Error) => {
      setApiError(err.message ?? 'Failed to attach lender')
    },
  })

  const handleClose = () => {
    if (mutation.isPending) return
    setSelectedProfileId('')
    setIsPrimary(false)
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
      aria-labelledby="attach-lender-dialog-title"
    >
      <DialogTitle id="attach-lender-dialog-title">
        Attach Lender — {SCENARIO_LABELS[scenario]}
      </DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {apiError && (
            <Alert severity="error">{apiError}</Alert>
          )}
          <FormControl fullWidth required>
            <InputLabel id="lender-profile-label">Lender Profile</InputLabel>
            <Select
              labelId="lender-profile-label"
              value={selectedProfileId}
              label="Lender Profile"
              onChange={(e) => setSelectedProfileId(e.target.value as number)}
              inputProps={{ 'aria-label': 'Select lender profile' }}
            >
              {filteredProfiles.length === 0 ? (
                <MenuItem disabled value="">
                  No {preferredType} profiles available
                </MenuItem>
              ) : (
                filteredProfiles.map((p) => (
                  <MenuItem key={p.id} value={p.id}>
                    {p.company}
                    <Chip label={p.lender_type} size="small" sx={{ ml: 1 }} />
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          <FormControlLabel
            control={
              <Checkbox
                checked={isPrimary}
                onChange={(e) => setIsPrimary(e.target.checked)}
                inputProps={{ 'aria-label': 'Mark as primary lender' }}
              />
            }
            label="Mark as Primary"
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={mutation.isPending}>Cancel</Button>
        <Button
          variant="contained"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || selectedProfileId === ''}
          startIcon={mutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {mutation.isPending ? 'Attaching…' : 'Attach'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Scenario Section
// ---------------------------------------------------------------------------

interface ScenarioSectionProps {
  dealId: number
  scenario: DealScenario
  selections: DealLenderSelection[]
  profiles: LenderProfile[]
}

function ScenarioSection({ dealId, scenario, selections, profiles }: ScenarioSectionProps) {
  const queryClient = useQueryClient()
  const [attachOpen, setAttachOpen] = useState(false)
  const [detachError, setDetachError] = useState<string | null>(null)

  const detachMutation = useMutation({
    mutationFn: (selectionId: number) =>
      multifamilyService.detachLenderFromDeal(dealId, scenario, selectionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deal', dealId] })
      setDetachError(null)
    },
    onError: (err: Error) => {
      setDetachError(err.message ?? 'Failed to detach lender')
    },
  })

  const profileMap: Record<number, LenderProfile> = {}
  for (const p of profiles) {
    profileMap[p.id] = p
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="subtitle1" fontWeight={600}>
          {SCENARIO_LABELS[scenario]}
        </Typography>
        <Button
          size="small"
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={() => setAttachOpen(true)}
          disabled={selections.length >= 3}
          aria-label={`Attach lender to ${SCENARIO_LABELS[scenario]}`}
        >
          Attach Lender
        </Button>
      </Box>

      {selections.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No lenders attached. Add up to 3.
        </Typography>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {selections.map((sel) => {
            const profile = sel.lender_profile ?? profileMap[sel.lender_profile_id]
            return (
              <Box
                key={sel.id}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  p: 1,
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                }}
              >
                {sel.is_primary && (
                  <Tooltip title="Primary lender">
                    <StarIcon fontSize="small" color="warning" aria-label="Primary lender" />
                  </Tooltip>
                )}
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="body2" fontWeight={500} noWrap>
                    {profile?.company ?? `Profile #${sel.lender_profile_id}`}
                  </Typography>
                  {profile && (
                    <Chip label={profile.lender_type} size="small" sx={{ mt: 0.25 }} />
                  )}
                </Box>
                {sel.is_primary && (
                  <Chip label="Primary" size="small" color="warning" />
                )}
                <Tooltip title="Detach lender">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={() => detachMutation.mutate(sel.id)}
                    disabled={detachMutation.isPending}
                    aria-label={`Detach ${profile?.company ?? 'lender'}`}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Box>
            )
          })}
        </Box>
      )}

      {detachError && (
        <Alert severity="error" sx={{ mt: 1 }}>
          {detachError}
        </Alert>
      )}

      <AttachLenderDialog
        open={attachOpen}
        dealId={dealId}
        scenario={scenario}
        profiles={profiles}
        onClose={() => setAttachOpen(false)}
      />
    </Paper>
  )
}

// ---------------------------------------------------------------------------
// Main Tab
// ---------------------------------------------------------------------------

interface LendersTabProps {
  dealId: number
}

export function LendersTab({ dealId }: LendersTabProps) {
  const { data: deal, isLoading: dealLoading } = useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => multifamilyService.getDeal(dealId),
  })

  const { data: profiles, isLoading: profilesLoading } = useQuery({
    queryKey: ['lender-profiles'],
    queryFn: () => multifamilyService.listLenderProfiles(),
  })

  if (dealLoading || profilesLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading lenders" />
      </Box>
    )
  }

  const allSelections: DealLenderSelection[] = deal?.lender_selections ?? []
  const selectionsA = allSelections.filter((s) => s.scenario === DealScenario.A)
  const selectionsB = allSelections.filter((s) => s.scenario === DealScenario.B)
  const allProfiles = profiles ?? []

  return (
    <Box>
      <Typography variant="h6" sx={{ mb: 3 }}>Lenders</Typography>
      <Divider sx={{ mb: 3 }} />
      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <ScenarioSection
            dealId={dealId}
            scenario={DealScenario.A}
            selections={selectionsA}
            profiles={allProfiles}
          />
        </Grid>
        <Grid item xs={12} md={6}>
          <ScenarioSection
            dealId={dealId}
            scenario={DealScenario.B}
            selections={selectionsB}
            profiles={allProfiles}
          />
        </Grid>
      </Grid>
    </Box>
  )
}

export default LendersTab
