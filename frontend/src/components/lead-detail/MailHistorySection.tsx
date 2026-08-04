/**
 * Detailed mail history — chips, table, returned addresses, attributed responses.
 * Canonical surface: At a glance (PropertyKpiCard). Do not reintroduce in Marketing tab.
 */
import {
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import type { CommandCenterPayload, PropertyDetail } from '@/types'
import { ccSubsectionTitleSx } from '@/components/lead-detail/commandCenterChrome'
import { formatDateTime } from '@/utils/formatters'
import { resolveMailerHistorySummary } from '@/utils/mailerHistory'

export interface MailHistorySectionProps {
  commandCenterData: CommandCenterPayload
  propertyDetail?: PropertyDetail | null
}

export function MailHistorySection({
  commandCenterData,
  propertyDetail,
}: MailHistorySectionProps) {
  const legacyHistory =
    propertyDetail?.mailer_history ??
    (commandCenterData as { mailer_history?: unknown }).mailer_history
  const mailSummary = resolveMailerHistorySummary(
    commandCenterData.mailer_history_summary,
    legacyHistory,
  )
  const queued = commandCenterData.mail_queue_status === 'queued'
  const upNext =
    propertyDetail?.up_next_to_mail ?? commandCenterData.up_next_to_mail
  const returnedAddresses =
    propertyDetail?.returned_addresses ??
    (commandCenterData as { returned_addresses?: string | null }).returned_addresses
  const attributed = commandCenterData.mail_attributed_responses ?? []

  return (
    <Box
      id="mail-history-section"
      data-testid="mail-history-section"
      sx={{
        mt: 1.5,
        pt: 1.25,
        borderTop: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Typography variant="subtitle2" sx={{ ...ccSubsectionTitleSx, mb: 1 }}>
        Mail history
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
        <Chip
          size="small"
          label={`${mailSummary.count} mailer${mailSummary.count === 1 ? '' : 's'}`}
        />
        {mailSummary.last_sent_at && (
          <Chip size="small" variant="outlined" label={`Last: ${mailSummary.last_sent_at}`} />
        )}
        {queued && <Chip size="small" color="primary" label="In mail queue" />}
        {Boolean(upNext) && !queued && (
          <Chip size="small" label="Up Next to Mail (legacy)" />
        )}
        {returnedAddresses && (
          <Chip size="small" color="warning" label="Has returned address(es)" />
        )}
      </Stack>
      {mailSummary.rows.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          No mailers recorded for this lead yet.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
          <Table size="small" aria-label="Mail history">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>When</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Mailer</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Source</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Notes</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {mailSummary.rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.sent_at || '—'}</TableCell>
                  <TableCell>
                    {row.label}
                    {row.campaign_id != null ? ` (#${row.campaign_id})` : ''}
                  </TableCell>
                  <TableCell>
                    {row.source === 'olc'
                      ? 'Open Letter'
                      : row.source === 'timeline'
                        ? 'Timeline'
                        : 'Imported'}
                  </TableCell>
                  <TableCell>
                    {[
                      row.address_feedback ? `Feedback: ${row.address_feedback}` : null,
                      row.cancelled ? 'Cancelled' : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {returnedAddresses && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Returned addresses: {returnedAddresses}
        </Alert>
      )}

      <Typography variant="subtitle2" sx={{ ...ccSubsectionTitleSx, mb: 1, mt: 1 }}>
        Responses attributed to mail
      </Typography>
      {attributed.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No attributed responses.
        </Typography>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small" aria-label="Mail-attributed responses">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold' }}>When</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Event</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Campaign</TableCell>
                <TableCell sx={{ fontWeight: 'bold' }}>Summary</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {attributed.map((e) => {
                const meta = (e.metadata || {}) as Record<string, unknown>
                return (
                  <TableRow key={e.id}>
                    <TableCell>{formatDateTime(e.occurred_at || e.created_at)}</TableCell>
                    <TableCell>{e.event_type}</TableCell>
                    <TableCell>
                      {meta.mail_campaign_id != null ? String(meta.mail_campaign_id) : '—'}
                    </TableCell>
                    <TableCell>{e.summary || '—'}</TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}

export default MailHistorySection
