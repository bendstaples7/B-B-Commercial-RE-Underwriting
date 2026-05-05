import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Box,
  Paper,
  Typography,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Button,
  Alert,
  Collapse,
  Slider,
  Pagination,
} from '@mui/material'
import FilterListIcon from '@mui/icons-material/FilterList'
import ClearIcon from '@mui/icons-material/Clear'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, ColDef } from 'ag-grid-community'
import type {
  LeadSummary,
  LeadListFilters,
  LeadListResponse,
  MarketingList,
} from '@/types'
import { leadService } from '@/services/leadApi'

// Register AG Grid community modules
ModuleRegistry.registerModules([AllCommunityModule])

/** Props accepted by LeadListPage. */
export interface LeadListPageProps {
  onLeadSelect?: (leadId: number) => void
}

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

/** AG Grid column definitions */
const COLUMN_DEFS: ColDef<LeadSummary>[] = [
  { field: 'property_street', headerName: 'Property Street', width: 200, sortable: true },
  { field: 'property_city', headerName: 'Property City', width: 130 },
  { field: 'property_state', headerName: 'State', width: 70 },
  { field: 'property_zip', headerName: 'Zip', width: 80 },
  { field: 'property_type', headerName: 'Property Type', width: 120 },
  { field: 'lead_category', headerName: 'Category', width: 110 },
  { field: 'bedrooms', headerName: 'Beds', width: 65 },
  { field: 'bathrooms', headerName: 'Baths', width: 65 },
  { field: 'square_footage', headerName: 'Sq Ft', width: 80 },
  { field: 'lot_size', headerName: 'Lot Size', width: 85 },
  { field: 'year_built', headerName: 'Year Built', width: 90 },
  { field: 'units', headerName: 'Units', width: 65 },
  { field: 'units_allowed', headerName: 'Units Allowed', width: 110 },
  { field: 'zoning', headerName: 'Zoning', width: 90 },
  { field: 'county_assessor_pin', headerName: 'Assessor PIN', width: 130 },
  { field: 'tax_bill_2021', headerName: 'Tax Bill 2021', width: 110 },
  { field: 'most_recent_sale', headerName: 'Most Recent Sale', width: 140 },
  { field: 'owner_first_name', headerName: 'Owner First', width: 120 },
  { field: 'owner_last_name', headerName: 'Owner Last', width: 120 },
  { field: 'owner_2_first_name', headerName: 'Owner 2 First', width: 120 },
  { field: 'owner_2_last_name', headerName: 'Owner 2 Last', width: 120 },
  { field: 'ownership_type', headerName: 'Ownership Type', width: 130 },
  { field: 'acquisition_date', headerName: 'Acquisition Date', width: 130 },
  { field: 'phone_1', headerName: 'Phone 1', width: 130 },
  { field: 'phone_2', headerName: 'Phone 2', width: 130 },
  { field: 'phone_3', headerName: 'Phone 3', width: 130 },
  { field: 'phone_4', headerName: 'Phone 4', width: 130 },
  { field: 'phone_5', headerName: 'Phone 5', width: 130 },
  { field: 'phone_6', headerName: 'Phone 6', width: 130 },
  { field: 'phone_7', headerName: 'Phone 7', width: 130 },
  { field: 'email_1', headerName: 'Email 1', width: 190 },
  { field: 'email_2', headerName: 'Email 2', width: 190 },
  { field: 'email_3', headerName: 'Email 3', width: 190 },
  { field: 'email_4', headerName: 'Email 4', width: 190 },
  { field: 'email_5', headerName: 'Email 5', width: 190 },
  { field: 'socials', headerName: 'Socials', width: 150 },
  { field: 'mailing_address', headerName: 'Mailing Address', width: 200 },
  { field: 'mailing_city', headerName: 'Mailing City', width: 130 },
  { field: 'mailing_state', headerName: 'Mailing State', width: 90 },
  { field: 'mailing_zip', headerName: 'Mailing Zip', width: 90 },
  { field: 'address_2', headerName: 'Address 2', width: 150 },
  { field: 'returned_addresses', headerName: 'Returned Addresses', width: 160 },
  { field: 'source', headerName: 'Source', width: 110 },
  { field: 'date_identified', headerName: 'Date Identified', width: 120 },
  { field: 'notes', headerName: 'Notes', width: 220 },
  { field: 'needs_skip_trace', headerName: 'Needs Skip Trace', width: 130 },
  { field: 'skip_tracer', headerName: 'Skip Tracer', width: 110 },
  { field: 'date_skip_traced', headerName: 'Date Skip Traced', width: 130 },
  { field: 'date_added_to_hubspot', headerName: 'Added to HubSpot', width: 130 },
  { field: 'up_next_to_mail', headerName: 'Up Next to Mail', width: 120 },
  { field: 'lead_score', headerName: 'Score', width: 80, sortable: true },
  { field: 'created_at', headerName: 'Added', width: 110, sortable: true },
]

export const LeadListPage: React.FC<LeadListPageProps> = ({ onLeadSelect }) => {
  const [leads, setLeads] = useState<LeadSummary[]>([])
  const [totalLeads, setTotalLeads] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filter state
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [leadCategory, setLeadCategory] = useState<'residential' | 'commercial' | ''>('')
  const [propertyType, setPropertyType] = useState('')
  const [city, setCity] = useState('')
  const [state, setState] = useState('')
  const [zip, setZip] = useState('')
  const [ownerName, setOwnerName] = useState('')
  const [scoreRange, setScoreRange] = useState<[number, number]>([0, 100])
  const [marketingListId, setMarketingListId] = useState<number | ''>('')

  // Pagination & sorting
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState<string>('lead_score')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  // Marketing lists for filter dropdown
  const [marketingLists, setMarketingLists] = useState<MarketingList[]>([])

  // AG Grid default column settings
  const defaultColDef = useMemo<ColDef>(() => ({
    sortable: false,
    resizable: true,
    filter: false,
  }), [])

  const buildFilters = useCallback((): LeadListFilters => {
    const filters: LeadListFilters = {
      page,
      per_page: PER_PAGE,
      sort_by: (sortBy === 'lead_score' || sortBy === 'created_at' || sortBy === 'property_street') ? sortBy : 'lead_score',
      sort_order: sortOrder,
    }
    if (leadCategory) filters.lead_category = leadCategory
    if (propertyType) filters.property_type = propertyType
    if (city.trim()) filters.city = city.trim()
    if (state.trim()) filters.state = state.trim()
    if (zip.trim()) filters.zip = zip.trim()
    if (ownerName.trim()) filters.owner_name = ownerName.trim()
    if (scoreRange[0] > 0) filters.score_min = scoreRange[0]
    if (scoreRange[1] < 100) filters.score_max = scoreRange[1]
    if (marketingListId !== '') filters.marketing_list_id = marketingListId as number
    return filters
  }, [page, sortBy, sortOrder, leadCategory, propertyType, city, state, zip, ownerName, scoreRange, marketingListId])

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

  useEffect(() => {
    const loadMarketingLists = async () => {
      try {
        const response = await leadService.listMarketingLists({ per_page: 100 })
        setMarketingLists(response.lists)
      } catch { /* non-critical */ }
    }
    loadMarketingLists()
  }, [])

  useEffect(() => { fetchLeads() }, [fetchLeads])

  const handleApplyFilters = () => { setPage(1) }

  const handleSortChanged = useCallback((event: any) => {
    const columnState = event.api.getColumnState()
    const sorted = columnState.find((c: any) => c.sort)
    if (sorted) {
      setSortBy(sorted.colId)
      setSortOrder(sorted.sort as 'asc' | 'desc')
    } else {
      setSortBy('lead_score')
      setSortOrder('desc')
    }
    setPage(1)
  }, [])

  const handleClearFilters = () => {
    setLeadCategory('')
    setPropertyType('')
    setCity('')
    setState('')
    setZip('')
    setOwnerName('')
    setScoreRange([0, 100])
    setMarketingListId('')
    setPage(1)
  }

  return (
    <Box component="section" aria-labelledby="lead-list-heading" sx={{ px: { xs: 1, sm: 2 }, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Box>
          <Typography variant="h5" id="lead-list-heading" component="h2">Leads</Typography>
          <Typography variant="body2" color="text.secondary">
            {totalLeads} lead{totalLeads !== 1 ? 's' : ''} found
          </Typography>
        </Box>
        <Button variant="outlined" startIcon={<FilterListIcon />} onClick={() => setFiltersOpen((p) => !p)} aria-expanded={filtersOpen}>
          Filters
        </Button>
      </Box>

      <Collapse in={filtersOpen}>
        <Paper sx={{ p: { xs: 2, sm: 3 }, mb: 2 }} role="search" aria-label="Lead filters">
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr', md: '1fr 1fr 1fr' }, gap: 2 }}>
            <FormControl size="small" fullWidth>
              <InputLabel id="filter-lead-category-label">Lead Category</InputLabel>
              <Select labelId="filter-lead-category-label" value={leadCategory} label="Lead Category" onChange={(e) => setLeadCategory(e.target.value as any)}>
                <MenuItem value="">All</MenuItem>
                <MenuItem value="residential">Residential</MenuItem>
                <MenuItem value="commercial">Commercial</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small" fullWidth>
              <InputLabel id="filter-property-type-label">Property Type</InputLabel>
              <Select labelId="filter-property-type-label" value={propertyType} label="Property Type" onChange={(e) => setPropertyType(e.target.value)}>
                {PROPERTY_TYPE_OPTIONS.map((opt) => (<MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>))}
              </Select>
            </FormControl>
            <TextField size="small" label="City" value={city} onChange={(e) => setCity(e.target.value)} fullWidth />
            <TextField size="small" label="State" value={state} onChange={(e) => setState(e.target.value)} fullWidth />
            <TextField size="small" label="Zip Code" value={zip} onChange={(e) => setZip(e.target.value)} fullWidth />
            <TextField size="small" label="Owner Name" value={ownerName} onChange={(e) => setOwnerName(e.target.value)} fullWidth />
            <FormControl size="small" fullWidth>
              <InputLabel id="filter-marketing-list-label">Marketing List</InputLabel>
              <Select labelId="filter-marketing-list-label" value={marketingListId} label="Marketing List" onChange={(e) => setMarketingListId(e.target.value as number | '')}>
                <MenuItem value="">All</MenuItem>
                {marketingLists.map((ml) => (<MenuItem key={ml.id} value={ml.id}>{ml.name}</MenuItem>))}
              </Select>
            </FormControl>
          </Box>
          <Box sx={{ mt: 2, px: 1 }}>
            <Typography variant="body2" gutterBottom>Score Range: {scoreRange[0]} – {scoreRange[1]}</Typography>
            <Slider value={scoreRange} onChange={(_e, v) => setScoreRange(v as [number, number])} valueLabelDisplay="auto" min={0} max={100} />
          </Box>
          <Box sx={{ display: 'flex', gap: 1, mt: 2, justifyContent: 'flex-end' }}>
            <Button variant="text" startIcon={<ClearIcon />} onClick={handleClearFilters}>Clear</Button>
            <Button variant="contained" onClick={handleApplyFilters}>Apply</Button>
          </Box>
        </Paper>
      </Collapse>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {/* AG Grid — scrollable, columns draggable to reorder, resizable */}
      <Paper sx={{ flex: 1, minHeight: 500, width: '100%' }}>
        <div style={{ height: '100%', width: '100%', minHeight: 500 }}>
          <AgGridReact<LeadSummary>
            rowData={leads}
            columnDefs={COLUMN_DEFS}
            defaultColDef={defaultColDef}
            loading={loading}
            rowSelection="single"
            onRowClicked={(e) => { if (e.data) onLeadSelect?.(e.data.id) }}
            onSortChanged={handleSortChanged}
            suppressMovableColumns={false}
            animateRows={true}
          />
        </div>
      </Paper>

      {totalPages > 1 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
          <Pagination count={totalPages} page={page} onChange={(_e, v) => setPage(v)} color="primary" showFirstButton showLastButton />
        </Box>
      )}
    </Box>
  )
}
