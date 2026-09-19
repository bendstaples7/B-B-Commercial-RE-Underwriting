/**
 * Shared source + why fields for Quick Add and Add Contact.
 * Notes stay on each form so existing note labels and payloads are unchanged.
 */
import {
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  TextField,
} from '@mui/material'
import { QUICK_ADD_DEAL_SOURCES } from '@/types'

export interface CaptureSourceFieldsProps {
  source: string
  onSourceChange: (value: string) => void
  context: string
  onContextChange: (value: string) => void
  /** When true, include a blank "not specified" option (contacts). */
  allowEmptySource?: boolean
  contextPlaceholder?: string
  sourceLabelId?: string
  /** Margin under each field. Contact dialog uses parent gap instead. */
  fieldMb?: number
}

export function CaptureSourceFields({
  source,
  onSourceChange,
  context,
  onContextChange,
  allowEmptySource = false,
  contextPlaceholder = 'Why this is worth capturing…',
  sourceLabelId = 'capture-source-label',
  fieldMb = 2,
}: CaptureSourceFieldsProps) {
  return (
    <>
      <FormControl fullWidth sx={{ mb: fieldMb }}>
        <InputLabel id={sourceLabelId}>Source</InputLabel>
        <Select
          labelId={sourceLabelId}
          label="Source"
          value={source}
          onChange={(event) => onSourceChange(event.target.value)}
          inputProps={{ 'aria-label': 'Source' }}
        >
          {allowEmptySource && (
            <MenuItem value="">
              <em>Not specified</em>
            </MenuItem>
          )}
          {QUICK_ADD_DEAL_SOURCES.map((option) => (
            <MenuItem key={option} value={option}>
              {option}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <TextField
        label="Why are you adding this?"
        value={context}
        onChange={(event) => onContextChange(event.target.value)}
        fullWidth
        multiline
        minRows={2}
        placeholder={contextPlaceholder}
        helperText="Context for why you are capturing this"
        sx={{ mb: fieldMb, caretColor: 'text.primary' }}
        inputProps={{ 'aria-label': 'Why are you adding this' }}
      />
    </>
  )
}
