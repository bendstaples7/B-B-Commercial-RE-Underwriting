/**
 * Shared source + why fields for Quick Add and Add Contact.
 * Notes stay on each form so existing note labels and payloads are unchanged.
 *
 * Source list = HubSpot-aligned builtins + user-created options (e.g. Facebook Ad)
 * via GET/POST /api/deal-sources. "+ Add new…" matches Log Activity sent-from UX.
 */
import { useMemo, useState } from 'react'
import {
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
} from '@mui/material'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import dealSourcesApi from '@/services/dealSourcesApi'
import { QUICK_ADD_DEAL_SOURCES } from '@/types'

const ADD_NEW_SOURCE = '__add_new_source__'
const DEAL_SOURCES_QUERY_KEY = ['deal-sources'] as const

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
  const queryClient = useQueryClient()
  const { data: remoteSources } = useQuery({
    queryKey: DEAL_SOURCES_QUERY_KEY,
    queryFn: () => dealSourcesApi.list(),
    staleTime: 60_000,
  })

  const [addingSource, setAddingSource] = useState(false)
  const [newSourceInput, setNewSourceInput] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  const options = useMemo(() => {
    const names = remoteSources?.map((row) => row.name) ?? [...QUICK_ADD_DEAL_SOURCES]
    const seen = new Set(names.map((n) => n.toLowerCase()))
    // Keep the current selection visible even before the catalog refreshes.
    if (source && !seen.has(source.toLowerCase())) {
      names.push(source)
    }
    return names
  }, [remoteSources, source])

  const createMutation = useMutation({
    mutationFn: (name: string) => dealSourcesApi.create(name),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: DEAL_SOURCES_QUERY_KEY })
      onSourceChange(result.name)
      setAddingSource(false)
      setNewSourceInput('')
      setAddError(null)
    },
    onError: (err: unknown) => {
      const message =
        err && typeof err === 'object' && 'response' in err
          ? String(
              (err as { response?: { data?: { message?: string; error?: string } } }).response?.data
                ?.message
                || (err as { response?: { data?: { error?: string } } }).response?.data?.error
                || 'Could not add source',
            )
          : 'Could not add source'
      setAddError(message)
    },
  })

  const handleAddSource = () => {
    const trimmed = newSourceInput.trim()
    if (!trimmed) {
      setAddError('Enter a source name')
      return
    }
    setAddError(null)
    createMutation.mutate(trimmed)
  }

  return (
    <>
      <FormControl fullWidth sx={{ mb: addingSource ? 1 : fieldMb }}>
        <InputLabel id={sourceLabelId}>Source</InputLabel>
        <Select
          labelId={sourceLabelId}
          label="Source"
          value={addingSource ? ADD_NEW_SOURCE : source}
          onChange={(event) => {
            const value = event.target.value
            if (value === ADD_NEW_SOURCE) {
              setAddingSource(true)
              setAddError(null)
              return
            }
            setAddingSource(false)
            setNewSourceInput('')
            setAddError(null)
            onSourceChange(value)
          }}
          inputProps={{ 'aria-label': 'Source' }}
          data-testid="capture-source-select"
          renderValue={(selected) => {
            if (selected === ADD_NEW_SOURCE) return '+ Add new…'
            if (!selected) return 'Not specified'
            return selected as string
          }}
        >
          {allowEmptySource && (
            <MenuItem value="">
              <em>Not specified</em>
            </MenuItem>
          )}
          {options.map((option) => (
            <MenuItem key={option} value={option} data-testid={`capture-source-option-${option}`}>
              {option}
            </MenuItem>
          ))}
          <MenuItem value={ADD_NEW_SOURCE} data-testid="capture-source-add-new">
            + Add new…
          </MenuItem>
        </Select>
      </FormControl>

      {addingSource && (
        <Box sx={{ mb: fieldMb }}>
          <Stack direction="row" spacing={1} alignItems="flex-start">
            <TextField
              size="small"
              fullWidth
              label="New source"
              value={newSourceInput}
              onChange={(event) => {
                setNewSourceInput(event.target.value)
                if (addError) setAddError(null)
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  handleAddSource()
                }
              }}
              error={Boolean(addError)}
              helperText={addError || 'e.g. Facebook Ad'}
              inputProps={{ 'aria-label': 'New source', 'data-testid': 'capture-source-new-input' }}
              sx={{ caretColor: 'text.primary' }}
            />
            <Button
              size="small"
              variant="contained"
              onClick={handleAddSource}
              disabled={createMutation.isPending}
              data-testid="capture-source-save-new"
              sx={{ mt: 0.5, flexShrink: 0 }}
            >
              Add
            </Button>
            <Button
              size="small"
              onClick={() => {
                setAddingSource(false)
                setNewSourceInput('')
                setAddError(null)
              }}
              disabled={createMutation.isPending}
              data-testid="capture-source-cancel-new"
              sx={{ mt: 0.5, flexShrink: 0 }}
            >
              Cancel
            </Button>
          </Stack>
        </Box>
      )}

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
