
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Alert,
  Chip,
  Tooltip,
  IconButton,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { multifamilyService } from '@/services/api'
import type { DealSummary } from '@/types'

// ---------------------------------------------------------------------------
// Helpers (Copied from DealListPage.tsx, can be refactored into a utils file if needed)
// ---------------------------------------------------------------------------

function formatCurrency(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(num)
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function statusColor(status: string): 'default' | 'primary' | 'success' | 'warning' {
  switch (status?.toLowerCase()) {
    case 'active':
      return 'success'
    case 'under_review':
      return 'primary'
    case 'draft':
      return 'warning'
    default:
      return 'default'
  }
}

// ---------------------------------------------------------------------------
// Quotes Table (adapted from DealTable)
// ---------------------------------------------------------------------------

interface QuoteTableProps {
  quotes: DealSummary[] // Re-using DealSummary as it has relevant quote-like data
  onOpen: (dealId: number) => void
}

function QuoteTable({ quotes, onOpen }: QuoteTableProps) {
  if (quotes.length === 0) {
    return (
      <Box sx={{ py: 8, textAlign: 'center' }}>
        <Typography color='text.secondary'>
          No quotes available yet.
        </Typography>
      </Box>
    )
  }

  return (
    <TableContainer component={Paper} variant='outlined'>
      <Table aria-label='Quotes table'>
        <TableHead>
          <TableRow>
            <TableCell>Address</TableCell>
            <TableCell align='right'>Units</TableCell>
            <TableCell align='right'>Purchase Price</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Created</TableCell>
            <TableCell>Updated</TableCell>
            <TableCell align='center'>View</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {quotes.map((quote) => (
            <TableRow
              key={quote.id}
              hover
              sx={{ cursor: 'pointer' }}
              onClick={() => onOpen(quote.id)}
            >
              <TableCell>
                <Typography variant='body2' fontWeight={500}>
                  {quote.property_address}
                </Typography>
              </TableCell>
              <TableCell align='right'>{quote.unit_count}</TableCell>
              <TableCell align='right'>{formatCurrency(quote.purchase_price)}</TableCell>
              <TableCell>
                <Chip
                  label={quote.status ?? 'draft'}
                  color={statusColor(quote.status)}
                  size='small'
                />
              </TableCell>
              <TableCell>{formatDate(quote.created_at)}</TableCell>
              <TableCell>{formatDate(quote.updated_at)}</TableCell>
              <TableCell align='center'>
                <Tooltip title='View Quote Details'>
                  <IconButton
                    size='small'
                    onClick={(e) => {
                      e.stopPropagation()
                      onOpen(quote.id)
                    }}
                    aria-label={`View quote details for ${quote.property_address}`}
                  >
                    <OpenInNewIcon fontSize='small' />
                  </IconButton>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function QuotesPage() {
  const navigate = useNavigate()

  const {
    data: quotes,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['multifamily', 'deals'], // Re-using the deals query for quotes
    queryFn: () => multifamilyService.listDeals(),
  })

  // Placeholder for "Create New Quote" functionality
  const handleCreateNewQuote = () => {
    alert('Create New Quote functionality to be implemented!')
    // In a real scenario, this would navigate to a form or open a dialog
    // similar to CreateDealDialog in DealListPage.tsx
  }

  return (
    <Box>
      {/* Header */}
      <Box
        sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}
      >
        <Typography variant='h5' component='h1' fontWeight={600}>
          Quotes
        </Typography>
        <Button
          variant='contained'
          startIcon={<AddIcon />}
          onClick={handleCreateNewQuote}
          aria-label='Create new quote'
        >
          New Quote
        </Button>
      </Box>

      {/* Content */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
          <CircularProgress aria-label='Loading quotes' />
        </Box>
      )}

      {isError && (
        <Alert severity='error' sx={{ mb: 2 }}>
          {(error as Error)?.message ?? 'Failed to load quotes'}
        </Alert>
      )}

      {!isLoading && !isError && (
        <QuoteTable quotes={quotes ?? []} onOpen={(id) => navigate(`/multifamily/deals/${id}`)} />
      )}
    </Box>
  )
}

export default QuotesPage
