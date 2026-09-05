import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import type {
  AnalystFindingCatalogItem,
  MotivationSignalDetail,
  PropertyDetail,
  PropertyScoreRecord,
} from '@/types'
import { leadService } from '@/services/leadApi'
import { motivationSeverityColor } from '@/utils/prospectMotivation'
import { commandCenterQueryKey } from '@/utils/afterCommandCenterMutation'

interface MotivationSignalsPanelProps {
  lead: PropertyDetail
  leadId: number
  /** Latest score record — used to surface HubSpot engagement (lead_score modifier). */
  score?: PropertyScoreRecord | null
}

export function MotivationSignalsPanel({ lead, leadId, score }: MotivationSignalsPanelProps) {
  const queryClient = useQueryClient()
  const signals = (lead.motivation_signals ?? []) as MotivationSignalDetail[]
  const summary = lead.motivation_signal_summary ?? []
  const details = score?.score_details ?? {}
  const notesKeywords = details.notes_keywords ?? 0
  const hubspotEngagement = details.hubspot_engagement ?? details.hubspot_signals ?? 0
  const timelineEngagement = details.timeline_engagement ?? 0

  const [findingKey, setFindingKey] = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: catalogData, isLoading: catalogLoading } = useQuery({
    queryKey: ['findingCatalog', leadId],
    queryFn: () => leadService.getFindingCatalog(leadId),
    staleTime: 60_000,
  })
  const catalog: AnalystFindingCatalogItem[] = catalogData?.findings ?? []

  useEffect(() => {
    if (!findingKey && catalog.length > 0) {
      const preferred =
        catalog.find((item) => item.finding_key === 'OWNER_SELLING_FSBO') ?? catalog[0]
      setFindingKey(preferred.finding_key)
    }
  }, [catalog, findingKey])

  const selected = catalog.find((item) => item.finding_key === findingKey)

  async function refreshAfterMutation() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['lead', leadId] }),
      queryClient.invalidateQueries({ queryKey: ['leadScore', leadId] }),
      queryClient.invalidateQueries({ queryKey: commandCenterQueryKey(leadId) }),
    ])
  }

  async function handleAddFinding() {
    if (!findingKey || saving) return
    setSaving(true)
    setError(null)
    try {
      await leadService.addFinding(leadId, findingKey, note.trim() || null)
      setNote('')
      await refreshAfterMutation()
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        'Could not add finding'
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  async function handleRemove(signalId: number) {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      await leadService.removeFinding(leadId, signalId)
      await refreshAfterMutation()
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        'Could not remove finding'
      setError(message)
    } finally {
      setSaving(false)
    }
  }

  const hasDetectedSignals =
    signals.length > 0 ||
    summary.length > 0 ||
    !!lead.motivation_score ||
    hubspotEngagement !== 0 ||
    timelineEngagement !== 0 ||
    notesKeywords !== 0

  return (
    <Box data-testid="motivation-signals-panel">
      {lead.motivation_score != null && (
        <Typography variant="body2" sx={{ mb: 0.5 }}>
          Product motivation score: <strong>{lead.motivation_score.toFixed(1)}</strong>
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
        Structured motivation from MotivationSignal rows (distress, source type, notes keywords,
        priority, and your findings). HubSpot CRM signal adjustments modify lead score engagement —
        they are not a second motivation score.
      </Typography>

      <Paper
        variant="outlined"
        sx={{ p: 1.5, mb: 2, cursor: 'auto' }}
        data-testid="add-finding-form"
      >
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Add finding
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
          Confirm facts like FSBO so they raise (or lower) seller motivation and queue priority.
        </Typography>
        {catalogLoading ? (
          <CircularProgress size={20} aria-label="Loading findings catalog" />
        ) : (
          <Stack spacing={1.5}>
            <FormControl size="small" fullWidth>
              <InputLabel id="finding-key-label">Finding</InputLabel>
              <Select
                labelId="finding-key-label"
                label="Finding"
                value={findingKey}
                onChange={(e) => setFindingKey(String(e.target.value))}
                data-testid="finding-key-select"
              >
                {catalog.map((item) => (
                  <MenuItem key={item.finding_key} value={item.finding_key}>
                    {item.label} ({item.points > 0 ? '+' : ''}
                    {item.points})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            {selected?.description && (
              <Typography variant="caption" color="text.secondary">
                {selected.description}
              </Typography>
            )}
            <TextField
              size="small"
              label="Optional note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              inputProps={{ maxLength: 500 }}
              data-testid="finding-note-input"
            />
            <Box>
              <Button
                variant="contained"
                size="small"
                onClick={handleAddFinding}
                disabled={!findingKey || saving}
                data-testid="add-finding-button"
              >
                {saving ? 'Saving…' : 'Add to score'}
              </Button>
            </Box>
          </Stack>
        )}
        {error && (
          <Alert severity="error" sx={{ mt: 1.5 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}
      </Paper>

      {!hasDetectedSignals && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          No automatic motivation signals yet. Cook County enrichment will populate tax, violation,
          and scofflaw signals — or add a finding above.
        </Typography>
      )}

      {(notesKeywords !== 0 || hubspotEngagement !== 0 || timelineEngagement !== 0) && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }} data-testid="motivation-attribution">
          {notesKeywords !== 0 && (
            <Chip
              size="small"
              label={`Notes keywords (${notesKeywords > 0 ? '+' : ''}${notesKeywords}) — in motivation`}
              color="warning"
              variant="outlined"
            />
          )}
          {hubspotEngagement !== 0 && (
            <Chip
              size="small"
              label={`HubSpot engagement (${hubspotEngagement > 0 ? '+' : ''}${hubspotEngagement}) — lead score`}
              color="info"
              variant="outlined"
            />
          )}
          {timelineEngagement !== 0 && (
            <Chip
              size="small"
              label={`Timeline engagement (${timelineEngagement > 0 ? '+' : ''}${timelineEngagement}) — lead score`}
              color="info"
              variant="outlined"
            />
          )}
        </Box>
      )}

      {summary.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 2 }}>
          {summary.map((item) => (
            <Chip
              key={item.signal_type}
              size="small"
              label={`${item.label} (${item.points > 0 ? '+' : ''}${item.points})`}
              color={item.points < 0 ? 'default' : 'warning'}
              variant="outlined"
            />
          ))}
        </Box>
      )}
      {signals.length > 0 && (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Signal</TableCell>
                <TableCell>Severity</TableCell>
                <TableCell align="right">Points</TableCell>
                <TableCell>Source</TableCell>
                <TableCell>Dataset</TableCell>
                <TableCell align="right" width={48} />
              </TableRow>
            </TableHead>
            <TableBody>
              {signals.map((sig) => (
                <TableRow key={sig.id}>
                  <TableCell>
                    {sig.label ?? sig.signal_type}
                    {typeof sig.evidence?.note === 'string' && sig.evidence.note ? (
                      <Typography variant="caption" color="text.secondary" display="block">
                        {sig.evidence.note}
                      </Typography>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <Chip size="small" label={sig.severity} color={motivationSeverityColor(sig.severity)} />
                  </TableCell>
                  <TableCell align="right">{sig.points > 0 ? `+${sig.points}` : sig.points}</TableCell>
                  <TableCell>{sig.source === 'analyst' ? 'You' : sig.source}</TableCell>
                  <TableCell>{sig.source_dataset ?? '—'}</TableCell>
                  <TableCell align="right">
                    {(sig.removable || sig.source === 'analyst') && (
                      <IconButton
                        size="small"
                        aria-label={`Remove ${sig.label ?? sig.signal_type}`}
                        onClick={() => handleRemove(sig.id)}
                        disabled={saving}
                        data-testid={`remove-finding-${sig.id}`}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}
