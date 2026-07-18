import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/Check'
import CloseIcon from '@mui/icons-material/Close'
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import { Link as RouterLink } from 'react-router-dom'
import type { PropertyMatchPreview, QueueRow } from '@/types'
import { LEAD_STATUS_LABELS } from '@/components/LeadStatusChip'
import { formatCookCountyPin } from '@/utils/cookCountyPin'

export interface PropertyMatchReviewCardProps {
  row: QueueRow
  preview: PropertyMatchPreview | null
  previewLoading: boolean
  index: number
  total: number
  onApprove: () => void
  onReject: () => void
  onSuppress: () => void
  onPrev: () => void
  onNext: () => void
  actionPending?: boolean
}

function formatAddress(parts: {
  property_street?: string | null
  property_city?: string | null
  property_state?: string | null
  property_zip?: string | null
} | null | undefined): string {
  if (!parts) return '—'
  return [
    parts.property_street,
    parts.property_city,
    parts.property_state,
    parts.property_zip,
  ].filter(Boolean).join(', ') || '—'
}

export function PropertyMatchReviewCard({
  row,
  preview,
  previewLoading,
  index,
  total,
  onApprove,
  onReject,
  onSuppress,
  onPrev,
  onNext,
  actionPending = false,
}: PropertyMatchReviewCardProps) {
  const ownerName = [row.owner_first_name, row.owner_last_name].filter(Boolean).join(' ') || 'Unknown owner'

  return (
    <Paper
      sx={{ p: { xs: 1.5, sm: 2 }, maxWidth: '100%', minWidth: 0, overflow: 'hidden' }}
      data-testid="property-match-review-card"
    >
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'stretch', sm: 'center' }}
        spacing={1}
        sx={{ mb: 2 }}
      >
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <Typography variant="h6" sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
            {ownerName}
          </Typography>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 0.5 }}>
            <Chip size="small" label={`Score ${row.lead_score}`} />
            {row.lead_status && (
              <Chip
                size="small"
                variant="outlined"
                label={LEAD_STATUS_LABELS[row.lead_status] ?? row.lead_status}
              />
            )}
          </Stack>
        </Box>
        <Stack direction="row" spacing={0.5} alignItems="center" justifyContent="flex-end">
          <IconButton onClick={onPrev} disabled={index <= 0} aria-label="Previous lead">
            <ChevronLeftIcon />
          </IconButton>
          <Typography variant="body2" color="text.secondary">
            {index + 1} / {total}
          </Typography>
          <IconButton onClick={onNext} disabled={index >= total - 1} aria-label="Next lead">
            <ChevronRightIcon />
          </IconButton>
        </Stack>
      </Stack>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <Box flex={1} sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" gutterBottom>As entered</Typography>
          <Typography
            variant="body2"
            data-testid="entered-address"
            sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
          >
            {formatAddress(preview?.entered_address ?? {
              property_street: row.property_street,
              property_city: row.property_city,
              property_state: row.property_state,
              property_zip: row.property_zip,
            })}
          </Typography>
        </Box>
        <Box flex={1} sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" gutterBottom>Recommended match</Typography>
          {previewLoading ? (
            <CircularProgress size={24} />
          ) : preview?.found ? (
            <>
              <Typography
                variant="body2"
                data-testid="recommended-address"
                sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
              >
                {formatAddress(preview.recommended_address)}
              </Typography>
              {preview.pin && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  display="block"
                  sx={{ overflowWrap: 'anywhere' }}
                >
                  PIN {formatCookCountyPin(preview.pin)}
                  {preview.connector ? ` · ${preview.connector}` : ''}
                </Typography>
              )}
              {preview.recommended_address?.property_type && (
                <Typography variant="caption" color="text.secondary" display="block">
                  Type: {preview.recommended_address.property_type}
                </Typography>
              )}
            </>
          ) : (
            <Typography
              variant="body2"
              color="text.secondary"
              data-testid="no-match-message"
              sx={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
            >
              {preview?.message ?? 'No assessor match found'}
            </Typography>
          )}
        </Box>
      </Stack>

      <Divider sx={{ mb: 2 }} />

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={2}
        alignItems="stretch"
        sx={{ width: '100%' }}
      >
        <Button
          variant="contained"
          color="success"
          size="large"
          startIcon={<CheckIcon />}
          onClick={onApprove}
          disabled={actionPending || previewLoading || !preview?.found}
          data-testid="approve-match-btn"
          sx={{ flex: 1, minHeight: 48, width: { xs: '100%', sm: 'auto' } }}
        >
          Approve match
        </Button>
        <Button
          variant="contained"
          color="error"
          size="large"
          startIcon={<CloseIcon />}
          onClick={onReject}
          disabled={actionPending}
          data-testid="reject-match-btn"
          sx={{ flex: 1, minHeight: 48, width: { xs: '100%', sm: 'auto' } }}
        >
          Reject
        </Button>
      </Stack>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        spacing={1}
        useFlexGap
        flexWrap="wrap"
        sx={{ mt: 2 }}
        justifyContent="space-between"
      >
        <Button
          component={RouterLink}
          to={`/leads/${row.id}`}
          size="small"
          sx={{ width: { xs: '100%', sm: 'auto' } }}
        >
          Open Command Center
        </Button>
        <Button
          size="small"
          color="warning"
          onClick={onSuppress}
          sx={{ width: { xs: '100%', sm: 'auto' } }}
        >
          Suppress
        </Button>
      </Stack>
    </Paper>
  )
}

export default PropertyMatchReviewCard
