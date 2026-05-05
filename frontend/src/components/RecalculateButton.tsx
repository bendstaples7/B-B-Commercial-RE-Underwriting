/**
 * RecalculateButton — triggers a lead-score recalculation via the backend.
 *
 * Supports three modes via a discriminated union on `mode`:
 *   • 'single'      — recalculate a single lead by leadId (used on the detail page)
 *   • 'bulk-all'    — recalculate every active lead (used on the list page)
 *   • 'bulk-source' — recalculate every lead matching a source_type
 *
 * While the mutation is pending the button is disabled and shows a
 * CircularProgress spinner. On success, relevant React Query caches are
 * invalidated so the UI refreshes with the new scores. On error, an MUI
 * Alert is rendered below the button.
 *
 * Satisfies Requirements 11.5, 12.1, 12.2, 12.3.
 */
import { Alert, Box, Button, CircularProgress } from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { leadScoreService } from '@/services/api'
import type { RecalculateRequest, RecalculateResponse } from '@/types'

export type RecalculateButtonProps =
  | {
      mode: 'single'
      leadId: number
      label?: string
      onSuccess?: (response: RecalculateResponse) => void
    }
  | {
      mode: 'bulk-all'
      label?: string
      onSuccess?: (response: RecalculateResponse) => void
    }
  | {
      mode: 'bulk-source'
      sourceType: string
      label?: string
      onSuccess?: (response: RecalculateResponse) => void
    }

/**
 * Default button label based on mode. Can be overridden via the `label` prop.
 */
function defaultLabel(props: RecalculateButtonProps): string {
  if (props.label) return props.label
  switch (props.mode) {
    case 'single':
      return 'Recalculate Score'
    case 'bulk-all':
      return 'Recalculate All Scores'
    case 'bulk-source':
      return `Recalculate ${props.sourceType} Scores`
  }
}

/**
 * Build the backend request payload from the component props.
 */
function buildRequest(props: RecalculateButtonProps): RecalculateRequest {
  switch (props.mode) {
    case 'single':
      return { lead_id: props.leadId }
    case 'bulk-all':
      return { all: true }
    case 'bulk-source':
      return { source_type: props.sourceType }
  }
}

export function RecalculateButton(props: RecalculateButtonProps) {
  const queryClient = useQueryClient()

  const mutation = useMutation<RecalculateResponse, Error, void>({
    mutationFn: async () => {
      const response = await leadScoreService.recalculate(buildRequest(props))
      return response.data
    },
    onSuccess: (data) => {
      // Invalidate the lead list in every mode — score columns depend on it.
      queryClient.invalidateQueries({ queryKey: ['leads'] })

      if (props.mode === 'single') {
        // Refresh this specific lead's score detail and its history.
        queryClient.invalidateQueries({ queryKey: ['leadScore', props.leadId] })
      } else {
        // Bulk modes touch many leads — invalidate all leadScore queries.
        queryClient.invalidateQueries({ queryKey: ['leadScore'] })
      }

      props.onSuccess?.(data)
    },
  })

  const isPending = mutation.isPending
  const label = defaultLabel(props)

  return (
    <Box>
      <Button
        variant="contained"
        color="primary"
        onClick={() => mutation.mutate()}
        disabled={isPending}
        startIcon={
          isPending ? (
            <CircularProgress size={16} color="inherit" />
          ) : (
            <RefreshIcon />
          )
        }
        data-testid="recalculate-button"
      >
        {isPending ? 'Recalculating...' : label}
      </Button>

      {mutation.isError && (
        <Alert severity="error" sx={{ mt: 1 }} data-testid="recalculate-error">
          {mutation.error?.message ?? 'Failed to recalculate score.'}
        </Alert>
      )}
    </Box>
  )
}

export default RecalculateButton
