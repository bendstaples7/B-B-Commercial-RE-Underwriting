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
  Tabs,
  Tab,
} from '@mui/material'
import FilterListIcon from '@mui/icons-material/FilterList'
import ClearIcon from '@mui/icons-material/Clear'
import { AgGridReact } from 'ag-grid-react'
import { AllCommunityModule, ModuleRegistry, ColDef } from 'ag-grid-community'
import type {
  LeadSummary,
  LeadListFilters,
  LeadListResponse,
  LeadScoreRecord,
  LeadScoreResponse,
  MarketingList,
  CondoFilterParams,
} from '@/types'
import { leadService } from '@/services/leadApi'
import { leadScoreService } from '@/services/api'
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { CondoResultsTable } from '@/components/CondoResultsTable'
import { CondoDetailView } from '@/components/CondoDetailView'
import { condoFilterService } from '@/services/condoFilterApi'
import { LeadScoreBadge } from '@/components/LeadScoreBadge'
import {
  ScoreFilterPanel,
  EMPTY_SCORE_FILTERS,
  type ScoreFilters,
} from '@/components/ScoreFilterPanel'
import { RecalculateButton } from '@/components/RecalculateButton'
import { ScoreLegend } from '@/components/ScoreLegend'

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

/**
 * Row shape used by the AG Grid table. Extends LeadSummary with the
 * most-recent LeadScoreRecord fields, flattened so AG Grid `valueGetter`s
 * can be avoided. `latest_score` is the raw record (or null when the lead
 * has never been scored).
 */
export interface LeadRow extends LeadSummary {
  latest_score: LeadScoreRecord | null
  total_score: number | null
  score_tier: LeadScoreRecord['score_tier'] | null
  data_quality_score: number | null
  recommended_action: LeadScoreRecord['recommended_action'] | null
  top_signal: string | null
  missing_data_count: number | null
}

/** Human-readable labels for the recommended-action values. */
const ACTION_LABELS: Record<NonNullable<LeadRow['recommended_action']>, string> = {
  review_now: 'Review Now',
  enrich_data: 'Enrich Data',
  mail_ready: 'Mail Ready',
  call_ready: 'Call Ready',
  valuation_needed: 'Valuation Needed',
  suppress: 'Suppress',
  nurture: 'Nurture',
  needs_manual_review: 'Needs Manual Review',
}

/** Convert a snake_case dimension key to a human-readable label. */
function humanizeDimension(key: string): string {
  if (!key) return ''
  return key
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ')
}

/**
 * Tier-badge cell renderer. AG Grid passes the row via `params.data`; we
 * render `LeadScoreBadge`, which handles the "Not scored" case when tier
 * is null.
 */
const TierCellRenderer: React.FC<{ data?: LeadRow }> = ({ data }) => (
  <LeadScoreBadge tier={data?.score_tier ?? null} size="small" />
)

/** AG Grid column definitions */
const COLUMN_DEFS: ColDef<LeadRow>[] = [
  // ---- Score columns (task 8.1 / Req 10.1, 10.3, 10.4) ----
  {
    field: 'score_tier',
    headerName: 'Tier',
    width: 90,
    sortable: true,
    pinned: 'left',
    cellRenderer: TierCellRenderer,
  },
  {
    field: 'total_score',
    headerName: 'Score',
    width: 85,
    sortable: true,
    pinned: 'left',
    valueFormatter: (p) => (p.value == null ? '—' : String(Math.round(p.value))),
  },
  {
    field: 'data_quality_score',
    headerName: 'Data Quality',
    width: 110,
    sortable: true,
    valueFormatter: (p) => (p.value == null ? '—' : String(Math.round(p.value))),
  },
  {
    field: 'recommended_action',
    headerName: 'Recommended',
    width: 160,
    sortable: true,
    valueFormatter: (p) =>
      p.value == null ? '—' : ACTION_LABELS[p.value as keyof typeof ACTION_LABELS] ?? p.value,
  },
  {
    field: 'top_signal',
    headerName: 'Top Signal',
    width: 180,
    valueFormatter: (p) => (p.value == null ? '—' : p.value),
  },
  {
    field: 'missing_data_count',
    headerName: 'Missing Data',
    width: 110,
    sortable: true,
    valueFormatter: (p) => (p.value == null ? '—' : String(p.value)),
  },

  // ---- Existing columns ----
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
  const queryClient = useQueryClient()
  const [leads, setLeads] = useState<LeadSummary[]>([])
  const [totalLeads, setTotalLeads] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Tab state
  const [activeTab, setActiveTab] = useState(0)

  // Condo filter state
  const [condoFilters, setCondoFilters] = useState<CondoFilterParams>({ page: 1, per_page: 20 })
  const [condoDetailId, setCondoDetailId] = useState<number | null>(null)
  const [condoDetailOpen, setCondoDetailOpen] = useState(false)
  const [analysisRunning, setAnalysisRunning] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [analysisSuccess, setAnalysisSuccess] = useState<string | null>(null)

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

  // Score filter state (task 8.1 / Req 13.1 – 13.7)
  const [scoreFilters, setScoreFilters] = useState<ScoreFilters>(EMPTY_SCORE_FILTERS)

  // Fetch the latest score for each visible lead in parallel. Uses
  // `useQueries` so React Query caches each response under its own key
  // and repeat renders / recalculations refresh only what changed.
  const scoreQueries = useQueries({
    queries: leads.map((lead) => ({
      queryKey: ['leadScore', lead.id] as const,
      queryFn: async (): Promise<LeadScoreResponse> => {
        const response = await leadScoreService.getLeadScore(lead.id)
        return response.data
      },
      staleTime: 60_000,
      retry: false,
      refetchOnWindowFocus: false,
    })),
  })

  /**
   * Merge each lead with its latest LeadScoreRecord and flatten the
   * score fields into the row. Leads whose score fetch is still in-flight
   * (or failed) fall through with null score fields, which the column
   * renderers handle via "Not scored" / "—".
   */
  const rows = useMemo<LeadRow[]>(() => {
    return leads.map((lead, idx) => {
      const query = scoreQueries[idx]
      const latest: LeadScoreRecord | null =
        (query?.data?.latest as LeadScoreRecord | null | undefined) ?? null

      if (!latest) {
        return {
          ...lead,
          latest_score: null,
          total_score: null,
          score_tier: null,
          data_quality_score: null,
          recommended_action: null,
          top_signal: null,
          missing_data_count: null,
        }
      }

      const topSignalKey = latest.top_signals?.[0]?.dimension
      return {
        ...lead,
        latest_score: latest,
        total_score: latest.total_score,
        score_tier: latest.score_tier,
        data_quality_score: latest.data_quality_score,
        recommended_action: latest.recommended_action,
        top_signal: topSignalKey ? humanizeDimension(topSignalKey) : null,
        missing_data_count: Array.isArray(latest.missing_data)
          ? latest.missing_data.length
          : 0,
      }
    })
    // scoreQueries is a new array each render, so depend on its data
    // payloads to avoid tight re-render loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leads, scoreQueries.map((q) => q.data).join('|')])

  /**
   * Apply score filters (task 8.1 / Req 13.1 – 13.7) to the current page
   * of rows. Score filters operate client-side because the backend
   * `GET /api/leads/` endpoint does not currently support filtering by
   * LeadScoreRecord fields.
   */
  const displayedRows = useMemo<LeadRow[]>(() => {
    const {
      tiers,
      actions,
      lowDataQuality,
      missingPin,
      missingOwnerMailing,
      condoNeedsReview,
      condoLikelyCondo,
    } = scoreFilters

    const anyFilterActive =
      tiers.length > 0 ||
      actions.length > 0 ||
      lowDataQuality ||
      missingPin ||
      missingOwnerMailing ||
      condoNeedsReview ||
      condoLikelyCondo

    if (!anyFilterActive) return rows

    return rows.filter((row) => {
      const score = row.latest_score
      if (tiers.length > 0 && (!score || !tiers.includes(score.score_tier))) return false
      if (actions.length > 0 && (!score || !actions.includes(score.recommended_action)))
        return false
      if (lowDataQuality && (!score || score.data_quality_score >= 70)) return false
      if (missingPin && !(score?.missing_data?.includes('pin') ?? false)) return false
      if (
        missingOwnerMailing &&
        !(score?.missing_data?.includes('owner_mailing_address') ?? false)
      )
        return false
      // Condo-risk filters check the score's recommended_action since the
      // DeterministicScoringEngine maps these condo states to dedicated
      // actions (see spec Req 6.8, 6.9).
      if (
        condoNeedsReview &&
        !(score?.recommended_action === 'needs_manual_review')
      )
        return false
      if (condoLikelyCondo && !(score?.recommended_action === 'suppress')) return false
      return true
    })
  }, [rows, scoreFilters])

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
    setScoreFilters(EMPTY_SCORE_FILTERS)
    setPage(1)
  }

  // Condo filter handlers
  const handleRunAnalysis = async () => {
    setAnalysisRunning(true)
    setAnalysisError(null)
    setAnalysisSuccess(null)
    try {
      const summary = await condoFilterService.runAnalysis()
      queryClient.invalidateQueries({ queryKey: ['condoFilterResults'] })
      setAnalysisSuccess(`Analysis complete: ${summary.total_groups} address groups, ${summary.total_properties} properties processed.`)
    } catch (err: any) {
      setAnalysisError(err.message || 'Failed to run analysis.')
    } finally {
      setAnalysisRunning(false)
    }
  }

  const handleExportCsv = async () => {
    try {
      const blob = await condoFilterService.exportCsv(condoFilters)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'condo_filter_results.csv'
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* non-critical */ }
  }

  return (
    <Box component="section" aria-labelledby="lead-list-heading" sx={{ px: { xs: 1, sm: 2 }, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h5" id="lead-list-heading" component="h2">Leads</Typography>
      </Box>

      <Tabs value={activeTab} onChange={(_e, v) => setActiveTab(v)} sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="All Leads" />
        {/* Disabled until public records + skip tracing provide complete data */}
        <Tab label="Condo Analysis" disabled />
      </Tabs>

      {/* Tab 0: All Leads */}
      {activeTab === 0 && (
        <>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="body2" color="text.secondary">
              {totalLeads} lead{totalLeads !== 1 ? 's' : ''} found
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <RecalculateButton mode="bulk-all" />
              <Button variant="outlined" startIcon={<FilterListIcon />} onClick={() => setFiltersOpen((p) => !p)} aria-expanded={filtersOpen}>
                Filters
              </Button>
            </Box>
          </Box>

          {/* Column legend — collapsible reference for Tier/Score/Quality/
              Action/Top Signal/Missing columns. */}
          <Box sx={{ mb: 2 }}>
            <ScoreLegend />
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

            {/* Score-based filter panel (task 8.1 / Req 13.1 – 13.7).
                Operates client-side over the current page of rows. */}
            <Box sx={{ mb: 2 }}>
              <ScoreFilterPanel filters={scoreFilters} onChange={setScoreFilters} />
            </Box>
          </Collapse>

          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

          <Paper sx={{ flex: 1, minHeight: 500, width: '100%' }}>
            <div style={{ height: '100%', width: '100%', minHeight: 500 }}>
              <AgGridReact<LeadRow>
                rowData={displayedRows}
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
        </>
      )}

      {/* Tab 1: Condo Analysis
          SHELVED — Hidden until public records + skip tracing are connected.
          The classification engine needs populated county_assessor_pin and owner
          names to produce useful results. Currently everything shows "needs_review"
          because those fields are mostly null. Re-enable this tab once data is complete.
          See: backend/app/services/condo_filter_service.py for full details. */}
      {activeTab === 1 && (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center' }}>
            <Button
              variant="contained"
              onClick={handleRunAnalysis}
              disabled={analysisRunning}
            >
              {analysisRunning ? 'Running Analysis...' : 'Run Analysis'}
            </Button>
            <Button variant="outlined" onClick={handleExportCsv}>
              Export CSV
            </Button>
          </Box>

          {analysisError && <Alert severity="error" sx={{ mb: 2 }}>{analysisError}</Alert>}
          {analysisSuccess && <Alert severity="success" sx={{ mb: 2 }}>{analysisSuccess}</Alert>}

          <CondoResultsTable
            filters={condoFilters}
            onFiltersChange={setCondoFilters}
            onRowClick={(analysis) => { setCondoDetailId(analysis.id); setCondoDetailOpen(true) }}
          />

          <CondoDetailView
            analysisId={condoDetailId}
            open={condoDetailOpen}
            onClose={() => { setCondoDetailOpen(false); setCondoDetailId(null) }}
          />
        </Box>
      )}
    </Box>
  )
}
