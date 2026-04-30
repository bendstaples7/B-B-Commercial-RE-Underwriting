import React, { useState, useEffect, useCallback } from 'react'
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Typography,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Button,
  Chip,
  CircularProgress,
  Alert,
  Pagination,
  Slider,
  Collapse,
} from '@mui/material'
import FilterListIcon from '@mui/icons-material/FilterList'
import ClearIcon from '@mui/icons-material/Clear'
import type {
  LeadSummary,
  LeadListFilters,
  LeadListResponse,
  MarketingList,
} from '@/types'
import { leadService } from '@/services/leadApi'

/** Props accepted by LeadListPage. */
export interface LeadListPageProps {
  /** Called when the user clicks a lead row. */
  onLeadSelect?: (leadId: number) => void
}

type SortField = 'lead_score' | 'created_at' | 'property_street'
type SortOrder = 'asc' | 'desc'

const PROPERTY_TYPE_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'Single Family', label: 'Single Family' },
  { value: 'Multi Family', label: 'Multi Family' },
  { value: 'Commercial', label: 'Commercial' },
  { value: 'Condo', label: 'Condo' },
  { value: 'Townhouse', label: 'Townhouse' },
  { value: 'Land', label: 'Land' },
]

const PER_PAGE = 20

/**
 * Paginated lead list with filtering, sorting, and score display.
 *
 * Requirements: 4.5, 4.6, 5.5, 5.6
 */
export const LeadListPage: React.FC<LeadListPageProps> = ({ onLeadSelect }) => {
  // Data state
  const [leads, setLeads] = useState<LeadSummary[]>([])
  const [totalLeads, setTotalLeads] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filter state
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [propertyType, setPropertyType] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [zip, setZip] = useState('')
  const [ownerName, setOwnerName] = useState('')
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100])
  const [marketingListId, setMarketingListId] = useState<number | ''>('')

  // Pagination & sorting
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState<SortField>('lead_score')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  // Marketing lists for filter dropdown
  const [marketingLists, setMarketingLists] = useState<MarketingList[]>([])

  // Build the filters object from current state
  const buildFilters = useCallback((): LeadListFilters => {
    const filters: LeadListFilters = {
      page,
      per_page: PER_PAGE,
      sort_by: sortBy,
      sort_order: sortOrder,
    }
    if (propertyType) filters.property_type = propertyType
    if (city.trim()) filters.city = city.trim()
    if (state.trim()) filters.state = state.trim()
    if (zip.trim()) filters.zip = zip.trim()
    if (ownerName.trim()) filters.owner_name = ownerName.trim()
    if (scoreRange[0] > 0) filters.score_min = scoreRange[0]
    if (scoreRange[1] < 100) filters.score_max = scoreRange[1]
    if (marketingListId !== '') filters.marketing_list_id = marketingListId as number
    return filters
  }, [page, sortBy, sortOrder, propertyType, city, state, zip, ownerName, scoreRange, marketingListId])

  // Fetch leads
  const fetchLeads = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response: LeadListResponse = await leadService.listLeads(buildFilters())
      setLeads(response.leads)
      setTotalLeads(response.total)
      setTotalPages(response.pages)
    } catch (err: any) {
      setError(err.message || 'Failed to load leads.')
    } finally {
      setLoading(false)
    }
  }, [buildFilters])

  // Fetch marketing lists for the filter dropdown (once)
  useEffect(() => {
    const loadMarketingLists = async () => {
      try {
        const response = await leadService.listMarketingLists({ per_page: 100 })
        setMarketingLists(response.lists)
      } catch {
        // Non-critical — filter dropdown just won't have options
      }
    }
    loadMarketingLists()
  }, [])

  // Reload leads when filters, page, or sort change
  useEffect(() => {
    fetchLeads()
  }, [fetchLeads])

  // Sorting handler
  const handleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(field)
      setSortOrder(field === 'property_street' ? 'asc' : 'desc')
    }
    setPage(1)
  }

  // Apply filters (reset to page 1)
  const handleApplyFilters = () => {
    setPage(1)
    fetchLeads()
  }

  // Clear all filters
  const handleClearFilters = () => {
    setPropertyType('')
    setCity('')
    setState('')
    setZip('')
    setOwnerName('')
    setScoreRange([0, 100])
    setMarketingListId('')
    setPage(1)
  }

  // Score color helper
  const getScoreColor = (score: number): 'success' | 'warning' | 'error' | 'default' => {
    if (score >= 70) return 'success'
    if (score >= 40) return 'warning'
    if (score > 0) return 'error'
    return 'default'
  }

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return '—'
    try {
      return new Date(dateStr).toLocaleDateString()
    } catch {
      return '—'
    }
  }

  return (
    <Box component="section" aria-labelledby="lead-list-heading" sx={{ px: { xs: 1, sm: 2 } }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Box>
          <Typography variant="h5" id="lead-list-heading" component="h2">
            Leads
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {totalLeads} lead{totalLeads !== 1 ? 's' : ''} found
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<FilterListIcon />}
          onClick={() => setFiltersOpen((prev) => !prev)}
          aria-expanded={filtersOpen}
          aria-controls="lead-filter-panel"
        >
          Filters
        </Button>
      </Box>

      {/* Filter Panel */}
      <Collapse in={filtersOpen}>
        <Paper
          id="lead-filter-panel"
          sx={{ p: { xs: 2, sm: 3 }, mb: 2 }}
          role="search"
          aria-label="Lead filters"
        >
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' },
              gap: 2,
            }}
          >
            <FormControl size="small" fullWidth>
              <InputLabel id="filter-property-type-label">Property Type</InputLabel>
              <Select
                labelId="filter-property-type-label"
                value={propertyType}
                label="Property Type"
                onChange={(e) => setPropertyType(e.target.value)}
              >
                {PROPERTY_TYPE_OPTIONS.map((opt) => (
                  <MenuItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <TextField
              size="small"
              label="City"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              fullWidth
            />

            <TextField
              size="small"
              label="State"
              value={state}
              onChange={(e) => setState(e.target.value)}
              fullWidth
            />

            <TextField
              size="small"
              label="Zip Code"
              value={zip}
              onChange={(e) => setZip(e.target.value)}
              fullWidth
            />

            <TextField
              size="small"
              label="Owner Name"
              value={ownerName}
              onChange={(e) => setOwnerName(e.target.value)}
              fullWidth
            />

            <FormControl size="small" fullWidth>
              <InputLabel id="filter-marketing-list-label">Marketing List</InputLabel>
              <Select
                labelId="filter-marketing-list-label"
                value={marketingListId}
                label="Marketing List"
                onChange={(e) => setMarketingListId(e.target.value as number | '')}
              >
                <MenuItem value="">All</MenuItem>
                {marketingLists.map((ml) => (
                  <MenuItem key={ml.id} value={ml.id}>
                    {ml.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>

          {/* Score range slider */}
          <Box sx={{ mt: 2, px: 1 }}>
            <Typography variant="body2" gutterBottom id="score-range-label">
              Score Range: {scoreRange[0]} – {scoreRange[1]}
            </Typography>
            <Slider
              value={scoreRange}
              onChange={(_e, newValue) => setScoreRange(newValue as [number, number])}
              valueLabelDisplay="auto"
              min={0}
              max={100}
              aria-labelledby="score-range-label"
            />
          </Box>

          <Box sx={{ display: 'flex', gap: 1, mt: 2, justifyContent: 'flex-end' }}>
            <Button
              variant="text"
              startIcon={<ClearIcon />}
              onClick={handleClearFilters}
              aria-label="Clear all filters"
            >
              Clear
            </Button>
            <Button variant="contained" onClick={handleApplyFilters} aria-label="Apply filters">
              Apply
            </Button>
          </Box>
        </Paper>
      </Collapse>

      {/* Error */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} role="alert">
          {error}
        </Alert>
      )}

      {/* Table */}
      <TableContainer
        component={Paper}
        sx={{ overflowX: 'auto' }}
        role="region"
        aria-labelledby="lead-list-heading"
      >
        <Table size="small" aria-label="Leads table">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 200 }} scope="col">
                <TableSortLabel
                  active={sortBy === 'property_street'}
                  direction={sortBy === 'property_street' ? sortOrder : 'asc'}
                  onClick={() => handleSort('property_street')}
                >
                  Address
                </TableSortLabel>
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 140 }} scope="col">
                Owner
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 90 }} align="center" scope="col">
                <TableSortLabel
                  active={sortBy === 'lead_score'}
                  direction={sortBy === 'lead_score' ? sortOrder : 'desc'}
                  onClick={() => handleSort('lead_score')}
                >
                  Score
                </TableSortLabel>
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }} scope="col">
                Property Type
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }} scope="col">
                Location
              </TableCell>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} scope="col">
                <TableSortLabel
                  active={sortBy === 'created_at'}
                  direction={sortBy === 'created_at' ? sortOrder : 'desc'}
                  onClick={() => handleSort('created_at')}
                >
                  Added
                </TableSortLabel>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && leads.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 6 }}>
                  <CircularProgress size={32} aria-label="Loading leads" />
                </TableCell>
              </TableRow>
            ) : leads.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 6 }}>
                  <Typography variant="body2" color="text.secondary">
                    No leads found. Adjust your filters or import leads to get started.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              leads.map((lead) => (
                <TableRow
                  key={lead.id}
                  hover
                  sx={{ cursor: onLeadSelect ? 'pointer' : 'default' }}
                  onClick={() => onLeadSelect?.(lead.id)}
                  role={onLeadSelect ? 'button' : undefined}
                  tabIndex={onLeadSelect ? 0 : undefined}
                  onKeyDown={(e) => {
                    if (onLeadSelect && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault()
                      onLeadSelect(lead.id)
                    }
                  }}
                  aria-label={`Lead: ${lead.property_street}, Owner: ${lead.owner_first_name} ${lead.owner_last_name}, Score: ${lead.lead_score}`}
                >
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {[lead.property_street, lead.property_city, lead.property_state, lead.property_zip].filter(Boolean).join(', ')}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{lead.owner_first_name} {lead.owner_last_name}</Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Chip
                      label={lead.lead_score.toFixed(1)}
                      size="small"
                      color={getScoreColor(lead.lead_score)}
                      aria-label={`Score ${lead.lead_score.toFixed(1)}`}
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{lead.property_type || '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {[lead.mailing_city, lead.mailing_state, lead.mailing_zip]
                        .filter(Boolean)
                        .join(', ') || '—'}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">{formatDate(lead.created_at)}</Typography>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Pagination */}
      {totalPages > 1 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
          <Pagination
            count={totalPages}
            page={page}
            onChange={(_e, value) => setPage(value)}
            color="primary"
            showFirstButton
            showLastButton
            aria-label="Lead list pagination"
          />
        </Box>
      )}
    </Box>
  )
}
