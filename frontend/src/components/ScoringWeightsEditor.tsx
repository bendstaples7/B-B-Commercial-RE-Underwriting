import React, { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Paper,
  Typography,
  Slider,
  Button,
  CircularProgress,
  Alert,
  Divider,
  Tooltip,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/Save'
import RefreshIcon from '@mui/icons-material/Refresh'
import type { ScoringWeights } from '@/types'
import { leadService } from '@/services/leadApi'

/** Describes a single scoring criterion for the editor. */
interface CriterionConfig {
  key: keyof Pick<
    ScoringWeights,
    | 'property_characteristics_weight'
    | 'data_completeness_weight'
    | 'owner_situation_weight'
    | 'location_desirability_weight'
  >
  label: string
  description: string
}

const CRITERIA: CriterionConfig[] = [
  {
    key: 'property_characteristics_weight',
    label: 'Property Characteristics',
    description: 'Property type, condition, equity estimate',
  },
  {
    key: 'data_completeness_weight',
    label: 'Data Completeness',
    description: 'Percentage of lead fields populated',
  },
  {
    key: 'owner_situation_weight',
    label: 'Owner Situation',
    description: 'Length of ownership, absentee owner status',
  },
  {
    key: 'location_desirability_weight',
    label: 'Location Desirability',
    description: 'Market area attractiveness',
  },
]

const WEIGHT_STEP = 0.01
const WEIGHT_MIN = 0
const WEIGHT_MAX = 1

/** Tolerance for floating-point comparison when checking weight sum. */
const SUM_TOLERANCE = 0.005

/**
 * Editor for lead scoring criterion weights.
 *
 * Provides slider controls for each criterion, validates that weights sum to 1.0,
 * and triggers a bulk rescore on save.
 *
 * Requirements: 5.3, 5.4
 */
export const ScoringWeightsEditor: React.FC = () => {
  const [weights, setWeights] = useState<Record<CriterionConfig['key'], number>>({
    property_characteristics_weight: 0.3,
    data_completeness_weight: 0.2,
    owner_situation_weight: 0.3,
    location_desirability_weight: 0.2,
  })
  const [savedWeights, setSavedWeights] = useState<Record<CriterionConfig['key'], number> | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // Compute the current sum of all weights
  const weightSum = CRITERIA.reduce((sum, c) => sum + weights[c.key], 0)
  const isSumValid = Math.abs(weightSum - 1.0) < SUM_TOLERANCE

  // Check if weights have been modified from saved state
  const isDirty =
    savedWeights !== null &&
    CRITERIA.some((c) => Math.abs(weights[c.key] - savedWeights[c.key]) >= WEIGHT_STEP / 2)

  // Load current weights from the API
  const loadWeights = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await leadService.getScoringWeights()
      const loaded: Record<CriterionConfig['key'], number> = {
        property_characteristics_weight: data.property_characteristics_weight,
        data_completeness_weight: data.data_completeness_weight,
        owner_situation_weight: data.owner_situation_weight,
        location_desirability_weight: data.location_desirability_weight,
      }
      setWeights(loaded)
      setSavedWeights(loaded)
    } catch (err: any) {
      setError(err.message || 'Failed to load scoring weights.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadWeights()
  }, [loadWeights])

  // Handle slider change for a single criterion
  const handleWeightChange = (key: CriterionConfig['key'], value: number) => {
    setWeights((prev) => ({ ...prev, [key]: value }))
    setSuccessMessage(null)
  }

  // Reset weights to last saved state
  const handleReset = () => {
    if (savedWeights) {
      setWeights({ ...savedWeights })
    }
    setSuccessMessage(null)
    setError(null)
  }

  // Save weights and trigger bulk rescore
  const handleSave = async () => {
    if (!isSumValid) return

    setSaving(true)
    setError(null)
    setSuccessMessage(null)
    try {
      const result = await leadService.updateScoringWeights({
        property_characteristics_weight: weights.property_characteristics_weight,
        data_completeness_weight: weights.data_completeness_weight,
        owner_situation_weight: weights.owner_situation_weight,
        location_desirability_weight: weights.location_desirability_weight,
      })
      const updated: Record<CriterionConfig['key'], number> = {
        property_characteristics_weight: result.property_characteristics_weight,
        data_completeness_weight: result.data_completeness_weight,
        owner_situation_weight: result.owner_situation_weight,
        location_desirability_weight: result.location_desirability_weight,
      }
      setWeights(updated)
      setSavedWeights(updated)
      setSuccessMessage(
        `Weights saved. ${result.leads_rescored} lead${result.leads_rescored !== 1 ? 's' : ''} rescored.`,
      )
    } catch (err: any) {
      setError(err.message || 'Failed to save scoring weights.')
    } finally {
      setSaving(false)
    }
  }

  // Format weight as percentage for display
  const formatPercent = (value: number): string => `${Math.round(value * 100)}%`

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading scoring weights" />
      </Box>
    )
  }

  return (
    <Box component="section" aria-labelledby="scoring-weights-heading" sx={{ px: { xs: 1, sm: 2 } }}>
      <Typography variant="h5" id="scoring-weights-heading" component="h2" gutterBottom>
        Scoring Weights
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Adjust how each criterion contributes to the overall lead score. Weights must sum to 100%.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {successMessage && (
        <Alert severity="success" sx={{ mb: 2 }} role="status" onClose={() => setSuccessMessage(null)}>
          {successMessage}
        </Alert>
      )}

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        {CRITERIA.map((criterion, index) => (
          <Box key={criterion.key}>
            {index > 0 && <Divider sx={{ my: 2 }} />}
            <Box sx={{ mb: 1 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <Tooltip title={criterion.description} arrow>
                  <Typography
                    variant="subtitle1"
                    component="label"
                    id={`label-${criterion.key}`}
                    sx={{ fontWeight: 500, cursor: 'help' }}
                  >
                    {criterion.label}
                  </Typography>
                </Tooltip>
                <Typography
                  variant="body1"
                  sx={{ fontWeight: 600, minWidth: 48, textAlign: 'right' }}
                  aria-live="polite"
                >
                  {formatPercent(weights[criterion.key])}
                </Typography>
              </Box>
              <Typography variant="caption" color="text.secondary">
                {criterion.description}
              </Typography>
            </Box>
            <Slider
              value={weights[criterion.key]}
              onChange={(_e, value) => handleWeightChange(criterion.key, value as number)}
              min={WEIGHT_MIN}
              max={WEIGHT_MAX}
              step={WEIGHT_STEP}
              valueLabelDisplay="auto"
              valueLabelFormat={formatPercent}
              aria-labelledby={`label-${criterion.key}`}
              aria-valuetext={formatPercent(weights[criterion.key])}
              disabled={saving}
            />
          </Box>
        ))}

        <Divider sx={{ my: 2 }} />

        {/* Weight sum indicator */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            Total
          </Typography>
          <Typography
            variant="body1"
            sx={{
              fontWeight: 700,
              color: isSumValid ? 'success.main' : 'error.main',
            }}
            role="status"
            aria-live="polite"
          >
            {formatPercent(weightSum)}
          </Typography>
        </Box>

        {!isSumValid && (
          <Alert severity="warning" sx={{ mb: 2 }} role="alert">
            Weights must sum to 100%. Current total is {formatPercent(weightSum)}.
          </Alert>
        )}

        {/* Actions */}
        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          <Button
            variant="text"
            startIcon={<RefreshIcon />}
            onClick={handleReset}
            disabled={!isDirty || saving}
            aria-label="Reset weights to last saved values"
          >
            Reset
          </Button>
          <Button
            variant="contained"
            startIcon={saving ? <CircularProgress size={18} color="inherit" /> : <SaveIcon />}
            onClick={handleSave}
            disabled={!isSumValid || !isDirty || saving}
            aria-label="Save scoring weights and rescore all leads"
          >
            {saving ? 'Saving…' : 'Save & Rescore'}
          </Button>
        </Box>
      </Paper>
    </Box>
  )
}
