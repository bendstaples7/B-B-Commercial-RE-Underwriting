/**
 * Shared follow-up interval controls (Log Call + last-task complete prompt).
 */
import {
  Box,
  Button,
  FormControlLabel,
  FormHelperText,
  Radio,
  RadioGroup,
  TextField,
  Typography,
} from '@mui/material'
import {
  type FollowUpPreset,
  followUpDueForPreset,
  formatFollowUpDueLong,
} from '@/utils/followUpPresets'

const PRESET_OPTIONS: Array<{ value: FollowUpPreset; label: string; shortLabel?: string }> = [
  { value: '1', label: 'Tomorrow', shortLabel: 'Tomorrow' },
  { value: '3', label: '3 days', shortLabel: '3 days' },
  { value: '7', label: '1 week', shortLabel: '1 wk' },
  { value: '14', label: '2 weeks', shortLabel: '2 wk' },
  { value: '1mo', label: '1 month', shortLabel: '1 mo' },
  { value: '3mo', label: '3 months', shortLabel: '3 mo' },
  { value: '6mo', label: '6 months', shortLabel: '6 mo' },
  { value: '1y', label: '1 year', shortLabel: '1 yr' },
  { value: 'custom', label: 'Custom', shortLabel: 'Custom' },
]

const NEAR_TERM = PRESET_OPTIONS.slice(0, 4)
const LONGER_TERM = PRESET_OPTIONS.slice(4)

export type FollowUpHorizonVariant = 'buttons' | 'list'

export interface FollowUpHorizonControlsProps {
  preset: FollowUpPreset
  customDueDate: string
  error?: string | null
  onPresetChange: (preset: FollowUpPreset) => void
  onCustomDueDateChange: (value: string) => void
  testIdPrefix?: string
  /** Tighter grid for button variant — single block, no section headers. */
  compact?: boolean
  /** `list` = vertical radios with due dates (Log Call split panel). */
  variant?: FollowUpHorizonVariant
}

function presetTestSuffix(value: FollowUpPreset): string {
  if (value === 'custom') return 'custom'
  if (value.endsWith('mo') || value === '1y') return value
  return `${value}d`
}


function PresetButton({
  opt,
  selected,
  onPresetChange,
  testIdPrefix,
  compact,
}: {
  opt: (typeof PRESET_OPTIONS)[number]
  selected: boolean
  onPresetChange: (preset: FollowUpPreset) => void
  testIdPrefix: string
  compact?: boolean
}) {
  return (
    <Button
      type="button"
      size="small"
      variant={selected ? 'contained' : 'outlined'}
      color={selected ? 'primary' : 'inherit'}
      onClick={() => onPresetChange(opt.value)}
      data-testid={`${testIdPrefix}-${presetTestSuffix(opt.value)}`}
      aria-pressed={selected}
      sx={{
        textTransform: 'none',
        fontWeight: selected ? 600 : 500,
        fontSize: compact ? '0.75rem' : '0.8125rem',
        lineHeight: 1.2,
        px: compact ? 0.75 : 1.25,
        py: compact ? 0.35 : 0.5,
        minWidth: 0,
        borderRadius: 1,
        borderColor: selected ? 'primary.main' : 'divider',
        color: selected ? undefined : 'text.primary',
        bgcolor: selected ? undefined : 'background.paper',
        '&:hover': {
          borderColor: selected ? 'primary.dark' : 'text.secondary',
          bgcolor: selected ? undefined : 'action.hover',
        },
      }}
    >
      {compact ? (opt.shortLabel ?? opt.label) : opt.label}
    </Button>
  )
}

function PresetRow({
  options,
  preset,
  onPresetChange,
  testIdPrefix,
  compact,
}: {
  options: Array<(typeof PRESET_OPTIONS)[number]>
  preset: FollowUpPreset
  onPresetChange: (preset: FollowUpPreset) => void
  testIdPrefix: string
  compact?: boolean
}) {
  return (
    <Box
      role="group"
      aria-label="Follow-up interval"
      sx={
        compact
          ? {
              display: 'grid',
              gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
              gap: 0.5,
              width: '100%',
            }
          : {
              display: 'flex',
              flexWrap: 'wrap',
              gap: 0.75,
              width: '100%',
              maxWidth: '100%',
            }
      }
    >
      {options.map((opt) => (
        <PresetButton
          key={opt.value}
          opt={opt}
          selected={preset === opt.value}
          onPresetChange={onPresetChange}
          testIdPrefix={testIdPrefix}
          compact={compact}
        />
      ))}
    </Box>
  )
}

function CustomDateField({
  testIdPrefix,
  customDueDate,
  error,
  onCustomDueDateChange,
}: {
  testIdPrefix: string
  customDueDate: string
  error?: string | null
  onCustomDueDateChange: (value: string) => void
}) {
  return (
    <TextField
      type="date"
      size="small"
      label="Follow-up date"
      value={customDueDate}
      onChange={(e) => onCustomDueDateChange(e.target.value)}
      error={!!error}
      helperText={error ?? undefined}
      InputLabelProps={{ shrink: true }}
      fullWidth
      sx={{ mt: 0.75 }}
      inputProps={{ 'data-testid': `${testIdPrefix}-custom-date` }}
    />
  )
}

function ListVariant({
  preset,
  customDueDate,
  error,
  onPresetChange,
  onCustomDueDateChange,
  testIdPrefix,
}: {
  preset: FollowUpPreset
  customDueDate: string
  error?: string | null
  onPresetChange: (preset: FollowUpPreset) => void
  onCustomDueDateChange: (value: string) => void
  testIdPrefix: string
}) {
  return (
    <Box sx={{ width: '100%', minWidth: 0 }}>
      <RadioGroup
        value={preset}
        onChange={(_, value) => onPresetChange(value as FollowUpPreset)}
        aria-label="Follow-up interval"
        sx={{ gap: 0 }}
      >
        {PRESET_OPTIONS.map((opt) => {
          const duePreview =
            opt.value !== 'custom' ? formatFollowUpDueLong(followUpDueForPreset(opt.value)) : null
          return (
            <FormControlLabel
              key={opt.value}
              value={opt.value}
              control={
                <Radio
                  size="small"
                  sx={{ py: 0.25 }}
                  inputProps={
                    { 'data-testid': `${testIdPrefix}-${presetTestSuffix(opt.value)}` } as React.InputHTMLAttributes<HTMLInputElement>
                  }
                />
              }
              sx={{
                m: 0,
                mx: 0,
                px: 0.5,
                py: 0.15,
                borderRadius: 1,
                width: '100%',
                alignItems: 'center',
                bgcolor: preset === opt.value ? 'action.selected' : 'transparent',
                '&:hover': { bgcolor: 'action.hover' },
                '& .MuiFormControlLabel-label': { width: '100%', minWidth: 0 },
              }}
              label={
                <Box
                  sx={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 1,
                    width: '100%',
                    minWidth: 0,
                  }}
                >
                  <Typography
                    variant="body2"
                    fontWeight={preset === opt.value ? 600 : 400}
                    sx={{ lineHeight: 1.3 }}
                  >
                    {opt.label}
                  </Typography>
                  {duePreview && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}
                    >
                      {duePreview}
                    </Typography>
                  )}
                </Box>
              }
            />
          )
        })}
      </RadioGroup>
      {preset === 'custom' && (
        <CustomDateField
          testIdPrefix={testIdPrefix}
          customDueDate={customDueDate}
          error={error}
          onCustomDueDateChange={onCustomDueDateChange}
        />
      )}
      {error && preset !== 'custom' && (
        <FormHelperText error sx={{ mx: 0, mt: 0.25 }}>
          {error}
        </FormHelperText>
      )}
    </Box>
  )
}

export function FollowUpHorizonControls({
  preset,
  customDueDate,
  error = null,
  onPresetChange,
  onCustomDueDateChange,
  testIdPrefix = 'follow-up',
  compact = false,
  variant = 'buttons',
}: FollowUpHorizonControlsProps) {
  if (variant === 'list') {
    return (
      <ListVariant
        preset={preset}
        customDueDate={customDueDate}
        error={error}
        onPresetChange={onPresetChange}
        onCustomDueDateChange={onCustomDueDateChange}
        testIdPrefix={testIdPrefix}
      />
    )
  }

  if (compact) {
    return (
      <Box sx={{ width: '100%', minWidth: 0 }}>
        <PresetRow
          options={PRESET_OPTIONS}
          preset={preset}
          onPresetChange={onPresetChange}
          testIdPrefix={testIdPrefix}
          compact
        />
        {preset === 'custom' && (
          <CustomDateField
            testIdPrefix={testIdPrefix}
            customDueDate={customDueDate}
            error={error}
            onCustomDueDateChange={onCustomDueDateChange}
          />
        )}
        {error && preset !== 'custom' && (
          <FormHelperText error sx={{ mx: 0, mt: 0.25 }}>
            {error}
          </FormHelperText>
        )}
      </Box>
    )
  }

  return (
    <Box sx={{ width: '100%', maxWidth: '100%', minWidth: 0 }}>
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: 'block', mb: 0.75 }}
      >
        Near term
      </Typography>
      <PresetRow
        options={NEAR_TERM}
        preset={preset}
        onPresetChange={onPresetChange}
        testIdPrefix={testIdPrefix}
      />
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: 'block', mt: 1.25, mb: 0.75 }}
      >
        Later
      </Typography>
      <PresetRow
        options={LONGER_TERM}
        preset={preset}
        onPresetChange={onPresetChange}
        testIdPrefix={testIdPrefix}
      />
      {preset === 'custom' && (
        <CustomDateField
          testIdPrefix={testIdPrefix}
          customDueDate={customDueDate}
          error={error}
          onCustomDueDateChange={onCustomDueDateChange}
        />
      )}
      {error && preset !== 'custom' && (
        <FormHelperText error sx={{ mx: 0, mt: 0.5 }}>
          {error}
        </FormHelperText>
      )}
    </Box>
  )
}
