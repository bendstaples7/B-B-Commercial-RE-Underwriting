/**
 * Shared Next-step panel for LogActivityForm (call / note / email).
 * Sole owner of complete-task + create-follow-up + horizon controls.
 */
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import type { LeadTask } from '@/types'
import { FollowUpHorizonControls } from '@/components/FollowUpHorizonControls'
import {
  type FollowUpPreset,
  formatFollowUpPresetLabel,
} from '@/utils/followUpPresets'
import {
  CREATE_TASK_PRESETS,
  type CreateTaskPresetId,
} from '@/utils/createTaskPresets'

export type NextStepTaskType = CreateTaskPresetId

export interface ActivityNextStepPanelProps {
  completableTask: LeadTask | null
  /** When true and no completableTask, show the call-mode hint about non-call tasks. */
  showNoCallTaskHint?: boolean
  hasOpenNonCompletableTasks?: boolean
  completeTask: boolean
  onCompleteTaskChange: (checked: boolean) => void
  createFollowUp: boolean
  onCreateFollowUpChange: (checked: boolean) => void
  followUpPreset: FollowUpPreset
  customDueDate: string
  followUpError: string | null
  followUpDuePreview: string | null
  onFollowUpPresetChange: (value: FollowUpPreset) => void
  onCustomDueDateChange: (value: string) => void
  nextStepExpanded: boolean
  onToggleNextStepExpanded: () => void
  nextStepType: NextStepTaskType
  onNextStepTypeChange: (value: NextStepTaskType) => void
  customTaskTitle: string
  onCustomTaskTitleChange: (value: string) => void
}

export function ActivityNextStepPanel({
  completableTask,
  showNoCallTaskHint = false,
  hasOpenNonCompletableTasks = false,
  completeTask,
  onCompleteTaskChange,
  createFollowUp,
  onCreateFollowUpChange,
  followUpPreset,
  customDueDate,
  followUpError,
  followUpDuePreview,
  onFollowUpPresetChange,
  onCustomDueDateChange,
  nextStepExpanded,
  onToggleNextStepExpanded,
  nextStepType,
  onNextStepTypeChange,
  customTaskTitle,
  onCustomTaskTitleChange,
}: ActivityNextStepPanelProps) {
  return (
    <Box
      data-testid="activity-next-step-actions"
      sx={{
        height: '100%',
        px: 1.5,
        py: 1.25,
        borderRadius: 1,
        bgcolor: 'action.hover',
        border: 1,
        borderColor: 'divider',
      }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600, letterSpacing: 0.01 }}>
        Next step
      </Typography>

      {completableTask ? (
        <FormControlLabel
          sx={{ alignItems: 'flex-start', m: 0, mb: 1, display: 'flex' }}
          control={
            <Checkbox
              checked={completeTask}
              onChange={(e) => onCompleteTaskChange(e.target.checked)}
              data-testid="complete-activity-task-checkbox"
              sx={{ pt: 0.25 }}
            />
          }
          label={
            <Box data-testid="complete-activity-task-section">
              <Typography variant="body2">
                Complete task:{' '}
                <Typography component="span" variant="body2" fontWeight={600}>
                  {completableTask.title}
                </Typography>
              </Typography>
              {completableTask.source === 'hubspot' && (
                <Typography variant="caption" color="text.secondary" display="block">
                  Marks done in HubSpot when possible.
                </Typography>
              )}
            </Box>
          }
        />
      ) : showNoCallTaskHint && hasOpenNonCompletableTasks ? (
        <Alert severity="info" sx={{ mb: 1, py: 0.5 }} data-testid="no-call-task-hint">
          No open call or follow-up task to complete. Mail or email outreach tasks are not
          completed from a call log.
        </Alert>
      ) : null}

      <FormControlLabel
        sx={{ alignItems: 'flex-start', m: 0, mb: createFollowUp ? 0.75 : 0, display: 'flex' }}
        control={
          <Checkbox
            checked={createFollowUp}
            onChange={(e) => onCreateFollowUpChange(e.target.checked)}
            data-testid="create-follow-up-checkbox"
            sx={{ pt: 0.25 }}
          />
        }
        label={
          <Typography variant="body2" data-testid="activity-follow-up-section">
            Create a follow-up task
            {followUpDuePreview && (
              <>
                {' — '}
                <Typography component="span" variant="body2" color="primary.main">
                  {formatFollowUpPresetLabel(
                    followUpPreset as Exclude<FollowUpPreset, 'custom'>,
                    followUpDuePreview,
                  )}
                </Typography>
              </>
            )}
          </Typography>
        }
      />

      {createFollowUp && (
        <Box sx={{ width: '100%', minWidth: 0 }}>
          <Button
            size="small"
            variant="text"
            onClick={onToggleNextStepExpanded}
            data-testid="change-next-step-btn"
            sx={{ px: 0, mb: 0.5 }}
          >
            Change next step
          </Button>
          {nextStepExpanded && (
            <>
              <FormControl fullWidth size="small" sx={{ mb: 1 }}>
                <InputLabel id="next-step-type-label">Task type</InputLabel>
                <Select
                  labelId="next-step-type-label"
                  label="Task type"
                  value={nextStepType}
                  onChange={(e) => onNextStepTypeChange(e.target.value as NextStepTaskType)}
                  inputProps={{ 'data-testid': 'next-step-type-select' }}
                >
                  {CREATE_TASK_PRESETS.map((opt) => (
                    <MenuItem key={opt.id} value={opt.id}>
                      {opt.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {nextStepType === 'custom' && (
                <TextField
                  label="Task title"
                  size="small"
                  fullWidth
                  value={customTaskTitle}
                  onChange={(e) => onCustomTaskTitleChange(e.target.value)}
                  inputProps={{ 'data-testid': 'next-step-custom-title', maxLength: 255 }}
                  sx={{ mb: 1 }}
                />
              )}
            </>
          )}
          <FollowUpHorizonControls
            variant="list"
            preset={followUpPreset}
            customDueDate={customDueDate}
            error={followUpError}
            onPresetChange={onFollowUpPresetChange}
            onCustomDueDateChange={onCustomDueDateChange}
          />
        </Box>
      )}
    </Box>
  )
}

export default ActivityNextStepPanel
