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
import openLetterService from '@/services/openLetterApi'
import type {
  BuildingOwnershipAnalyzeResult,
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
  onAddToMailQueue?: () => Promise<void>
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

const RISK_LABELS: Record<CondoRiskStatus, string> = {
  likely_condo: 'Condo building',
  likely_not_condo: 'Single-owner building',
  needs_review: 'Needs more research',
  partial_condo_possible: 'Partial condo possible',
  unknown: 'Unknown',
}

type AssessorPinRow = {
  pin?: string
  property_class?: string
  is_condo_class?: boolean
}

function formatAddress(data: CommandCenterPayload): string {
  const parts = [
    data.property_street,
    data.property_city,
    data.property_state,
    data.property_zip,
  ].filter(Boolean)
  return parts.join(', ') || '—'
}

function pinExplanation(
  pinCount: number,
  units: number | null | undefined,
  pins: AssessorPinRow[],
): string {
  const anyCondoClass = pins.some((p) => p.is_condo_class)
  const unitPart =
    units != null
      ? ` Imported unit count is ${units}.`
      : ''

  if (pinCount <= 1) {
    return (
      `One PIN at this address is common for a single parcel.${unitPart}` +
      (anyCondoClass
        ? ' Assessor class signals condo coding — confirm carefully.'
        : ' No assessor condo class on the PIN.')
    )
  }

  return (
    `Multiple PINs at an address do not automatically mean a condo association. ` +
    `Cook County often assigns one PIN per unit in a 2-flat or small multi-unit building.` +
    unitPart +
    (anyCondoClass
      ? ' At least one PIN has an assessor condo class.'
      : ' Condo signal “No” means the assessor class is not condo-coded.') +
    (units != null && pinCount === units && !anyCondoClass
      ? ` ${pinCount} PINs + ${units} imported units + no condo class → often a ${units}-unit building, not a condo association.`
      : '')
  )
}

export function BuildingOwnershipReviewDrawer({
  leadId,
  commandCenterData,
  open,
  onClose,
  onUpdated,
  onAddToMailQueue,
}: BuildingOwnershipReviewDrawerProps) {
  const queryClient = useQueryClient()
  const [overrideStatus, setOverrideStatus] = useState<CondoRiskStatus>('needs_review')
  const [overrideBuildingSale, setOverrideBuildingSale] = useState<BuildingSalePossible>('unknown')
  const [overrideReason, setOverrideReason] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [analyzeFeedback, setAnalyzeFeedback] = useState<string | null>(null)
  const [analyzeSnapshot, setAnalyzeSnapshot] = useState<BuildingOwnershipAnalyzeResult | null>(null)
  const [mailMessage, setMailMessage] = useState<string | null>(null)
  const [mailPending, setMailPending] = useState(false)

  const hasAnalysis = Boolean(
    commandCenterData.condo_analysis_id || analyzeSnapshot?.condo_analysis_id,
  )

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
      const result = (await buildingOwnershipService.analyze(
        requestedLeadId,
      )) as BuildingOwnershipAnalyzeResult
      return { requestedLeadId, result }
    },
    onSuccess: ({ requestedLeadId, result }) => {
      if (requestedLeadId !== leadId) return
      setAnalyzeSnapshot(result)
      setOverrideStatus(
        (result?.condo_risk_status as CondoRiskStatus) ?? 'needs_review',
      )
      setOverrideBuildingSale(
        (result?.building_sale_possible as BuildingSalePossible) ?? 'unknown',
      )
      setOverrideReason('')
      setFormError(null)
      if (result?.skipped) {
        setAnalyzeFeedback(
          'Already analyzed (current) — review the results below, then save your decision if needed.',
        )
      } else {
        setAnalyzeFeedback('Analysis updated. Review the findings and save your decision.')
      }
      invalidate()
      void refetch()
    },
  })

  const overrideMutation = useMutation({
    mutationFn: () =>
      buildingOwnershipService.override(leadId, {
        condo_risk_status: overrideStatus,
        building_sale_possible: overrideBuildingSale,
        reason: overrideReason.trim(),
      }),
    onSuccess: (result) => {
      setFormError(null)
      setOverrideReason('')
      setAnalyzeFeedback('Ownership decision saved. Recommended action has been rescored.')
      if (result?.condo_risk_status) {
        setOverrideStatus(result.condo_risk_status as CondoRiskStatus)
      }
      if (result?.building_sale_possible) {
        setOverrideBuildingSale(result.building_sale_possible as BuildingSalePossible)
      }
      invalidate()
      void refetch()
    },
    onError: (err: Error) => setFormError(err.message || 'Save failed'),
  })

  const createTaskMutation = useMutation({
    mutationFn: () =>
      leadTaskService.createTask(leadId, {
        title: 'Confirm building ownership',
        task_type: 'confirm_building_ownership',
      }),
    onSuccess: () => {
      setAnalyzeFeedback('Follow-up task created. This does not change ownership status.')
      invalidate()
    },
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
      setAnalyzeFeedback(null)
      setAnalyzeSnapshot(null)
      setMailMessage(null)
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

  const snapshotPins = (analyzeSnapshot?.analysis_details?.assessor_pins ?? []) as AssessorPinRow[]
  const detailPins = (detail?.analysis_details?.assessor_pins ?? []) as AssessorPinRow[]
  const assessorPins = detailPins.length > 0 ? detailPins : snapshotPins

  const classification =
    (detail?.analysis_details as Record<string, unknown> | undefined) ??
    (analyzeSnapshot?.analysis_details as Record<string, unknown> | undefined) ??
    (analyzeSnapshot?.classification as Record<string, unknown> | undefined)

  const displayRisk =
    (detail?.condo_risk_status as CondoRiskStatus | undefined) ??
    analyzeSnapshot?.condo_risk_status ??
    commandCenterData.condo_risk_status ??
    null
  const displaySale =
    (detail?.building_sale_possible as BuildingSalePossible | undefined) ??
    analyzeSnapshot?.building_sale_possible ??
    commandCenterData.building_sale_possible ??
    null

  const units = commandCenterData.units ?? null
  const unitsAllowed = commandCenterData.units_allowed ?? null
  const pinCount = detail?.pin_count ?? assessorPins.length
  const showDecisionForm = Boolean(detail || analyzeSnapshot)
  const hasMailingAddress = Boolean(
    (commandCenterData.mailing_address || '').trim() ||
      (commandCenterData.mailing_city || '').trim(),
  )
  const effectiveRisk = overrideMutation.isSuccess ? overrideStatus : displayRisk
  const effectiveSale = overrideMutation.isSuccess ? overrideBuildingSale : displaySale
  const showMailCta =
    hasMailingAddress &&
    (effectiveRisk === 'likely_not_condo' || effectiveSale === 'yes') &&
    commandCenterData.mail_queue_status !== 'queued'

  const handleAddToMail = async () => {
    setMailMessage(null)
    setMailPending(true)
    try {
      if (onAddToMailQueue) {
        await onAddToMailQueue()
      } else {
        const result = await openLetterService.enqueue([leadId])
        setMailMessage(
          `Added to mail queue (${result.queued_count}/${result.batch_minimum})`,
        )
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        await queryClient.invalidateQueries({ queryKey: ['mail-queue'] })
        await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
      }
    } catch (err) {
      setMailMessage(err instanceof Error ? err.message : 'Failed to add to mail queue')
    } finally {
      setMailPending(false)
    }
  }

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100%', sm: 520 } } }}
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
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Lead PIN: {commandCenterData.county_assessor_pin}
            {commandCenterData.assessor_class ? ` · Class ${commandCenterData.assessor_class}` : ''}
          </Typography>
        )}

        <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }} data-testid="ownership-imported-units">
          <Typography variant="subtitle2" gutterBottom>
            Imported units
          </Typography>
          <Typography variant="body2">
            {units != null
              ? `From import: ${units} unit${units === 1 ? '' : 's'}`
              : 'No unit count on this lead from import.'}
            {unitsAllowed != null ? ` · Units allowed: ${unitsAllowed}` : ''}
          </Typography>
        </Paper>

        <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', gap: 1 }}>
          {displayRisk && (
            <Chip
              size="small"
              label={RISK_LABELS[displayRisk] ?? displayRisk.replace(/_/g, ' ')}
              data-testid="condo-risk-chip"
            />
          )}
          {displaySale && (
            <Chip
              size="small"
              variant="outlined"
              label={`Whole-building sale: ${displaySale}`}
            />
          )}
        </Stack>

        {!hasAnalysis && !analyzeMutation.isPending && !analyzeSnapshot && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Building ownership has not been verified yet. Run an automated check using Cook County
            assessor data.
          </Alert>
        )}

        <Button
          variant="contained"
          fullWidth
          disabled={analyzeMutation.isPending}
          onClick={() => {
            setAnalyzeFeedback(null)
            analyzeMutation.mutate()
          }}
          data-testid="run-building-ownership-check"
          sx={{ mb: 2 }}
        >
          {analyzeMutation.isPending ? (
            <CircularProgress size={22} color="inherit" />
          ) : (
            'Run automated check'
          )}
        </Button>

        {analyzeFeedback && (
          <Alert
            severity={analyzeSnapshot?.skipped ? 'info' : 'success'}
            sx={{ mb: 2 }}
            data-testid="building-ownership-analyze-feedback"
          >
            {analyzeFeedback}
          </Alert>
        )}

        {analyzeMutation.isError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {analyzeMutation.error instanceof Error
              ? analyzeMutation.error.message
              : 'Analysis failed'}
          </Alert>
        )}

        {isLoading && hasAnalysis && !analyzeSnapshot && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
            <CircularProgress size={28} />
          </Box>
        )}

        {error && hasAnalysis && !analyzeSnapshot && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Could not load analysis details. Try running the check again.
          </Alert>
        )}

        {showDecisionForm && (
          <>
            <Typography variant="subtitle2" gutterBottom>
              System recommendation
            </Typography>
            <Paper variant="outlined" sx={{ p: 1.5, mb: 2 }}>
              <Typography variant="body2">
                {(classification?.reason as string) ??
                  'No automated reason recorded yet. Run the check or save your decision below.'}
              </Typography>
              {classification?.confidence != null && (
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                  Confidence: {String(classification.confidence)}
                </Typography>
              )}
            </Paper>

            <Typography variant="subtitle2" gutterBottom>
              What we found — PINs at address ({pinCount || assessorPins.length || 0})
            </Typography>
            <Alert severity="info" sx={{ mb: 1.5 }} data-testid="pin-explanation">
              {pinExplanation(pinCount || assessorPins.length, units, assessorPins)}
            </Alert>

            {assessorPins.length > 0 ? (
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
                    {assessorPins.map((row, index) => (
                      <TableRow key={row.pin ?? `pin-row-${index}`}>
                        <TableCell>{row.pin ?? '—'}</TableCell>
                        <TableCell>{row.property_class ?? '—'}</TableCell>
                        <TableCell>{row.is_condo_class ? 'Yes' : 'No'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            ) : (
              <Alert severity="warning" sx={{ mb: 2 }} data-testid="pins-empty-state">
                No assessor PINs were returned for this address. You can still save an ownership
                decision based on research.
              </Alert>
            )}

            <Divider sx={{ my: 2 }} />
            <Typography variant="subtitle2" gutterBottom>
              Your decision
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
              Saves condo risk on this lead and rescores the recommended action. Use this when the
              automated check is wrong or ambiguous (for example a 2-unit building with two PINs).
            </Typography>
            <Stack
              spacing={2}
              component="form"
              onSubmit={(e) => {
                e.preventDefault()
                if (!overrideReason.trim()) {
                  setFormError('Reason is required.')
                  return
                }
                overrideMutation.mutate()
              }}
            >
              <FormControl fullWidth size="small">
                <InputLabel>Building type</InputLabel>
                <Select
                  value={overrideStatus}
                  label="Building type"
                  onChange={(e) => setOverrideStatus(e.target.value as CondoRiskStatus)}
                >
                  {RISK_STATUS_OPTIONS.map((opt) => (
                    <MenuItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl fullWidth size="small">
                <InputLabel>Whole-building sale possible?</InputLabel>
                <Select
                  value={overrideBuildingSale}
                  label="Whole-building sale possible?"
                  onChange={(e) =>
                    setOverrideBuildingSale(e.target.value as BuildingSalePossible)
                  }
                >
                  {BUILDING_SALE_OPTIONS.map((opt) => (
                    <MenuItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </MenuItem>
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
                variant="contained"
                disabled={overrideMutation.isPending}
                data-testid="confirm-building-ownership"
              >
                {overrideMutation.isPending ? 'Saving…' : 'Save ownership decision'}
              </Button>
            </Stack>
          </>
        )}

        {showMailCta && (
          <>
            <Divider sx={{ my: 2 }} />
            <Typography variant="subtitle2" gutterBottom>
              Next step
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              This looks like a whole-building (non-condo) opportunity with a mailing address.
            </Typography>
            <Button
              variant="contained"
              color="secondary"
              fullWidth
              disabled={mailPending}
              onClick={() => void handleAddToMail()}
              data-testid="ownership-add-to-mail-queue"
            >
              {mailPending ? <CircularProgress size={22} color="inherit" /> : 'Add to Mail Queue'}
            </Button>
            {mailMessage && (
              <Alert severity="info" sx={{ mt: 1 }}>
                {mailMessage}
              </Alert>
            )}
          </>
        )}

        <Divider sx={{ my: 2 }} />
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
          Optional: create a to-do for later. This does not change ownership status or scoring.
        </Typography>
        <Button
          variant="text"
          size="small"
          onClick={() => createTaskMutation.mutate()}
          disabled={createTaskMutation.isPending}
          data-testid="create-ownership-follow-up-task"
        >
          Create follow-up task
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
