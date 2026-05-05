import React, { useState } from 'react'
import {
  Box,
  Drawer,
  Typography,
  IconButton,
  Divider,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Button,
  Alert,
  CircularProgress,
  Stack,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { condoFilterService } from '@/services/condoFilterApi'
import type {
  CondoRiskStatus,
  BuildingSalePossible,
  CondoOverrideRequest,
} from '@/types'

export interface CondoDetailViewProps {
  analysisId: number | null
  open: boolean
  onClose: () => void
}

const RISK_STATUS_OPTIONS: { value: CondoRiskStatus; label: string }[] = [
  { value: 'likely_condo', label: 'Likely Condo' },
  { value: 'likely_not_condo', label: 'Likely Not Condo' },
  { value: 'partial_condo_possible', label: 'Partial Condo Possible' },
  { value: 'needs_review', label: 'Needs Review' },
  { value: 'unknown', label: 'Unknown' },
]

const BUILDING_SALE_OPTIONS: { value: BuildingSalePossible; label: string }[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'unknown', label: 'Unknown' },
]

export const CondoDetailView: React.FC<CondoDetailViewProps> = ({
  analysisId,
  open,
  onClose,
}) => {
  const queryClient = useQueryClient()

  const [overrideStatus, setOverrideStatus] = useState<CondoRiskStatus>('needs_review')
  const [overrideBuildingSale, setOverrideBuildingSale] = useState<BuildingSalePossible>('unknown')
  const [overrideReason, setOverrideReason] = useState('')
  const [overrideError, setOverrideError] = useState<string | null>(null)

  // Reset form state when a different analysis is opened
  React.useEffect(() => {
    setOverrideStatus('needs_review')
    setOverrideBuildingSale('unknown')
    setOverrideReason('')
    setOverrideError(null)
  }, [analysisId])

  const { data: detail, isLoading, error } = useQuery({
    queryKey: ['condoFilterDetail', analysisId],
    queryFn: () => condoFilterService.getDetail(analysisId!),
    enabled: open && analysisId !== null,
  })

  const overrideMutation = useMutation({
    mutationFn: (data: CondoOverrideRequest) =>
      condoFilterService.applyOverride(analysisId!, data),
    onSuccess: () => {
      setOverrideError(null)
      setOverrideReason('')
      queryClient.invalidateQueries({ queryKey: ['condoFilterDetail', analysisId] })
      queryClient.invalidateQueries({ queryKey: ['condoFilterResults'] })
    },
    onError: (err: Error) => {
      setOverrideError(err.message || 'Failed to apply override.')
    },
  })

  const handleOverrideSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!overrideReason.trim()) {
      setOverrideError('Reason is required.')
      return
    }
    overrideMutation.mutate({
      condo_risk_status: overrideStatus,
      building_sale_possible: overrideBuildingSale,
      reason: overrideReason.trim(),
    })
  }

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: { xs: '100%', sm: 600, md: 700 } } }}
    >
      <Box sx={{ p: 3 }}>
        {/* Header */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6" component="h2">
            Address Group Detail
          </Typography>
          <IconButton onClick={onClose} aria-label="Close detail view">
            <CloseIcon />
          </IconButton>
        </Box>

        <Divider sx={{ mb: 2 }} />

        {/* Loading */}
        {isLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress aria-label="Loading detail" />
          </Box>
        )}

        {/* Error */}
        {error && (
          <Alert severity="error">
            {error instanceof Error ? error.message : 'Failed to load detail.'}
          </Alert>
        )}

        {/* Detail Content */}
        {detail && (
          <>
            {/* Analysis Metrics */}
            <Typography variant="subtitle1" gutterBottom fontWeight="bold">
              {detail.normalized_address}
            </Typography>

            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: '1fr 1fr', sm: '1fr 1fr 1fr' },
                gap: 1,
                mb: 2,
              }}
            >
              <MetricItem label="Risk Status" value={detail.condo_risk_status.replace(/_/g, ' ')} />
              <MetricItem label="Building Sale" value={detail.building_sale_possible} />
              <MetricItem label="Properties" value={String(detail.property_count)} />
              <MetricItem label="PINs" value={String(detail.pin_count)} />
              <MetricItem label="Owners" value={String(detail.owner_count)} />
              <MetricItem label="Has Unit #" value={detail.has_unit_number ? 'Yes' : 'No'} />
              <MetricItem label="Condo Language" value={detail.has_condo_language ? 'Yes' : 'No'} />
              <MetricItem label="Missing PINs" value={String(detail.missing_pin_count)} />
              <MetricItem label="Missing Owners" value={String(detail.missing_owner_count)} />
            </Box>

            {/* Classification Details */}
            {detail.analysis_details && (
              <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Classification Details
                </Typography>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  <strong>Confidence:</strong> {detail.analysis_details.confidence}
                </Typography>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  <strong>Reason:</strong> {detail.analysis_details.reason}
                </Typography>
                <Box sx={{ mt: 1 }}>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    <strong>Triggered Rules:</strong>
                  </Typography>
                  <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                    {detail.analysis_details.triggered_rules.map((rule) => (
                      <Chip key={rule} label={rule} size="small" variant="outlined" />
                    ))}
                  </Stack>
                </Box>
              </Paper>
            )}

            {/* Manual Override Info */}
            {detail.manually_reviewed && detail.manual_override_status && (
              <Paper variant="outlined" sx={{ p: 2, mb: 2, borderColor: 'primary.main' }}>
                <Typography variant="subtitle2" gutterBottom color="primary">
                  Manual Override Applied
                </Typography>
                <Typography variant="body2">
                  <strong>Override Status:</strong> {detail.manual_override_status}
                </Typography>
                {detail.manual_override_reason && (
                  <Typography variant="body2">
                    <strong>Reason:</strong> {detail.manual_override_reason}
                  </Typography>
                )}
              </Paper>
            )}

            <Divider sx={{ my: 2 }} />

            {/* Linked Leads Table */}
            <Typography variant="subtitle2" gutterBottom>
              Linked Properties ({detail.leads.length})
            </Typography>
            <TableContainer component={Paper} variant="outlined" sx={{ mb: 3, maxHeight: 300 }}>
              <Table size="small" stickyHeader aria-label="Linked lead records">
                <TableHead>
                  <TableRow>
                    <TableCell>Address</TableCell>
                    <TableCell>PIN</TableCell>
                    <TableCell>Owner(s)</TableCell>
                    <TableCell>Property Type</TableCell>
                    <TableCell>Assessor Class</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {detail.leads.map((lead) => (
                    <TableRow key={lead.id}>
                      <TableCell>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 160 }}>
                          {lead.property_street}
                        </Typography>
                      </TableCell>
                      <TableCell>{lead.county_assessor_pin || '—'}</TableCell>
                      <TableCell>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 140 }}>
                          {formatOwnerNames(lead)}
                        </Typography>
                      </TableCell>
                      <TableCell>{lead.property_type || '—'}</TableCell>
                      <TableCell>{lead.assessor_class || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <Divider sx={{ my: 2 }} />

            {/* Manual Override Form */}
            <Typography variant="subtitle2" gutterBottom>
              Manual Override
            </Typography>
            <Box component="form" onSubmit={handleOverrideSubmit}>
              <Stack spacing={2}>
                <FormControl size="small" fullWidth>
                  <InputLabel id="override-status-label">Condo Risk Status</InputLabel>
                  <Select
                    labelId="override-status-label"
                    value={overrideStatus}
                    label="Condo Risk Status"
                    onChange={(e) => setOverrideStatus(e.target.value as CondoRiskStatus)}
                  >
                    {RISK_STATUS_OPTIONS.map((opt) => (
                      <MenuItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <FormControl size="small" fullWidth>
                  <InputLabel id="override-building-sale-label">Building Sale Possible</InputLabel>
                  <Select
                    labelId="override-building-sale-label"
                    value={overrideBuildingSale}
                    label="Building Sale Possible"
                    onChange={(e) => setOverrideBuildingSale(e.target.value as BuildingSalePossible)}
                  >
                    {BUILDING_SALE_OPTIONS.map((opt) => (
                      <MenuItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>

                <TextField
                  size="small"
                  label="Reason"
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  multiline
                  rows={3}
                  fullWidth
                  required
                  inputProps={{ maxLength: 1000 }}
                  helperText={`${overrideReason.length}/1000`}
                />

                {overrideError && (
                  <Alert severity="error" onClose={() => setOverrideError(null)}>
                    {overrideError}
                  </Alert>
                )}

                {overrideMutation.isSuccess && (
                  <Alert severity="success">Override applied successfully.</Alert>
                )}

                <Button
                  type="submit"
                  variant="contained"
                  disabled={overrideMutation.isPending}
                  startIcon={overrideMutation.isPending ? <CircularProgress size={16} /> : undefined}
                >
                  {overrideMutation.isPending ? 'Applying...' : 'Apply Override'}
                </Button>
              </Stack>
            </Box>
          </>
        )}
      </Box>
    </Drawer>
  )
}

/** Helper to format owner names from a lead record. */
function formatOwnerNames(lead: { owner_first_name: string | null; owner_last_name: string | null; owner_2_first_name: string | null; owner_2_last_name: string | null }): string {
  const names: string[] = []
  if (lead.owner_first_name || lead.owner_last_name) {
    names.push([lead.owner_first_name, lead.owner_last_name].filter(Boolean).join(' '))
  }
  if (lead.owner_2_first_name || lead.owner_2_last_name) {
    names.push([lead.owner_2_first_name, lead.owner_2_last_name].filter(Boolean).join(' '))
  }
  return names.length > 0 ? names.join('; ') : '—'
}

/** Small metric display component. */
function MetricItem({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
  )
}
