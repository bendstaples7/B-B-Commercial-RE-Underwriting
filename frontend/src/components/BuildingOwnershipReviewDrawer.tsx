import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Drawer,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { buildingOwnershipService, leadTaskService } from '@/services/api'
import type {
  BuildingOwnershipDetail,
  BuildingSalePossible,
  CommandCenterPayload,
  CondoRiskStatus,
} from '@/types'

export interface BuildingOwnershipReviewDrawerProps {
  leadId: number
  commandCenterData: CommandCenterPayload
  open: boolean
  onClose: () => void
  onUpdated?: () => void
}

const RISK_STATUS_OPTIONS: { value: CondoRiskStatus; label: string }[] = [
  { value: 'likely_condo', label: 'Condo building' },
  { value: 'likely_not_condo', label: 'Single-owner building' },
  { value: 'needs_review', label: 'Needs more research' },
  { value: 'partial_condo_possible', label: 'Partial condo possible' },
  { value: 'unknown', label: 'Unknown' },
]

const BUILDING_SALE_OPTIONS: { value: BuildingSalePossible; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'unknown', label: 'Unknown' },
]

function formatAddress(data: CommandCenterPayload): string {
  const parts = [
    data.property_street,
    data.property_city,
    data.property_state,
    data.property_zip,
  ].filter(Boolean)
  return parts.join(', ') || '—'
}

export function BuildingOwnershipReviewDrawer({
  leadId,
  commandCenterData,
  open,
  onClose,
  onUpdated,
}: BuildingOwnershipReviewDrawerProps) {
  const queryClient = useQueryClient()
  const [overrideStatus, setOverrideStatus] = useState<CondoRiskStatus>('needs_review')
  const [overrideBuildingSale, setOverrideBuildingSale] = useState<BuildingSalePossible>('unknown')
  const [overrideReason, setOverrideReason] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const hasAnalysis = Boolean(commandCenterData.condo_analysis_id)

  const { data: detail, isLoading, error, refetch } = useQuery<BuildingOwnershipDetail>({
    queryKey: ['buildingOwnership', leadId],
    queryFn: () => buildingOwnershipService.get(leadId),
    enabled: open && hasAnalysis,
    retry: false,
  })

  const wasOpenRef = useRef(false)
  const lastLeadIdRef = useRef(leadId)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    queryClient.invalidateQueries({ queryKey: ['buildingOwnership', leadId] })
    onUpdated?.()
  }

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      const requestedLeadId = leadId
      const result = await buildingOwnershipService.analyze(requestedLeadId)
      return { requestedLeadId, result }
    },
    onSuccess: ({ requestedLeadId, result }) => {
      // Ignore stale responses if the drawer switched leads mid-flight.
      if (requestedLeadId !== leadId) return
      setOverrideStatus(
        (result?.condo_risk_status as CondoRiskStatus) ?? 'needs_review',
      )
      setOverrideBuildingSale(
        (result?.building_sale_possible as BuildingSalePossible) ?? 'unknown',
      )
      setOverrideReason('')
      setFormError(null)
      invalidate()
      refetch()
    },
  })

  const overrideMutation = useMutation({
    mutationFn: () =>
      buildingOwnershipService.override(leadId, {
        condo_risk_status: overrideStatus,
        building_sale_possible: overrideBuildingSale,
        reason: overrideReason.trim(),
      }),
    onSuccess: () => {
      setFormError(null)
      setOverrideReason('')
      invalidate()
      refetch()
    },
    onError: (err: Error) => setFormError(err.message || 'Override failed'),
  })

  const createTaskMutation = useMutation({
    mutationFn: () =>
      leadTaskService.createTask(leadId, {
        title: 'Confirm building ownership',
        task_type: 'confirm_building_ownership',
      }),
    onSuccess: invalidate,
    onError: (err: Error) => setFormError(err.message || 'Failed to create task'),
  })

  useEffect(() => {
    const leadChanged = lastLeadIdRef.current !== leadId
    lastLeadIdRef.current = leadId
    if ((open && !wasOpenRef.current) || (open && leadChanged)) {
      setOverrideStatus(commandCenterData.condo_risk_status ?? 'needs_review')
      setOverrideBuildingSale(commandCenterData.building_sale_possible ?? 'unknown')
      setOverrideReason('')
      setFormError(null)
    }
    if (leadChanged) {
      analyzeMutation.reset()
      overrideMutation.reset()
      createTaskMutation.reset()
    }
    wasOpenRef.current = open
    // Intentionally omit mutation objects from deps — reset only on lead/open changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, leadId, commandCenterData.condo_risk_status, commandCenterData.building_sale_possible])

  const assessorPins = (detail?.analysis_details?.assessor_pins ?? []) as Array<{
    pin?: string
    property_class?: string
    is_condo_class?: boolean
  }>

  const classification = detail?.analysis_details as Record<string, unknown> | undefined

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100%', sm: 480 } } }}
      data-testid="building-ownership-drawer"
    >
      <Box sx={{ p: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="h6">Building Ownership Review</Typography>
        <IconButton onClick={onClose} aria-label="Close">
          <CloseIcon />
        </IconButton>
      </Box>
      <Divider />

      <Box sx={{ p: 2 }}>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          {formatAddress(commandCenterData)}
        </Typography>
        {commandCenterData.county_assessor_pin && (
          <Typography variant="body2" color="text.secondary">
            Lead PIN: {commandCenterData.county_assessor_pin}
            {commandCenterData.assessor_class ? ` · Class ${commandCenterData.assessor_class}` : ''}
          </Typography>
        )}

        <Stack direction="row" spacing={1} sx={{ mt: 1, mb: 2, flexWrap: 'wrap' }}>
          {commandCenterData.condo_risk_status && (
            <Chip
              size="small"
              label={`Condo risk: ${commandCenterData.condo_risk_status.replace(/_/g, ' ')}`}
              data-testid="condo-risk-chip"
            />
          )}
          {commandCenterData.building_sale_possible && (
            <Chip
              size="small"
              variant="outlined"
              label={`Building sale: ${commandCenterData.building_sale_possible}`}
            />
          )}
        </Stack>

        {!hasAnalysis && !analyzeMutation.isPending && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Building ownership has not been verified yet. Run an automated check using Cook County assessor data.
          </Alert>
        )}

        <Button
          variant="contained"
          fullWidth
          disabled={analyzeMutation.isPending}
          onClick={() => analyzeMutation.mutate()}
          data-testid="run-building-ownership-check"
          sx={{ mb: 2 }}
        >
          {analyzeMutation.isPending ? <CircularProgress size={22} color="inherit" /> : 'Run automated check'}
        </Button>

        {analyzeMutation.isError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {analyzeMutation.error instanceof Error
              ? analyzeMutation.error.message
              : 'Analysis failed'}
          </Alert>
        )}

        {isLoading && hasAnalysis && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress size={28} />
          </Box>
        )}

        {error && hasAnalysis && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Could not load analysis details. Try running the check again.
          </Alert>
        )}

        {detail && (
          <>
            <Typography variant="subtitle2" gutterBottom>
              Classification
            </Typography>
            <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
              <Typography variant="body2">
                {(classification?.reason as string) ?? 'No reason recorded'}
              </Typography>
              {classification?.confidence != null && (
                <Typography variant="caption" color="text.secondary">
                  Confidence: {String(classification.confidence)}
                </Typography>
              )}
            </Paper>

            {assessorPins.length > 0 && (
              <>
                <Typography variant="subtitle2" gutterBottom>
                  PINs at address ({assessorPins.length})
                </Typography>
                <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>PIN</TableCell>
                        <TableCell>Class</TableCell>
                        <TableCell>Condo signal</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {assessorPins.map((row) => (
                        <TableRow key={row.pin}>
                          <TableCell>{row.pin ?? '—'}</TableCell>
                          <TableCell>{row.property_class ?? '—'}</TableCell>
                          <TableCell>{row.is_condo_class ? 'Yes' : 'No'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </>
            )}

            <Divider sx={{ my: 2 }} />
            <Typography variant="subtitle2" gutterBottom>
              Manual confirmation
            </Typography>
            <Stack spacing={2} component="form" onSubmit={(e) => {
              e.preventDefault()
              if (!overrideReason.trim()) {
                setFormError('Reason is required.')
                return
              }
              overrideMutation.mutate()
            }}>
              <FormControl fullWidth size="small">
                <InputLabel>Building type</InputLabel>
                <Select
                  value={overrideStatus}
                  label="Building type"
                  onChange={(e) => setOverrideStatus(e.target.value as CondoRiskStatus)}
                >
                  {RISK_STATUS_OPTIONS.map((opt) => (
                    <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth size="small">
                <InputLabel>Whole-building sale possible?</InputLabel>
                <Select
                  value={overrideBuildingSale}
                  label="Whole-building sale possible?"
                  onChange={(e) => setOverrideBuildingSale(e.target.value as BuildingSalePossible)}
                >
                  {BUILDING_SALE_OPTIONS.map((opt) => (
                    <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                label="Reason"
                value={overrideReason}
                onChange={(e) => setOverrideReason(e.target.value)}
                multiline
                minRows={2}
                required
                size="small"
              />
              {formError && <Alert severity="error">{formError}</Alert>}
              <Button
                type="submit"
                variant="outlined"
                disabled={overrideMutation.isPending}
                data-testid="confirm-building-ownership"
              >
                {overrideMutation.isPending ? 'Saving…' : 'Confirm override'}
              </Button>
            </Stack>
          </>
        )}

        <Divider sx={{ my: 2 }} />
        <Button
          variant="text"
          onClick={() => createTaskMutation.mutate()}
          disabled={createTaskMutation.isPending}
        >
          Create confirm ownership task
        </Button>
        {createTaskMutation.isError && (
          <Alert severity="error" sx={{ mt: 1 }}>
            {createTaskMutation.error instanceof Error
              ? createTaskMutation.error.message
              : 'Failed to create task'}
          </Alert>
        )}
      </Box>
    </Drawer>
  )
}

export default BuildingOwnershipReviewDrawer
