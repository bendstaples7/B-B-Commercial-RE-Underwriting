/**
 * Ready-to-Mail section: leads blocked on mailing address (invalid / USPS failed).
 */
import {
  Alert,
  Box,
  Link,
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
import { useQuery } from '@tanstack/react-query'
import { Link as RouterLink } from 'react-router-dom'
import openLetterService from '@/services/openLetterApi'

export function MailAddressProblemsSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['mail-address-problems'],
    queryFn: () => openLetterService.listAddressProblems(100),
    refetchInterval: 60_000,
  })

  const items = data?.items ?? []
  if (isLoading && !data) {
    return null
  }
  if (isError) {
    return (
      <Paper sx={{ p: 2, mb: 2 }} data-testid="mail-address-problems-section">
        <Alert severity="error">
          Couldn’t load address problems. Refresh the page or try again in a moment.
        </Alert>
      </Paper>
    )
  }
  if (items.length === 0) {
    return null
  }

  return (
    <Paper
      sx={{ p: 2, mb: 2 }}
      data-testid="mail-address-problems-section"
      aria-labelledby="mail-address-problems-title"
    >
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        gap={2}
        flexWrap="wrap"
        sx={{ mb: 1 }}
      >
        <Typography id="mail-address-problems-title" variant="h6" component="h2">
          Needs address fix
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {items.length} lead{items.length === 1 ? '' : 's'}
        </Typography>
      </Stack>
      <Alert severity="warning" sx={{ mb: 1.5 }}>
        These addresses failed validation (local or USPS via Open Letter). Fix the mailing
        address or skip-trace before they can mail again.
      </Alert>
      <TableContainer sx={{ overflowX: 'auto' }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Lead</TableCell>
              <TableCell>Property</TableCell>
              <TableCell>Mailing</TableCell>
              <TableCell>Problem</TableCell>
              <TableCell>Batch</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id} data-testid={`mail-address-problem-${item.lead_id}`}>
                <TableCell>
                  <Link component={RouterLink} to={`/leads/${item.lead_id}`} fontWeight={600}>
                    {item.owner_name || `Lead ${item.lead_id}`}
                  </Link>
                </TableCell>
                <TableCell>{item.property_street || '—'}</TableCell>
                <TableCell>
                  {[item.mailing_address, item.mailing_city, item.mailing_state, item.mailing_zip]
                    .filter(Boolean)
                    .join(', ') || '—'}
                </TableCell>
                <TableCell>
                  <Box component="span" sx={{ display: 'block' }}>
                    {item.problem_kind === 'address_failed' ? 'USPS failed' : 'Invalid address'}
                  </Box>
                  <Typography variant="caption" color="text.secondary">
                    {item.validation_error || '—'}
                  </Typography>
                </TableCell>
                <TableCell>
                  {item.campaign_id != null ? `#${item.campaign_id}` : '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  )
}

export default MailAddressProblemsSection
