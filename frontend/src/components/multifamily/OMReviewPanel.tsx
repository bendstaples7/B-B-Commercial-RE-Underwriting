/**
 * OMReviewPanel — main review UI for a Commercial OM PDF Intake job in REVIEW status.
 *
 * Composes:
 *   - Intake_Status chip (always visible)
 *   - Extracted property fields with confidence scores (amber + warning icon if < 0.7)
 *   - Links to up to 5 existing Deals whose address matches property_address
 *   - OMScenarioTable (three-scenario side-by-side metrics)
 *   - OMUnitMixComparison (editable per-unit-type rent rows)
 *   - OMDataWarnings (consistency warnings)
 *   - Blocking alerts for asking_price_missing_error / unit_count_missing_error
 *   - "Confirm" button → calls confirmOMJob → navigates to /multifamily/deals/:dealId
 *
 * Requirements: 6.1, 6.2, 6.3, 6.6, 6.13, 7.10, 7.11, 12.3
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Link,
  Paper,
  Tooltip,
  Typography,
} from '@mui/material'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import type {
  OMIntakeReviewData,
  ExtractedOMData,
  OMFieldValue,
  UnitMixComparisonRow,
  DealSummary,
  IntakeStatus,
} from '@/types'
import { omIntakeService, multifamilyService } from '@/services/api'
import { OMScenarioTable } from './OMScenarioTable'
import OMUnitMixComparison from './OMUnitMixComparison'
import { OMDataWarnings } from './OMDataWarnings'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface OMReviewPanelProps {
  reviewData: OMIntakeReviewData
  jobId: number
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Confidence threshold below which a field is flagged with amber + warning icon. */
const LOW_CONFIDENCE_THRESHOLD = 0.7

/** Maximum number of matching deals to show. */
const MAX_DEAL_LINKS = 5

// ---------------------------------------------------------------------------
// Status chip color mapping
// ---------------------------------------------------------------------------

type ChipColor = 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'

function statusChipColor(status: IntakeStatus): ChipColor {
  switch (status) {
    case 'PENDING':
    case 'PARSING':
    case 'EXTRACTING':
    case 'RESEARCHING':
      return 'info'
    case 'REVIEW':
      return 'warning'
    case 'CONFIRMED':
      return 'success'
    case 'FAILED':
      return 'error'
    default:
      return 'default'
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a field value for display. */
function formatFieldValue(fieldName: string, value: unknown): string {
  if (value === null || value === undefined) return '—'

  const name = fieldName.toLowerCase()

  if (name === 'asking_price') {
    const num = Number(value)
    if (!isFinite(num)) return String(value)
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0,
    }).format(num)
  }

  if (name === 'building_sqft') {
    const num = Number(value)
    if (!isFinite(num)) return String(value)
    return `${new Intl.NumberFormat('en-US').format(Math.round(num))} sqft`
  }

  return String(value)
}

/** Human-readable label for a field key. */
function fieldLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Simple case-insensitive substring match for address similarity.
 * Returns true if dealAddress contains any significant word (≥4 chars) from
 * propertyAddress, or if one is a substring of the other.
 */
function addressMatches(dealAddress: string, propertyAddress: string): boolean {
  const deal = dealAddress.toLowerCase().trim()
  const prop = propertyAddress.toLowerCase().trim()
  if (!prop || !deal) return false
  if (deal.includes(prop) || prop.includes(deal)) return true
  const words = prop.split(/\s+/).filter((w) => w.length >= 4)
  return words.some((word) => deal.includes(word))
}

// ---------------------------------------------------------------------------
// Sub-component: single extracted field row
// ---------------------------------------------------------------------------

interface FieldRowProps {
  fieldName: string
  fieldValue: OMFieldValue<unknown>
}

function FieldRow({ fieldName, fieldValue }: FieldRowProps) {
  const isLowConfidence = fieldValue.confidence < LOW_CONFIDENCE_THRESHOLD
  const confidencePct = `${Math.round(fieldValue.confidence * 100)}%`

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        px: 1.5,
        py: 0.75,
        borderRadius: 1,
        backgroundColor: isLowConfidence ? 'warning.light' : 'transparent',
        border: '1px solid',
        borderColor: isLowConfidence ? 'warning.main' : 'transparent',
      }}
    >
      {/* Warning icon for low-confidence fields */}
      {isLowConfidence ? (
        <Tooltip title={`Low confidence: ${confidencePct}`} arrow>
          <WarningAmberIcon
            fontSize="small"
            sx={{ color: 'warning.dark', flexShrink: 0 }}
            aria-label="Low confidence warning"
          />
        </Tooltip>
      ) : (
        <CheckCircleOutlineIcon
          fontSize="small"
          sx={{ color: 'success.main', flexShrink: 0, opacity: 0.6 }}
          aria-hidden="true"
        />
      )}

      {/* Field label */}
      <Typography variant="body2" sx={{ fontWeight: 500, minWidth: 160, flexShrink: 0 }}>
        {fieldLabel(fieldName)}
      </Typography>

      {/* Field value */}
      <Typography variant="body2" sx={{ flexGrow: 1 }}>
        {formatFieldValue(fieldName, fieldValue.value)}
      </Typography>

      {/* Confidence score */}
      <Tooltip title="Extraction confidence" arrow>
        <Typography
          variant="caption"
          sx={{
            color: isLowConfidence ? 'warning.dark' : 'text.secondary',
            fontWeight: isLowConfidence ? 600 : 400,
            flexShrink: 0,
          }}
        >
          {confidencePct}
        </Typography>
      </Tooltip>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Extracted fields to display (per task spec)
// ---------------------------------------------------------------------------

const PROPERTY_FIELDS: Array<keyof ExtractedOMData> = [
  'property_address',
  'property_city',
  'property_state',
  'property_zip',
  'asking_price',
  'unit_count',
  'year_built',
  'building_sqft',
  'neighborhood',
  'zoning',
]

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function OMReviewPanel({ reviewData, jobId }: OMReviewPanelProps) {
  const navigate = useNavigate()

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------

  /** Current unit mix rows — may be updated by OMUnitMixComparison edits. */
  const [unitMixRows, setUnitMixRows] = useState<UnitMixComparisonRow[]>(
    reviewData.scenario_comparison?.unit_mix_comparison ?? [],
  )

  /** Deals whose address matches the extracted property address. */
  const [matchingDeals, setMatchingDeals] = useState<DealSummary[]>([])

  /** Whether we're currently submitting the confirm request. */
  const [confirming, setConfirming] = useState(false)

  /** Error message from a failed confirm attempt. */
  const [confirmError, setConfirmError] = useState<string | null>(null)

  // -------------------------------------------------------------------------
  // Load matching deals on mount
  // -------------------------------------------------------------------------

  useEffect(() => {
    const propertyAddress =
      reviewData.extracted_om_data?.property_address?.value ?? null

    if (!propertyAddress) return

    multifamilyService
      .listDeals()
      .then((deals) => {
        const matches = deals
          .filter((d) => addressMatches(d.property_address, propertyAddress))
          .slice(0, MAX_DEAL_LINKS)
        setMatchingDeals(matches)
      })
      .catch(() => {
        // Non-critical — silently ignore deal lookup failures
      })
  }, [reviewData.extracted_om_data?.property_address?.value])

  // -------------------------------------------------------------------------
  // Unit mix change handler
  // -------------------------------------------------------------------------

  const handleUnitMixRowsChange = useCallback(
    (updatedRows: UnitMixComparisonRow[], _overriddenFields: Set<string>) => {
      setUnitMixRows(updatedRows)
    },
    [],
  )

  // -------------------------------------------------------------------------
  // Build confirmedData from current state
  // -------------------------------------------------------------------------

  function buildConfirmedData() {
    const om = reviewData.extracted_om_data

    return {
      asking_price: om?.asking_price?.value ?? null,
      unit_count: om?.unit_count?.value ?? null,
      property_address: om?.property_address?.value ?? undefined,
      property_city: om?.property_city?.value ?? undefined,
      property_state: om?.property_state?.value ?? undefined,
      property_zip: om?.property_zip?.value ?? undefined,
      unit_mix: unitMixRows.map((row) => ({
        unit_type_label: row.unit_type_label,
        unit_count: row.unit_count,
        sqft: row.sqft !== null ? parseFloat(row.sqft) : 0,
        current_avg_rent:
          row.current_avg_rent !== null ? parseFloat(row.current_avg_rent) : null,
        proforma_rent:
          row.proforma_rent !== null ? parseFloat(row.proforma_rent) : null,
        market_rent_estimate:
          row.market_rent_estimate !== null ? parseFloat(row.market_rent_estimate) : null,
      })),
      expense_items:
        om?.expense_items?.map((item) => ({
          label: item.label.value ?? '',
          current_annual_amount:
            item.current_annual_amount.value !== null
              ? Number(item.current_annual_amount.value)
              : null,
          proforma_annual_amount:
            item.proforma_annual_amount.value !== null
              ? Number(item.proforma_annual_amount.value)
              : undefined,
        })) ?? [],
      other_income_items:
        om?.other_income_items?.map((item) => ({
          label: item.label.value ?? '',
          annual_amount:
            item.annual_amount.value !== null ? Number(item.annual_amount.value) : 0,
        })) ?? [],
    }
  }

  // -------------------------------------------------------------------------
  // Confirm handler
  // -------------------------------------------------------------------------

  const handleConfirm = async () => {
    setConfirming(true)
    setConfirmError(null)

    try {
      const confirmedData = buildConfirmedData()
      const result = await omIntakeService.confirmOMJob(jobId, confirmedData)
      navigate(`/multifamily/deals/${result.deal_id}`)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Confirmation failed. Please try again.'
      setConfirmError(message)
    } finally {
      setConfirming(false)
    }
  }

  // -------------------------------------------------------------------------
  // Derived values
  // -------------------------------------------------------------------------

  const om = reviewData.extracted_om_data
  const hasBlockingErrors =
    reviewData.asking_price_missing_error === true ||
    reviewData.unit_count_missing_error === true

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* ------------------------------------------------------------------ */}
      {/* Header: status chip + filename                                       */}
      {/* ------------------------------------------------------------------ */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <Typography variant="h5" component="h1" sx={{ flexGrow: 1 }}>
          OM Review
        </Typography>
        <Chip
          label={reviewData.intake_status}
          color={statusChipColor(reviewData.intake_status)}
          size="medium"
          aria-label={`Intake status: ${reviewData.intake_status}`}
        />
        {reviewData.original_filename && (
          <Typography variant="body2" color="text.secondary" noWrap>
            {reviewData.original_filename}
          </Typography>
        )}
      </Box>

      {/* ------------------------------------------------------------------ */}
      {/* Blocking error alerts                                                */}
      {/* ------------------------------------------------------------------ */}
      {reviewData.asking_price_missing_error && (
        <Alert severity="error" aria-live="assertive">
          <strong>Asking price is missing.</strong> The extracted data does not contain an asking
          price. Confirmation is blocked until this is resolved.
        </Alert>
      )}
      {reviewData.unit_count_missing_error && (
        <Alert severity="error" aria-live="assertive">
          <strong>Unit count is missing.</strong> The extracted data does not contain a unit count.
          Confirmation is blocked until this is resolved.
        </Alert>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Extracted property fields                                            */}
      {/* ------------------------------------------------------------------ */}
      {om && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Extracted Property Fields
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1.5, display: 'block' }}>
            Fields with confidence below 70% are highlighted in amber.
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
            {PROPERTY_FIELDS.map((key) => {
              const fieldValue = om[key] as OMFieldValue<unknown> | undefined
              if (!fieldValue) return null
              return <FieldRow key={key} fieldName={key} fieldValue={fieldValue} />
            })}
          </Box>
        </Paper>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Matching deals                                                       */}
      {/* ------------------------------------------------------------------ */}
      {matchingDeals.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Existing Deals with Similar Address
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Up to {MAX_DEAL_LINKS} deals whose address matches the extracted property address.
          </Typography>
          <Box component="ul" sx={{ m: 0, pl: 2 }}>
            {matchingDeals.map((deal) => (
              <Box component="li" key={deal.id} sx={{ mb: 0.5 }}>
                <Link
                  href={`/multifamily/deals/${deal.id}`}
                  underline="hover"
                  aria-label={`Open deal ${deal.id}: ${deal.property_address}`}
                >
                  {deal.property_address}
                </Link>
                <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                  ({deal.unit_count} units · {deal.status})
                </Typography>
              </Box>
            ))}
          </Box>
        </Paper>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Scenario comparison table                                            */}
      {/* ------------------------------------------------------------------ */}
      {reviewData.scenario_comparison && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="h6" gutterBottom>
            Scenario Comparison
          </Typography>
          <OMScenarioTable comparison={reviewData.scenario_comparison} />
        </Paper>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Unit mix comparison (editable)                                       */}
      {/* ------------------------------------------------------------------ */}
      {unitMixRows.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <OMUnitMixComparison rows={unitMixRows} onRowsChange={handleUnitMixRowsChange} />
        </Paper>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Data warnings                                                        */}
      {/* ------------------------------------------------------------------ */}
      {(reviewData.consistency_warnings?.length ?? 0) > 0 && (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <OMDataWarnings warnings={reviewData.consistency_warnings} />
        </Paper>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Confirm error alert                                                  */}
      {/* ------------------------------------------------------------------ */}
      {confirmError && (
        <Alert severity="error" onClose={() => setConfirmError(null)} aria-live="assertive">
          {confirmError}
        </Alert>
      )}

      <Divider />

      {/* ------------------------------------------------------------------ */}
      {/* Confirm button                                                       */}
      {/* ------------------------------------------------------------------ */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button
          variant="contained"
          color="primary"
          size="large"
          disabled={confirming || hasBlockingErrors}
          onClick={handleConfirm}
          startIcon={
            confirming ? <CircularProgress size={18} color="inherit" /> : undefined
          }
          aria-label="Confirm OM intake and create deal"
        >
          {confirming ? 'Confirming…' : 'Confirm'}
        </Button>
      </Box>
    </Box>
  )
}

export default OMReviewPanel
