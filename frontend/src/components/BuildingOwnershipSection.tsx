import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  FormControl,
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
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { buildingOwnershipService } from '@/services/api'
import { formatDateTime } from '@/utils/formatters'
import { ccMetaSx, ccSupportCardSx, ccSubsectionTitleSx } from '@/components/lead-detail/commandCenterChrome'
import type {
  BuildingOwnershipAnalyzeResult,
  BuildingOwnershipDetail,
  BuildingSalePossible,
  CommandCenterPayload,
  CondoRiskStatus,
} from '@/types'

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

type CondoizedAnswer = 'yes' | 'no' | 'unclear'

type AssessorPinRow = {
  pin?: string
  property_class?: string
  is_condo_class?: boolean
}

function pinExplanation(
  pinCount: number,
  units: number | null | undefined,
  pins: AssessorPinRow[],
): string {
  const anyCondoClass = pins.some((p) => p.is_condo_class)
  if (pinCount <= 1) {
    return anyCondoClass
      ? 'Single PIN with a condo-coded assessor class.'
      : 'Single PIN · no condo class on the assessor record.'
  }
  const unitBit = units != null ? ` Imported units: ${units}.` : ''
  if (units != null && pinCount === units && !anyCondoClass) {
    return (
      `${pinCount} PINs at this address · no condo class.${unitBit} ` +
      `Often a ${units}-unit building (one PIN per unit), not a condo association.`
    )
  }
  return (
    `${pinCount} PINs at this address` +
    (anyCondoClass ? ' · at least one condo-coded class.' : ' · no condo class.') +
    unitBit +
    ' Multiple PINs alone do not mean condo.'
  )
}

function statusNeedsDecision(status: CondoRiskStatus | null | undefined): boolean {
  return (
    status == null ||
    status === 'needs_review' ||
    status === 'partial_condo_possible' ||
    status === 'unknown'
  )
}

function statusToCondoized(status: CondoRiskStatus | null | undefined): CondoizedAnswer | null {
  if (!status) return null
  if (status === 'likely_condo') return 'yes'
  if (status === 'likely_not_condo') return 'no'
  return 'unclear'
}

function condoizedToOverride(answer: CondoizedAnswer): {
  condo_risk_status: CondoRiskStatus
  building_sale_possible: BuildingSalePossible
} {
  if (answer === 'yes') {
    return { condo_risk_status: 'likely_condo', building_sale_possible: 'no' }
  }
  if (answer === 'no') {
    return { condo_risk_status: 'likely_not_condo', building_sale_possible: 'yes' }
  }
  return { condo_risk_status: 'needs_review', building_sale_possible: 'unknown' }
}

export interface BuildingOwnershipSectionProps {
  leadId: number
  commandCenterData: CommandCenterPayload
}

/**
 * Inline Command Center section for commercial building ownership / condo risk.
 * Shows analysis results by default; only exposes actions when a decision is still needed.
 */
export function BuildingOwnershipSection({
  leadId,
  commandCenterData,
}: BuildingOwnershipSectionProps) {
  const queryClient = useQueryClient()
  const [decisionOpen, setDecisionOpen] = useState(false)
  const [overrideStatus, setOverrideStatus] = useState<CondoRiskStatus>(
    commandCenterData.condo_risk_status ?? 'needs_review',
  )
  const [overrideBuildingSale, setOverrideBuildingSale] = useState<BuildingSalePossible>(
    commandCenterData.building_sale_possible ?? 'unknown',
  )
  const [overrideReason, setOverrideReason] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [analyzeFeedback, setAnalyzeFeedback] = useState<string | null>(null)
  const [analyzeSnapshot, setAnalyzeSnapshot] = useState<BuildingOwnershipAnalyzeResult | null>(
    null,
  )

  const hasAnalysisId = Boolean(
    commandCenterData.condo_analysis_id || analyzeSnapshot?.condo_analysis_id,
  )
  const isCommercial = (commandCenterData.lead_category ?? '').toLowerCase() === 'commercial'
  const showSection =
    isCommercial ||
    hasAnalysisId ||
    Boolean(commandCenterData.condo_risk_status) ||
    Boolean(commandCenterData.building_sale_possible)

  const { data: detail, isLoading, error, refetch } = useQuery<BuildingOwnershipDetail>({
    queryKey: ['buildingOwnership', leadId],
    queryFn: () => buildingOwnershipService.get(leadId),
    enabled: showSection && hasAnalysisId,
    retry: false,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    queryClient.invalidateQueries({ queryKey: ['buildingOwnership', leadId] })
  }

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      // Always force on explicit user click so PIN details refresh instead of a silent skip.
      const result = (await buildingOwnershipService.analyze(leadId, {
        force: true,
      })) as BuildingOwnershipAnalyzeResult
      return result
    },
    onSuccess: (result) => {
      setAnalyzeSnapshot(result)
      // Seed cache so PIN/reason render immediately from the analyze response
      // (skipped path returns the same shape as GET detail).
      if (result && (result as BuildingOwnershipDetail).id != null) {
        queryClient.setQueryData(['buildingOwnership', leadId], result)
      }
      setOverrideStatus((result?.condo_risk_status as CondoRiskStatus) ?? 'needs_review')
      setOverrideBuildingSale(
        (result?.building_sale_possible as BuildingSalePossible) ?? 'unknown',
      )
      setFormError(null)
      const pins = (result?.analysis_details?.assessor_pins ?? []) as AssessorPinRow[]
      if (result?.skipped) {
        setAnalyzeFeedback(
          pins.length > 0
            ? 'Analysis is already current.'
            : 'Analysis is already current, but no PIN details are stored for this record.',
        )
      } else {
        setAnalyzeFeedback('Analysis updated.')
      }
      invalidate()
      void refetch()
    },
  })

  const overrideMutation = useMutation({
    mutationFn: (payload: {
      condo_risk_status: CondoRiskStatus
      building_sale_possible: BuildingSalePossible
      reason: string
    }) => buildingOwnershipService.override(leadId, payload),
    onSuccess: () => {
      setFormError(null)
      setOverrideReason('')
      setDecisionOpen(false)
      setAnalyzeFeedback('Ownership decision saved. Recommended action has been rescored.')
      invalidate()
      void refetch()
    },
    onError: (err: Error) => setFormError(err.message || 'Save failed'),
  })

  if (!showSection) return null

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
  const saleDisplay = commandCenterData.most_recent_sale_display ?? null
  const needsDecision = statusNeedsDecision(displayRisk)
  const hasResults = Boolean(detail || analyzeSnapshot || displayRisk)
  const lastCheckedAt =
    detail?.analyzed_at
    || (analyzeSnapshot?.analysis_details as { analyzed_at?: string } | undefined)?.analyzed_at
    || null
  const condoizedValue = statusToCondoized(displayRisk)
  const confidence =
    classification?.confidence != null ? String(classification.confidence) : null

  const saveCondoized = (answer: CondoizedAnswer) => {
    if (answer === condoizedValue) return
    const mapped = condoizedToOverride(answer)
    setOverrideStatus(mapped.condo_risk_status)
    setOverrideBuildingSale(mapped.building_sale_possible)
    overrideMutation.mutate({
      ...mapped,
      reason: 'Set from Condoized? control',
    })
  }

  return (
    <Paper
      sx={ccSupportCardSx}
      data-testid="building-ownership-section"
      id="building-ownership-section"
    >
      <Typography sx={ccSubsectionTitleSx}>
        Building ownership
      </Typography>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        sx={{ mb: 1.5, flexWrap: 'wrap', gap: 1 }}
      >
        <Typography variant="body2" fontWeight={600} sx={{ mr: 0.5 }}>
          Condoized?
        </Typography>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={condoizedValue}
          disabled={overrideMutation.isPending || !hasAnalysisId}
          onChange={(_e, next: CondoizedAnswer | null) => {
            if (next) saveCondoized(next)
          }}
          data-testid="building-ownership-condoized-control"
        >
          <ToggleButton value="yes" data-testid="building-ownership-condoized-yes">
            Yes
          </ToggleButton>
          <ToggleButton value="no" data-testid="building-ownership-condoized-no">
            No
          </ToggleButton>
          <ToggleButton value="unclear" data-testid="building-ownership-condoized-unclear">
            Unclear
          </ToggleButton>
        </ToggleButtonGroup>
        {confidence && (
          <Chip
            size="small"
            variant="outlined"
            label={`${confidence} confidence`}
            data-testid="building-ownership-confidence"
          />
        )}
        {overrideMutation.isPending && <CircularProgress size={16} />}
      </Stack>

      {displaySale && (
        <Chip
          size="small"
          variant="outlined"
          label={`Whole-building sale: ${displaySale}`}
          sx={{ mb: 1.5 }}
        />
      )}

      {hasAnalysisId && lastCheckedAt && (
        <Typography
          sx={{ ...ccMetaSx, mb: 1.5 }}
          data-testid="building-ownership-last-checked"
        >
          Last automated check: {formatDateTime(lastCheckedAt)}
        </Typography>
      )}

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', sm: '140px 1fr' },
          columnGap: 1,
          rowGap: 0.75,
          mb: 1.5,
        }}
      >
        <Typography variant="caption" color="text.secondary">
          Imported units
        </Typography>
        <Typography variant="body2" data-testid="building-ownership-units">
          {units != null
            ? `${units} unit${units === 1 ? '' : 's'}${unitsAllowed != null ? ` · allowed ${unitsAllowed}` : ''}`
            : '—'}
        </Typography>

        <Typography variant="caption" color="text.secondary">
          Most recent sale
        </Typography>
        <Typography variant="body2" data-testid="building-ownership-sale">
          {saleDisplay || '—'}
        </Typography>

        {commandCenterData.county_assessor_pin && (
          <>
            <Typography variant="caption" color="text.secondary">
              Lead PIN
            </Typography>
            <Typography variant="body2">
              {commandCenterData.county_assessor_pin}
              {commandCenterData.assessor_class
                ? ` · Class ${commandCenterData.assessor_class}`
                : ''}
            </Typography>
          </>
        )}

        {hasResults && classification?.reason != null && (
          <>
            <Typography variant="caption" color="text.secondary">
              System note
            </Typography>
            <Typography variant="body2" data-testid="building-ownership-reason">
              {String(classification.reason)}
            </Typography>
          </>
        )}
      </Box>

      {isLoading && hasAnalysisId && !analyzeSnapshot && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {error && hasAnalysisId && !analyzeSnapshot && (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          Could not load PIN details. You can re-run the automated check if needed.
        </Alert>
      )}

      {assessorPins.length > 0 ? (
        <>
          <Typography sx={ccSubsectionTitleSx}>
            PINs at address ({pinCount || assessorPins.length})
          </Typography>
          <Typography sx={{ ...ccMetaSx, mb: 1 }} data-testid="building-ownership-pin-explanation">
            {pinExplanation(pinCount || assessorPins.length, units, assessorPins)}
          </Typography>
          <TableContainer sx={{ mb: 1.5 }}>
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
                  <TableRow key={row.pin ?? `pin-${index}`}>
                    <TableCell>{row.pin ?? '—'}</TableCell>
                    <TableCell>{row.property_class ?? '—'}</TableCell>
                    <TableCell>{row.is_condo_class ? 'Yes' : 'No'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      ) : (
        hasAnalysisId &&
        !isLoading && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            No PIN details stored for this analysis yet.
          </Typography>
        )
      )}

      {analyzeFeedback && (
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          sx={{ mb: 1 }}
          data-testid="building-ownership-analyze-feedback"
        >
          {analyzeFeedback}
        </Typography>
      )}

      {analyzeMutation.isError && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {analyzeMutation.error instanceof Error
            ? analyzeMutation.error.message
            : 'Analysis failed'}
        </Alert>
      )}

      {formError && !decisionOpen && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          {formError}
        </Alert>
      )}

      {/* Actions only when a decision is still needed or analysis has never run */}
      {(needsDecision || !hasAnalysisId) && (
        <>
          <Divider sx={{ my: 1.5 }} />
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
            <Button
              variant="outlined"
              size="small"
              disabled={analyzeMutation.isPending}
              onClick={() => {
                setAnalyzeFeedback(null)
                analyzeMutation.mutate()
              }}
              data-testid="building-ownership-run-check"
            >
              {analyzeMutation.isPending ? (
                <CircularProgress size={18} color="inherit" />
              ) : hasAnalysisId ? (
                'Re-run automated check'
              ) : (
                'Run automated check'
              )}
            </Button>
            {hasAnalysisId && (
              <Button
                variant="text"
                size="small"
                onClick={() => {
                  setOverrideStatus(displayRisk ?? 'needs_review')
                  setOverrideBuildingSale(displaySale ?? 'unknown')
                  setDecisionOpen((open) => !open)
                }}
                data-testid="building-ownership-toggle-decision"
              >
                {decisionOpen ? 'Hide advanced form' : 'Advanced ownership form'}
              </Button>
            )}
          </Stack>

          <Collapse in={decisionOpen}>
            <Box
              component="form"
              sx={{ mt: 2 }}
              onSubmit={(e) => {
                e.preventDefault()
                if (!overrideReason.trim()) {
                  setFormError('Reason is required.')
                  return
                }
                overrideMutation.mutate({
                  condo_risk_status: overrideStatus,
                  building_sale_possible: overrideBuildingSale,
                  reason: overrideReason.trim(),
                })
              }}
            >
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
                Saves condo risk and rescores the recommended action.
              </Typography>
              <Stack spacing={1.5}>
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
                  size="small"
                  disabled={overrideMutation.isPending}
                  data-testid="building-ownership-save-decision"
                >
                  {overrideMutation.isPending ? 'Saving…' : 'Save ownership decision'}
                </Button>
              </Stack>
            </Box>
          </Collapse>
        </>
      )}
    </Paper>
  )
}

export default BuildingOwnershipSection
