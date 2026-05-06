/**
 * ScoreFilterPanel — controlled filter controls for the lead list.
 *
 * Renders on the Lead List page to let the user narrow the visible leads by
 * score-related attributes. This is a "dumb" controlled component: the parent
 * owns the filter state and passes the current `filters` value and an
 * `onChange` callback. Every interaction emits a fully-updated
 * {@link ScoreFilters} object through `onChange`.
 *
 * Supported filters:
 *   • score_tier — multi-select (A / B / C / D) via checkboxes
 *   • recommended_action — multi-select via Autocomplete
 *   • data_quality_score < 70 — boolean toggle
 *   • missing PIN — boolean toggle
 *   • missing owner mailing address — boolean toggle
 *   • condo_risk_status = needs_review — boolean toggle
 *   • condo_risk_status = likely_condo — boolean toggle
 *
 * Satisfies Requirements 13.1 through 13.7.
 */
import {
  Autocomplete,
  Box,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Divider,
  FormControlLabel,
  FormGroup,
  FormLabel,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import type { LeadScoreRecord, RecommendedAction } from '@/types'

export type ScoreTier = LeadScoreRecord['score_tier']

/**
 * All filter values the panel can emit. Parents pass the current value in
 * and receive a fully-updated object via {@link ScoreFilterPanelProps.onChange}.
 */
export interface ScoreFilters {
  /** Selected score tiers. Empty array means "no tier filter applied". */
  tiers: ScoreTier[]
  /** Selected recommended actions. Empty array means "no action filter". */
  actions: RecommendedAction[]
  /** When true, show only leads with data_quality_score < 70. */
  lowDataQuality: boolean
  /** When true, show only leads missing their county_assessor_pin. */
  missingPin: boolean
  /** When true, show only leads missing their owner mailing address. */
  missingOwnerMailing: boolean
  /** When true, show only commercial leads with condo_risk_status = needs_review. */
  condoNeedsReview: boolean
  /** When true, show only commercial leads with condo_risk_status = likely_condo. */
  condoLikelyCondo: boolean
}

/**
 * The "everything off" filter state. Exported so parents can initialize or
 * reset their own state without duplicating the shape.
 */
export const EMPTY_SCORE_FILTERS: ScoreFilters = {
  tiers: [],
  actions: [],
  lowDataQuality: false,
  missingPin: false,
  missingOwnerMailing: false,
  condoNeedsReview: false,
  condoLikelyCondo: false,
}

export interface ScoreFilterPanelProps {
  /** Current filter values. The panel is fully controlled by this prop. */
  filters: ScoreFilters
  /** Called with the fully-updated filters whenever any control changes. */
  onChange: (filters: ScoreFilters) => void
  /** Optional className passthrough. */
  className?: string
}

/** Canonical list of score tiers for the checkbox group. */
const ALL_TIERS: ScoreTier[] = ['A', 'B', 'C', 'D']

/** Canonical list of recommended actions for the multi-select. */
const ALL_ACTIONS: RecommendedAction[] = [
  'review_now',
  'enrich_data',
  'mail_ready',
  'call_ready',
  'valuation_needed',
  'suppress',
  'nurture',
  'needs_manual_review',
]

/** Human-readable labels for recommended actions. */
const ACTION_LABELS: Record<RecommendedAction, string> = {
  review_now: 'Review Now',
  enrich_data: 'Enrich Data',
  mail_ready: 'Mail Ready',
  call_ready: 'Call Ready',
  valuation_needed: 'Valuation Needed',
  suppress: 'Suppress',
  nurture: 'Nurture',
  needs_manual_review: 'Needs Manual Review',
}

export function ScoreFilterPanel({
  filters,
  onChange,
  className,
}: ScoreFilterPanelProps) {
  /** Emit a new ScoreFilters object with the given patch applied. */
  const update = (patch: Partial<ScoreFilters>) => {
    onChange({ ...filters, ...patch })
  }

  const toggleTier = (tier: ScoreTier, checked: boolean) => {
    const next = checked
      ? Array.from(new Set([...filters.tiers, tier]))
      : filters.tiers.filter((t) => t !== tier)
    update({ tiers: next })
  }

  return (
    <Card
      variant="outlined"
      className={className}
      data-testid="score-filter-panel"
    >
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Score Filters
        </Typography>

        {/* Score tier — multi-select via checkboxes */}
        <Box sx={{ mb: 2 }}>
          <FormLabel component="legend" sx={{ mb: 0.5, display: 'block' }}>
            Score Tier
          </FormLabel>
          <FormGroup row data-testid="score-filter-tiers">
            {ALL_TIERS.map((tier) => (
              <FormControlLabel
                key={tier}
                control={
                  <Checkbox
                    size="small"
                    checked={filters.tiers.includes(tier)}
                    onChange={(e) => toggleTier(tier, e.target.checked)}
                    inputProps={{
                      'aria-label': `Score tier ${tier}`,
                    }}
                    data-testid={`score-filter-tier-${tier}`}
                  />
                }
                label={tier}
              />
            ))}
          </FormGroup>
        </Box>

        {/* Recommended action — multi-select via Autocomplete */}
        <Box sx={{ mb: 2 }}>
          <Autocomplete<RecommendedAction, true>
            multiple
            size="small"
            options={ALL_ACTIONS}
            value={filters.actions}
            onChange={(_, value) => update({ actions: value })}
            getOptionLabel={(option) => ACTION_LABELS[option] ?? option}
            isOptionEqualToValue={(option, value) => option === value}
            renderTags={(value, getTagProps) =>
              value.map((option, index) => {
                const { key, ...tagProps } = getTagProps({ index })
                return (
                  <Chip
                    key={key}
                    label={ACTION_LABELS[option] ?? option}
                    size="small"
                    {...tagProps}
                  />
                )
              })
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label="Recommended Action"
                placeholder={
                  filters.actions.length === 0 ? 'Any action' : undefined
                }
              />
            )}
            data-testid="score-filter-actions"
          />
        </Box>

        <Divider sx={{ my: 2 }} />

        {/* Boolean toggles for data-quality and condo-risk conditions. */}
        <Stack spacing={0.5} data-testid="score-filter-toggles">
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={filters.lowDataQuality}
                onChange={(e) => update({ lowDataQuality: e.target.checked })}
                inputProps={{
                  'aria-label': 'Filter to low data quality',
                }}
                data-testid="score-filter-low-data-quality"
              />
            }
            label="Data quality < 70"
          />
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={filters.missingPin}
                onChange={(e) => update({ missingPin: e.target.checked })}
                inputProps={{ 'aria-label': 'Filter to missing PIN' }}
                data-testid="score-filter-missing-pin"
              />
            }
            label="Missing PIN"
          />
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={filters.missingOwnerMailing}
                onChange={(e) =>
                  update({ missingOwnerMailing: e.target.checked })
                }
                inputProps={{
                  'aria-label': 'Filter to missing owner mailing address',
                }}
                data-testid="score-filter-missing-owner-mailing"
              />
            }
            label="Missing owner mailing address"
          />
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={filters.condoNeedsReview}
                onChange={(e) =>
                  update({ condoNeedsReview: e.target.checked })
                }
                inputProps={{
                  'aria-label': 'Filter to condo status needs review',
                }}
                data-testid="score-filter-condo-needs-review"
              />
            }
            label="Condo status: needs review"
          />
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={filters.condoLikelyCondo}
                onChange={(e) =>
                  update({ condoLikelyCondo: e.target.checked })
                }
                inputProps={{
                  'aria-label': 'Filter to condo status likely condo',
                }}
                data-testid="score-filter-condo-likely-condo"
              />
            }
            label="Condo status: likely condo"
          />
        </Stack>
      </CardContent>
    </Card>
  )
}

export default ScoreFilterPanel
