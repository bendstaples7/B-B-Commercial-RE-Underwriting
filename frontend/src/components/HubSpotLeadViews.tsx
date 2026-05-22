/**
 * HubSpotLeadViews — Six pre-built filtered lead views for the HubSpot CRM migration.
 *
 * Views:
 *  1. PreviouslyWarmLeadsView   — leads with warm conversation / appointment signals
 *  2. NeedsReviewView           — HubSpot-imported leads needing review
 *  3. FollowUpOverdueView       — leads with overdue open tasks
 *  4. NoNextActionView          — leads with no open task or future interaction
 *  5. DoNotContactView          — suppressed leads
 *  6. MissingPropertyMatchView  — HubSpot placeholder leads with no confirmed match
 *
 * Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7
 */
import { useQuery } from '@tanstack/react-query'
import {
  Box,
  Typography,
  CircularProgress,
  Alert,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TableContainer,
  Paper,
} from '@mui/material'
import { leadViewService } from '@/services/api'
import type { PropertySummary } from '@/types'
import { ReviewQueue } from '@/components/ReviewQueue'

// ---------------------------------------------------------------------------
// Shared lead list table
// ---------------------------------------------------------------------------

interface LeadListTableProps {
  leads: PropertySummary[]
}

function LeadListTable({ leads }: LeadListTableProps) {
  if (leads.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
        No properties found.
      </Typography>
    )
  }

  return (
    <TableContainer component={Paper} variant="outlined" sx={{ mt: 2 }}>
      <Table size="small" aria-label="Property list">
        <TableHead>
          <TableRow>
            <TableCell>Property Street</TableCell>
            <TableCell>Owner First Name</TableCell>
            <TableCell>Owner Last Name</TableCell>
            <TableCell align="right">Score</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {leads.map((lead) => (
            <TableRow key={lead.id} hover>
              <TableCell>{lead.property_street ?? '—'}</TableCell>
              <TableCell>{lead.owner_first_name ?? '—'}</TableCell>
              <TableCell>{lead.owner_last_name ?? '—'}</TableCell>
              <TableCell align="right">{lead.lead_score}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

// ---------------------------------------------------------------------------
// Shared view wrapper
// ---------------------------------------------------------------------------

interface LeadViewProps {
  title: string
  queryKey: string[]
  queryFn: () => Promise<PropertySummary[]>
}

function LeadView({ title, queryKey, queryFn }: LeadViewProps) {
  const { data, isLoading, isError, error } = useQuery<PropertySummary[], Error>({
    queryKey,
    queryFn,
  })

  return (
    <Box sx={{ px: { xs: 1, sm: 2 } }}>
      <Typography variant="h5" component="h2" gutterBottom>
        {title}
      </Typography>

      {isLoading && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 2 }}>
          <CircularProgress size={20} />
          <Typography variant="body2" color="text.secondary">
            Loading…
          </Typography>
        </Box>
      )}

      {isError && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error?.message ?? 'Failed to load properties.'}
        </Alert>
      )}

      {!isLoading && !isError && data !== undefined && (
        <LeadListTable leads={data} />
      )}
    </Box>
  )
}

// ---------------------------------------------------------------------------
// 1. Previously Warm Leads
// ---------------------------------------------------------------------------

export function PreviouslyWarmLeadsView() {
  return (
    <LeadView
      title="Previously Warm Properties"
      queryKey={['leads', 'views', 'previously-warm']}
      queryFn={leadViewService.getPreviouslyWarmLeads}
    />
  )
}

// ---------------------------------------------------------------------------
// 2. Needs Review — renders the full Review Queue inline
// ---------------------------------------------------------------------------

export function NeedsReviewView() {
  return <ReviewQueue standalone={true} />
}


// ---------------------------------------------------------------------------
// 3. Follow-Up Overdue
// ---------------------------------------------------------------------------

export function FollowUpOverdueView() {
  return (
    <LeadView
      title="Follow-Up Overdue"
      queryKey={['leads', 'views', 'follow-up-overdue']}
      queryFn={leadViewService.getFollowUpOverdueLeads}
    />
  )
}

// ---------------------------------------------------------------------------
// 4. No Current Next Action
// ---------------------------------------------------------------------------

export function NoNextActionView() {
  return (
    <LeadView
      title="No Current Next Action"
      queryKey={['leads', 'views', 'no-next-action']}
      queryFn={leadViewService.getNoNextActionLeads}
    />
  )
}

// ---------------------------------------------------------------------------
// 5. Do Not Contact
// ---------------------------------------------------------------------------

export function DoNotContactView() {
  return (
    <LeadView
      title="Do Not Contact"
      queryKey={['leads', 'views', 'do-not-contact']}
      queryFn={leadViewService.getDoNotContactLeads}
    />
  )
}

// ---------------------------------------------------------------------------
// 6. Missing Property Match
// ---------------------------------------------------------------------------

export function MissingPropertyMatchView() {
  return (
    <LeadView
      title="Missing Property Match"
      queryKey={['leads', 'views', 'missing-property-match']}
      queryFn={leadViewService.getMissingPropertyMatchLeads}
    />
  )
}
