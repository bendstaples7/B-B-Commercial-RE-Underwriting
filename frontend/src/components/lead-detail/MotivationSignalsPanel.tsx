import {
  Box,
  Chip,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import type { MotivationSignalDetail, PropertyDetail } from '@/types'
import { motivationSeverityColor } from '@/utils/prospectMotivation'

interface MotivationSignalsPanelProps {
  lead: PropertyDetail
}

export function MotivationSignalsPanel({ lead }: MotivationSignalsPanelProps) {
  const signals = (lead.motivation_signals ?? []) as MotivationSignalDetail[]
  const summary = lead.motivation_signal_summary ?? []

  if (!signals.length && !summary.length && !lead.motivation_score) {
    return (
      <Typography variant="body2" color="text.secondary">
        No structured motivation signals detected yet. Cook County enrichment will populate tax, violation, and scofflaw signals.
      </Typography>
    )
  }

  return (
    <Box data-testid="motivation-signals-panel">
      {lead.motivation_score != null && (
        <Typography variant="body2" sx={{ mb: 1 }}>
          Structured motivation score: <strong>{lead.motivation_score.toFixed(1)}</strong>
        </Typography>
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
              </TableRow>
            </TableHead>
            <TableBody>
              {signals.map((sig) => (
                <TableRow key={sig.id}>
                  <TableCell>{sig.label ?? sig.signal_type}</TableCell>
                  <TableCell>
                    <Chip size="small" label={sig.severity} color={motivationSeverityColor(sig.severity)} />
                  </TableCell>
                  <TableCell align="right">{sig.points > 0 ? `+${sig.points}` : sig.points}</TableCell>
                  <TableCell>{sig.source}</TableCell>
                  <TableCell>{sig.source_dataset ?? '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}
