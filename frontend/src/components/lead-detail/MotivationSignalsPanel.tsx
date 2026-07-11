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
import type { MotivationSignalDetail, PropertyDetail, PropertyScoreRecord } from '@/types'
import { motivationSeverityColor } from '@/utils/prospectMotivation'

interface MotivationSignalsPanelProps {
  lead: PropertyDetail
  /** Latest score record — used to surface HubSpot engagement (lead_score modifier). */
  score?: PropertyScoreRecord | null
}

export function MotivationSignalsPanel({ lead, score }: MotivationSignalsPanelProps) {
  const signals = (lead.motivation_signals ?? []) as MotivationSignalDetail[]
  const summary = lead.motivation_signal_summary ?? []
  const details = score?.score_details ?? {}
  const notesKeywords = details.notes_keywords ?? 0
  const hubspotEngagement = details.hubspot_engagement ?? details.hubspot_signals ?? 0
  const timelineEngagement = details.timeline_engagement ?? 0

  if (
    !signals.length &&
    !summary.length &&
    !lead.motivation_score &&
    !hubspotEngagement &&
    !timelineEngagement
  ) {
    return (
      <Typography variant="body2" color="text.secondary">
        No structured motivation signals detected yet. Cook County enrichment will populate tax, violation, and scofflaw signals.
      </Typography>
    )
  }

  return (
    <Box data-testid="motivation-signals-panel">
      {lead.motivation_score != null && (
        <Typography variant="body2" sx={{ mb: 0.5 }}>
          Product motivation score: <strong>{lead.motivation_score.toFixed(1)}</strong>
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
        This is structured motivation from MotivationSignal rows (distress, source type, notes
        keywords, priority). HubSpot CRM signal adjustments modify lead score engagement — they are
        not a second motivation score.
      </Typography>

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
