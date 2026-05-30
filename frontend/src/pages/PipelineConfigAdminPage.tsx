/**
 * PipelineConfigAdminPage — admin interface for viewing and editing pipeline stage weights.
 *
 * Displays all configured stages with editable weight fields.
 * Sends batch updates via PUT /api/pipeline-stages/weights.
 */
import React, { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Box,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Button,
  CircularProgress,
  Alert,
  IconButton,
  Tooltip,
} from '@mui/material'
import SaveIcon from '@mui/icons-material/Save'
import RefreshIcon from '@mui/icons-material/Refresh'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { useNavigate } from 'react-router-dom'
import { pipelineConfigService } from '@/services/api'
import type { PipelineStage } from '@/types'

export function PipelineConfigAdminPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [edits, setEdits] = useState<Record<number, number>>({})
  const [saved, setSaved] = useState(false)

  const {
    data: stages,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['pipeline-stages'],
    queryFn: () => pipelineConfigService.getStages(),
    staleTime: 0,
  })

  // Initialize edits from fetched data
  useEffect(() => {
    if (stages) {
      const initial: Record<number, number> = {}
      for (const s of stages) {
        initial[s.id] = s.weight
      }
      setEdits(initial)
    }
  }, [stages])

  const saveMutation = useMutation({
    mutationFn: (payload: { stage_name: string; weight: number }[]) =>
      pipelineConfigService.updateWeights(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline-stages'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    },
  })

  const handleWeightChange = (stageId: number, value: string) => {
    const num = parseFloat(value)
    if (!isNaN(num) && num >= 0) {
      setEdits((prev) => ({ ...prev, [stageId]: num }))
    }
  }

  const handleSave = () => {
    if (!stages) return
    const payload = stages.map((s) => ({
      stage_name: s.stage_name,
      weight: edits[s.id] ?? s.weight,
    }))
    saveMutation.mutate(payload)
  }

  const hasChanges = stages
    ? stages.some((s) => edits[s.id] !== s.weight)
    : false

  return (
    <Box>
      {/* Header */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          mb: 3,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Tooltip title="Back to Kanban">
            <IconButton onClick={() => navigate('/kanban')} size="small">
              <ArrowBackIcon />
            </IconButton>
          </Tooltip>
          <Typography variant="h5" component="h1" fontWeight={600}>
            Pipeline Stage Configuration
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Tooltip title="Refresh">
            <IconButton onClick={() => refetch()} size="small">
              <RefreshIcon />
            </IconButton>
          </Tooltip>
          <Button
            variant="contained"
            startIcon={
              saveMutation.isPending ? (
                <CircularProgress size={16} color="inherit" />
              ) : (
                <SaveIcon />
              )
            }
            onClick={handleSave}
            disabled={!hasChanges || saveMutation.isPending}
          >
            {saveMutation.isPending ? 'Saving…' : 'Save Weights'}
          </Button>
        </Box>
      </Box>

      {saved && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Stage weights saved successfully. Priority scores will be recalculated
          on next status change or via the recompute command.
        </Alert>
      )}

      {isError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {(error as Error)?.message ?? 'Failed to load pipeline stages'}
        </Alert>
      )}

      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress aria-label="Loading pipeline stages" />
        </Box>
      )}

      {stages && stages.length === 0 && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            No pipeline stages configured. Run{' '}
            <code>flask seed-pipeline-stages</code> to create default stages.
          </Typography>
        </Paper>
      )}

      {stages && stages.length > 0 && (
        <TableContainer component={Paper} variant="outlined">
          <Table aria-label="Pipeline stage configuration">
            <TableHead>
              <TableRow>
                <TableCell>Order</TableCell>
                <TableCell>Stage Name</TableCell>
                <TableCell align="right">Weight (Score)</TableCell>
                <TableCell>Description</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {stages
                .sort((a, b) => a.order - b.order)
                .map((stage) => (
                  <TableRow key={stage.id}>
                    <TableCell>{stage.order}</TableCell>
                    <TableCell>
                      <Typography fontWeight={600}>{stage.stage_name}</Typography>
                    </TableCell>
                    <TableCell align="right">
                      <TextField
                        type="number"
                        size="small"
                        value={edits[stage.id] ?? stage.weight}
                        onChange={(e) =>
                          handleWeightChange(stage.id, e.target.value)
                        }
                        inputProps={{
                          min: 0,
                          max: 100,
                          step: 0.5,
                          style: { textAlign: 'right', width: 80 },
                        }}
                        sx={{ width: 100 }}
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        Determines priority score when a deal is in this stage
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Info box */}
      <Paper variant="outlined" sx={{ mt: 3, p: 2 }}>
        <Typography variant="subtitle2" gutterBottom>
          How Priority Scoring Works
        </Typography>
        <Typography variant="body2" color="text.secondary">
          The priority score for a deal is derived primarily from the stage
          weight. Higher weight = higher priority. Scores are recalculated
          automatically when a deal's status changes (via drag-and-drop or API
          update). To recalculate all scores at once, run the CLI command:{' '}
          <code>flask recompute-deal-priority-scores</code>.
        </Typography>
      </Paper>
    </Box>
  )
}

export default PipelineConfigAdminPage
