import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Link,
  Stack,
  Typography,
} from '@mui/material'
import { Link as RouterLink } from 'react-router-dom'
import type { BulkActionResult } from '@/types'

type MailResult = NonNullable<BulkActionResult['mail_enqueue']>
type Outcome = MailResult['results'][number]

interface MailEnqueueResultDialogProps {
  open: boolean
  onClose: () => void
  result: MailResult | null
  title?: string
}

const STATUS_LABELS: Record<string, string> = {
  queued: 'Staged',
  invalid_address: 'Invalid address',
  recently_sold: 'Recently sold',
  already_queued: 'Already staged',
  not_authorized: 'Not authorized',
  not_found: 'Not found',
  error: 'Could not stage',
}

function outcomeDetail(outcome: Outcome): string | null {
  if (outcome.error) return outcome.error
  if (outcome.status === 'recently_sold' && outcome.sale_date) {
    return `Sale date: ${outcome.sale_date}`
  }
  return null
}

function OutcomeGroup({ label, outcomes }: { label: string; outcomes: Outcome[] }) {
  if (outcomes.length === 0) return null
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
        {label} ({outcomes.length})
      </Typography>
      <Stack divider={<Divider flexItem />} spacing={1}>
        {outcomes.map((outcome) => (
          <Stack
            key={`${outcome.lead_id}-${outcome.status}`}
            direction={{ xs: 'column', sm: 'row' }}
            justifyContent="space-between"
            spacing={1}
            data-testid={`mail-result-${outcome.lead_id}`}
          >
            <Box>
              <Link component={RouterLink} to={`/leads/${outcome.lead_id}`} fontWeight={600}>
                {outcome.owner_name || `Lead ${outcome.lead_id}`}
              </Link>
              {outcome.property_street && (
                <Typography variant="body2" color="text.secondary">
                  {outcome.property_street}
                </Typography>
              )}
              {outcomeDetail(outcome) && (
                <Typography variant="caption" color="warning.main">
                  {outcomeDetail(outcome)}
                </Typography>
              )}
            </Box>
            <Chip
              size="small"
              label={STATUS_LABELS[outcome.status] ?? outcome.status}
              color={outcome.status === 'queued' ? 'success' : 'warning'}
              sx={{ alignSelf: { xs: 'flex-start', sm: 'center' } }}
            />
          </Stack>
        ))}
      </Stack>
    </Box>
  )
}

export function MailEnqueueResultDialog({
  open,
  onClose,
  result,
  title = 'Direct mail results',
}: MailEnqueueResultDialogProps) {
  if (!result) return null

  const staged = result.results.filter((item) => item.status === 'queued')
  const invalid = result.results.filter((item) => item.status === 'invalid_address')
  const recentlySold = result.results.filter((item) => item.status === 'recently_sold')
  const other = result.results.filter(
    (item) => !['queued', 'invalid_address', 'recently_sold'].includes(item.status),
  )

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" sx={{ mb: 2 }}>
          {result.added} staged · {result.invalid + result.skipped} need attention
        </Typography>
        <Stack spacing={2.5}>
          <OutcomeGroup label="Invalid addresses" outcomes={invalid} />
          <OutcomeGroup label="Recently sold" outcomes={recentlySold} />
          <OutcomeGroup label="Other outcomes" outcomes={other} />
          <OutcomeGroup label="Staged for next batch" outcomes={staged} />
        </Stack>
      </DialogContent>
      <DialogActions>
        {result.added > 0 && (
          <Button component={RouterLink} to="/queues/ready-to-mail">
            View staged batch
          </Button>
        )}
        <Button onClick={onClose} variant="contained">Close</Button>
      </DialogActions>
    </Dialog>
  )
}

export default MailEnqueueResultDialog
