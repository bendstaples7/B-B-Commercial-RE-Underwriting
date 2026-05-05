import React from 'react'
import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Paper,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  Typography,
  CircularProgress,
  Alert,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CancelIcon from '@mui/icons-material/Cancel'
import { useQuery } from '@tanstack/react-query'
import { condoFilterService } from '@/services/condoFilterApi'
import type {
  AddressGroupAnalysis,
  CondoFilterParams,
  CondoRiskStatus,
  BuildingSalePossible,
} from '@/types'

export interface CondoResultsTableProps {
  filters: CondoFilterParams
  onFiltersChange: (filters: CondoFilterParams) => void
  onRowClick: (analysis: AddressGroupAnalysis) => void
}

const RISK_STATUS_OPTIONS: { value: CondoRiskStatus | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'likely_condo', label: 'Likely Condo' },
  { value: 'likely_not_condo', label: 'Likely Not Condo' },
  { value: 'partial_condo_possible', label: 'Partial Condo Possible' },
  { value: 'needs_review', label: 'Needs Review' },
  { value: 'unknown', label: 'Unknown' },
]

const BUILDING_SALE_OPTIONS: { value: BuildingSalePossible | ''; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'unknown', label: 'Unknown' },
]

const REVIEWED_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'true', label: 'Reviewed' },
  { value: 'false', label: 'Not Reviewed' },
]

function getRiskStatusColor(status: CondoRiskStatus): 'error' | 'success' | 'warning' | 'info' | 'default' {
  switch (status) {
    case 'likely_condo': return 'error'
    case 'likely_not_condo': return 'success'
    case 'partial_condo_possible': return 'warning'
    case 'needs_review': return 'info'
    default: return 'default'
  }
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—'
  try {
    return new Date(dateStr).toLocaleDateString()
  } catch {
    return '—'
  }
}

export const CondoResultsTable: React.FC<CondoResultsTableProps> = ({
  filters,
  onFiltersChange,
  onRowClick,
}) => {
  const { data, isLoading, error } = useQuery({
    queryKey: ['condoFilterResults', filters],
    queryFn: () => condoFilterService.getResults(filters),
  })

  const handlePageChange = (_event: unknown, newPage: number) => {
    onFiltersChange({ ...filters, page: newPage + 1 })
  }

  const handleRowsPerPageChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    onFiltersChange({ ...filters, per_page: parseInt(event.target.value, 10), page: 1 })
  }

  return (
    <Box>
      {/* Filter Controls */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr' },
            gap: 2,
          }}
          role="search"
          aria-label="Condo filter results filters"
        >
          <FormControl size="small" fullWidth>
            <InputLabel id="condo-risk-status-filter-label">Condo Risk Status</InputLabel>
            <Select
              labelId="condo-risk-status-filter-label"
              value={filters.condo_risk_status || ''}
              label="Condo Risk Status"
              onChange={(e) =>
                onFiltersChange({
                  ...filters,
                  condo_risk_status: (e.target.value || undefined) as CondoRiskStatus | undefined,
                  page: 1,
                })
              }
            >
              {RISK_STATUS_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" fullWidth>
            <InputLabel id="building-sale-filter-label">Building Sale Possible</InputLabel>
            <Select
              labelId="building-sale-filter-label"
              value={filters.building_sale_possible || ''}
              label="Building Sale Possible"
              onChange={(e) =>
                onFiltersChange({
                  ...filters,
                  building_sale_possible: (e.target.value || undefined) as BuildingSalePossible | undefined,
                  page: 1,
                })
              }
            >
              {BUILDING_SALE_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" fullWidth>
            <InputLabel id="manually-reviewed-filter-label">Manually Reviewed</InputLabel>
            <Select
              labelId="manually-reviewed-filter-label"
              value={
                filters.manually_reviewed === true
                  ? 'true'
                  : filters.manually_reviewed === false
                    ? 'false'
                    : ''
              }
              label="Manually Reviewed"
              onChange={(e) => {
                const val = e.target.value
                onFiltersChange({
                  ...filters,
                  manually_reviewed: val === 'true' ? true : val === 'false' ? false : undefined,
                  page: 1,
                })
              }}
            >
              {REVIEWED_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Box>
      </Paper>

      {/* Error State */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error instanceof Error ? error.message : 'Failed to load results.'}
        </Alert>
      )}

      {/* Loading State */}
      {isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress aria-label="Loading results" />
        </Box>
      )}

      {/* Results Table */}
      {!isLoading && data && (
        <>
          <TableContainer component={Paper}>
            <Table size="small" aria-label="Condo filter analysis results">
              <TableHead>
                <TableRow>
                  <TableCell>Address</TableCell>
                  <TableCell>Risk Status</TableCell>
                  <TableCell>Building Sale</TableCell>
                  <TableCell>Confidence</TableCell>
                  <TableCell align="right">Properties</TableCell>
                  <TableCell align="right">PINs</TableCell>
                  <TableCell align="right">Owners</TableCell>
                  <TableCell>Unit #</TableCell>
                  <TableCell>Condo Lang</TableCell>
                  <TableCell align="right">Missing PINs</TableCell>
                  <TableCell align="right">Missing Owners</TableCell>
                  <TableCell>Reason</TableCell>
                  <TableCell>Analyzed</TableCell>
                  <TableCell>Reviewed</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.results.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={14} align="center">
                      <Typography variant="body2" color="text.secondary" sx={{ py: 4 }}>
                        No results found. Run analysis or adjust filters.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  data.results.map((row) => (
                    <TableRow
                      key={row.id}
                      hover
                      onClick={() => onRowClick(row)}
                      sx={{ cursor: 'pointer' }}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          onRowClick(row)
                        }
                      }}
                      aria-label={`View details for ${row.normalized_address}`}
                    >
                      <TableCell>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 200 }}>
                          {row.normalized_address}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={row.condo_risk_status.replace(/_/g, ' ')}
                          color={getRiskStatusColor(row.condo_risk_status)}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>{row.building_sale_possible}</TableCell>
                      <TableCell>{row.analysis_details?.confidence || '—'}</TableCell>
                      <TableCell align="right">{row.property_count}</TableCell>
                      <TableCell align="right">{row.pin_count}</TableCell>
                      <TableCell align="right">{row.owner_count}</TableCell>
                      <TableCell>
                        {row.has_unit_number ? (
                          <CheckCircleIcon fontSize="small" color="warning" aria-label="Yes" />
                        ) : (
                          <CancelIcon fontSize="small" color="disabled" aria-label="No" />
                        )}
                      </TableCell>
                      <TableCell>
                        {row.has_condo_language ? (
                          <CheckCircleIcon fontSize="small" color="warning" aria-label="Yes" />
                        ) : (
                          <CancelIcon fontSize="small" color="disabled" aria-label="No" />
                        )}
                      </TableCell>
                      <TableCell align="right">{row.missing_pin_count}</TableCell>
                      <TableCell align="right">{row.missing_owner_count}</TableCell>
                      <TableCell>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 180 }}>
                          {row.analysis_details?.reason || '—'}
                        </Typography>
                      </TableCell>
                      <TableCell>{formatDate(row.analyzed_at)}</TableCell>
                      <TableCell>
                        {row.manually_reviewed ? (
                          <Chip label="Yes" color="primary" size="small" variant="outlined" />
                        ) : (
                          '—'
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>

          <TablePagination
            component="div"
            count={data.total}
            page={(filters.page || 1) - 1}
            onPageChange={handlePageChange}
            rowsPerPage={filters.per_page || 20}
            onRowsPerPageChange={handleRowsPerPageChange}
            rowsPerPageOptions={[10, 20, 50, 100]}
          />
        </>
      )}
    </Box>
  )
}
