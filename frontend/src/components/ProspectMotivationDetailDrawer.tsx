import {
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import type { ProspectCandidate } from '@/types'
import {
  PROSPECT_MIN_MOTIVATION_PCT,
  PROSPECT_MOTIVATION_CAP,
  formatEvidenceLines,
  formatProspectAddress,
  formatProspectMotivationPct,
  formatRecencyNote,
  formatSignalPoints,
  motivationSeverityColor,
  prospectSignalLabel,
  sortedProspectSignals,
} from '@/utils/prospectMotivation'

interface ProspectMotivationDetailDrawerProps {
  candidate: ProspectCandidate | null
  open: boolean
  onClose: () => void
}

export function ProspectMotivationDetailDrawer({
  candidate,
  open,
  onClose,
}: ProspectMotivationDetailDrawerProps) {
  const signals = candidate ? sortedProspectSignals(candidate) : []
  const rawTotal = signals.reduce((sum, sig) => sum + sig.points, 0)
  const cappedScore = candidate?.motivation_score ?? Math.min(rawTotal, PROSPECT_MOTIVATION_CAP)

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      data-testid="prospect-motivation-drawer"
      PaperProps={{ sx: { width: { xs: '100%', sm: 420 } } }}
    >
      {candidate && (
        <Box sx={{ p: 2, height: '100%', display: 'flex', flexDirection: 'column' }}>
          <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 1 }}>
            <Box>
              <Typography variant="h6" component="h2">
                Motivation breakdown
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {formatProspectAddress(candidate)}
              </Typography>
              {candidate.pin && (
                <Typography variant="caption" color="text.secondary" display="block">
                  PIN {candidate.pin}
                </Typography>
              )}
            </Box>
            <IconButton aria-label="Close motivation details" onClick={onClose} size="small">
              <CloseIcon />
            </IconButton>
          </Box>

          <Box sx={{ mb: 2 }}>
            <Typography variant="h4" component="p" sx={{ fontWeight: 600 }}>
              {formatProspectMotivationPct(candidate)}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {cappedScore.toFixed(1)} of {PROSPECT_MOTIVATION_CAP} points · {PROSPECT_MIN_MOTIVATION_PCT}% minimum
              to enter this queue
            </Typography>
            {rawTotal > PROSPECT_MOTIVATION_CAP && (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                Raw signal sum is {rawTotal.toFixed(1)} points; score is capped at {PROSPECT_MOTIVATION_CAP}.
              </Typography>
            )}
          </Box>

          <Divider sx={{ mb: 2 }} />

          {signals.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No stacked signals recorded for this prospect.
            </Typography>
          ) : (
            <TableContainer sx={{ flex: 1, overflow: 'auto' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Signal</TableCell>
                    <TableCell align="right">Points</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {signals.map((sig) => {
                    const evidenceLines = formatEvidenceLines(sig.evidence)
                    const recencyNote = formatRecencyNote(sig)
                    return (
                      <TableRow key={`${sig.signal_type}-${sig.evidence_key ?? sig.label}`}>
                        <TableCell>
                          <Typography variant="body2">{prospectSignalLabel(sig)}</Typography>
                          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                            <Chip
                              size="small"
                              label={sig.severity}
                              color={motivationSeverityColor(sig.severity)}
                              variant="outlined"
                            />
                          </Box>
                          {evidenceLines.map((line) => (
                            <Typography
                              key={line}
                              variant="caption"
                              color="text.secondary"
                              display="block"
                              sx={{ mt: 0.5 }}
                            >
                              {line}
                            </Typography>
                          ))}
                          {recencyNote && (
                            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                              {recencyNote}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell align="right" sx={{ verticalAlign: 'top' }}>
                          <Typography variant="body2">{formatSignalPoints(sig)}</Typography>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                  <TableRow>
                    <TableCell sx={{ fontWeight: 600 }}>Total (capped)</TableCell>
                    <TableCell align="right" sx={{ fontWeight: 600 }}>
                      {cappedScore.toFixed(1)}
                    </TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </TableContainer>
          )}

          <Typography variant="caption" color="text.secondary" sx={{ mt: 2 }}>
            Distress signals from Cook County and Chicago feeds stack by PIN. Violations, 311
            complaints, and vacant-building signals decay with age (100% through 90 days, then 75% /
            50% / 25%). This percentage reflects signal strength only — not the lead score after import.
          </Typography>
        </Box>
      )}
    </Drawer>
  )
}

export default ProspectMotivationDetailDrawer
