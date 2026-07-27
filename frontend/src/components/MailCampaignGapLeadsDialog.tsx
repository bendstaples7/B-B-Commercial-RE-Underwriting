import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import openLetterService, {
  type MailCampaignGapKind,
  type MailCampaignGapLead,
} from '@/services/openLetterApi'
import { formatGapLeadsTsv } from '@/utils/formatGapLeadsTsv'

export type MailCampaignGapLeadsDialogProps = {
  open: boolean
  onClose: () => void
  campaignId: number | null
  kind: MailCampaignGapKind | null
}

function titleFor(kind: MailCampaignGapKind | null, campaignId: number | null): string {
  const batch = campaignId != null ? ` — batch #${campaignId}` : ''
  if (kind === 'olc_omitted') return `Not on OLC order${batch}`
  return `Invalid addresses${batch}`
}

function dispositionLabel(row: MailCampaignGapLead): string {
  if (row.disposition === 'requeued') return 'Requeued'
  if (row.disposition === 'support') return 'Support'
  if (row.disposition === 'invalid_local') return 'Invalid'
  return row.disposition || '—'
}

export function MailCampaignGapLeadsDialog({
  open,
  onClose,
  campaignId,
  kind,
}: MailCampaignGapLeadsDialogProps) {
  const [copyNote, setCopyNote] = useState<string | null>(null)
  const enabled = open && campaignId != null && kind != null
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['mail-campaign-gap-leads', campaignId, kind],
    queryFn: ({ signal }) =>
      openLetterService.getCampaignGapLeads(campaignId!, kind!, { signal }),
    enabled,
    retry: false,
  })

  const leads = data?.leads ?? []
  const canCopy = leads.length > 0 && !isLoading && !isError

  const handleCopy = async () => {
    const text = formatGapLeadsTsv(leads, kind)
    try {
      await navigator.clipboard.writeText(text)
      setCopyNote(`Copied ${leads.length} row${leads.length === 1 ? '' : 's'}`)
    } catch {
      setCopyNote('Copy failed — select the table and copy manually')
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      aria-labelledby="mail-campaign-gap-leads-title"
      data-testid="mail-campaign-gap-leads-dialog"
      TransitionProps={{
        onExited: () => setCopyNote(null),
      }}
    >
      <DialogTitle id="mail-campaign-gap-leads-title" sx={{ pr: 2 }}>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          gap={2}
          flexWrap="wrap"
        >
          <Box component="span" sx={{ fontSize: 'inherit', fontWeight: 500 }}>
            {titleFor(kind, campaignId)}
          </Box>
          <Button
            size="small"
            variant="outlined"
            disabled={!canCopy}
            onClick={() => void handleCopy()}
            data-testid="mail-campaign-gap-copy-excel"
          >
            Copy for Excel
          </Button>
        </Stack>
      </DialogTitle>
      <DialogContent dividers>
        {copyNote ? (
          <Alert severity="success" sx={{ mb: 1.5 }} onClose={() => setCopyNote(null)}>
            {copyNote}
          </Alert>
        ) : null}
        {isLoading || (isFetching && !data) ? (
          <Box
            sx={{ display: 'flex', justifyContent: 'center', py: 4 }}
            data-testid="mail-campaign-gap-leads-loading"
          >
            <CircularProgress size={28} />
          </Box>
        ) : isError ? (
          <Alert
            severity="error"
            action={
              <Button color="inherit" size="small" onClick={() => refetch()}>
                Retry
              </Button>
            }
          >
            {(error as Error)?.message || 'Could not load leads'}
          </Alert>
        ) : leads.length === 0 ? (
          <Typography color="text.secondary" data-testid="mail-campaign-gap-leads-empty">
            {kind === 'olc_omitted'
              ? 'No cached OLC-omitted list for this batch yet. Click Refresh on Mail Batches to sync analytics, then reopen.'
              : 'No leads in this gap.'}
          </Typography>
        ) : (
          <Table size="small" data-testid="mail-campaign-gap-leads-table">
            <TableHead>
              <TableRow>
                <TableCell>Lead</TableCell>
                <TableCell>Property</TableCell>
                <TableCell>Mailing</TableCell>
                <TableCell>Reason</TableCell>
                <TableCell>Where now</TableCell>
                {kind === 'olc_omitted' ? <TableCell>Omit</TableCell> : null}
              </TableRow>
            </TableHead>
            <TableBody>
              {leads.map((row) => (
                <TableRow key={row.lead_id} data-testid={`mail-gap-lead-${row.lead_id}`}>
                  <TableCell>
                    <Link
                      component={RouterLink}
                      to={`/leads/${row.lead_id}`}
                      fontWeight={600}
                    >
                      {row.owner_name || `Lead ${row.lead_id}`}
                    </Link>
                  </TableCell>
                  <TableCell>{row.property_street || '—'}</TableCell>
                  <TableCell>{row.mailing_address || '—'}</TableCell>
                  <TableCell>{row.reason || '—'}</TableCell>
                  <TableCell>{row.resolution || dispositionLabel(row)}</TableCell>
                  {kind === 'olc_omitted' ? (
                    <TableCell>
                      {row.omit_count != null ? `${row.omit_count}×` : dispositionLabel(row)}
                    </TableCell>
                  ) : null}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  )
}

export default MailCampaignGapLeadsDialog
