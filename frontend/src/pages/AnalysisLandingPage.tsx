/**
 * AnalysisLandingPage — unified entry point for both single-family ARV
 * and multifamily pro-forma workflows.
 *
 * Shows existing ARV sessions and multifamily deals side-by-side, plus a
 * "New Analysis" dialog that routes to the correct workflow based on unit count.
 */
import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Paper,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import HomeWorkIcon from '@mui/icons-material/HomeWork'
import ApartmentIcon from '@mui/icons-material/Apartment'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import usePlacesAutocomplete from 'use-places-autocomplete'
import { multifamilyService } from '@/services/api'
import type { DealCreatePayload, DealSummary } from '@/types'
import { useGoogleMapsLoaded } from '@/App'

// ---------------------------------------------------------------------------
// Helpers
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

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function dealStatusColor(status: string): 'default' | 'primary' | 'success' | 'warning' {
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

/** Determine analysis type from unit count. */
type AnalysisType = 'single-family' | 'multifamily'

function detectType(unitCount: number | null): AnalysisType | null {
  if (unitCount === null || unitCount === 0) return null
  return unitCount >= 5 ? 'multifamily' : 'single-family'
}

// ---------------------------------------------------------------------------
// New Analysis Dialog
// ---------------------------------------------------------------------------

interface NewAnalysisDialogProps {
  open: boolean
  onClose: () => void
}

function NewAnalysisDialog({ open, onClose }: NewAnalysisDialogProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const suggestionsRef = useRef<HTMLUListElement>(null)
  const mapsLoaded = useGoogleMapsLoaded()

  const [unitCount, setUnitCount] = useState<number | ''>('')
  const [overrideType, setOverrideType] = useState<AnalysisType | null>(null)
  const [addressError, setAddressError] = useState('')
  const [resolvedCoords, setResolvedCoords] = useState<{ lat: number; lng: number } | undefined>()

  const {
    ready,
    value: address,
    suggestions: { status, data },
    setValue: setAddress,
    clearSuggestions,
    init,
  } = usePlacesAutocomplete({
    requestOptions: { componentRestrictions: { country: 'us' } },
    debounce: 300,
    // Don't try to initialize until the Maps API is loaded
    initOnMount: false,
  })

  // Initialize the autocomplete service as soon as the Maps API is ready
  useEffect(() => {
    if (mapsLoaded) init()
  }, [mapsLoaded, init])

  const detected = detectType(typeof unitCount === 'number' ? unitCount : null)
  const effectiveType: AnalysisType | null = overrideType ?? detected

  const createDealMutation = useMutation({
    mutationFn: (payload: DealCreatePayload) => multifamilyService.createDeal(payload),
    onSuccess: (deal) => {
      queryClient.invalidateQueries({ queryKey: ['multifamily', 'deals'] })
      handleClose()
      navigate(`/multifamily/deals/${deal.id}`)
    },
  })

  // Create a single-family ARV session and navigate to it
  const createSingleFamilyMutation = useMutation({
    mutationFn: async ({ address, coords }: { address: string; coords?: { lat: number; lng: number } }) => {
      const userId = localStorage.getItem('user_id') || 'default'
      const response = await fetch('/api/analysis/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          address,
          user_id: userId,
          ...(coords ? { latitude: coords.lat, longitude: coords.lng } : {}),
        }),
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err?.error?.message || err?.message || 'Failed to start analysis')
      }
      return response.json()
    },
    onSuccess: (data) => {
      // Seed the React Query cache with the start response so AnalysisRoute
      // can immediately show the pre-fetched Cook County property facts without
      // a second round-trip to the backend.
      queryClient.setQueryData(['session', data.session_id], {
        session_id: data.session_id,
        current_step: 'PROPERTY_FACTS',
        loading: false,
        subject_property: data.property_facts ?? null,
        step_results: {},
        completed_steps: [],
      })
      handleClose()
      navigate(`/analysis/arv/${data.session_id}`)
    },
  })

  const handleClose = () => {
    if (createDealMutation.isPending || createSingleFamilyMutation.isPending) return
    setAddress('')
    setUnitCount('')
    setOverrideType(null)
    setAddressError('')
    setResolvedCoords(undefined)
    clearSuggestions()
    createDealMutation.reset()
    createSingleFamilyMutation.reset()
    onClose()
  }

  const handleSelect = (description: string, placeId: string) => {
    setAddress(description, false)
    clearSuggestions()
    setAddressError('')
    // Use PlacesService.getDetails to get coordinates from the place_id.
    // This uses the Places API (already enabled) — no Geocoding API needed.
    try {
      const service = new (window as any).google.maps.places.PlacesService(
        document.createElement('div')
      )
      service.getDetails(
        { placeId, fields: ['geometry'] },
        (result: any, status: any) => {
          if (
            status === (window as any).google.maps.places.PlacesServiceStatus.OK &&
            result?.geometry?.location
          ) {
            setResolvedCoords({
              lat: result.geometry.location.lat(),
              lng: result.geometry.location.lng(),
            })
          }
        }
      )
    } catch {
      setResolvedCoords(undefined)
    }
  }

  const handleStart = () => {
    if (!address.trim()) {
      setAddressError('Property address is required')
      return
    }
    setAddressError('')

    // Use coords resolved from the Places suggestion selection.
    // If the user typed manually without selecting a suggestion, coords will be
    // undefined and the backend will fall back to Cook County parcel coordinates.
    const coords = resolvedCoords

    const type = effectiveType ?? (typeof unitCount === 'number' && unitCount >= 5 ? 'multifamily' : 'single-family')

    if (type === 'multifamily') {
      createDealMutation.mutate({
        property_address: address.trim(),
        unit_count: typeof unitCount === 'number' ? unitCount : 5,
        purchase_price: 0,
        close_date: new Date().toISOString().split('T')[0],
      })
    } else {
      createSingleFamilyMutation.mutate({ address: address.trim(), coords })
    }
  }

  const units = typeof unitCount === 'number' ? unitCount : null

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="sm"
      fullWidth
      aria-labelledby="new-analysis-dialog-title"
    >
      <DialogTitle id="new-analysis-dialog-title">New Analysis</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {(createDealMutation.isError || createSingleFamilyMutation.isError) && (
            <Alert severity="error">
              {(createDealMutation.error as Error)?.message ??
               (createSingleFamilyMutation.error as Error)?.message ??
               'Failed to start analysis'}
            </Alert>
          )}

          {/* Address field with Places Autocomplete */}
          <Box sx={{ position: 'relative' }}>
            <TextField
              label="Property Address"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value)
                setResolvedCoords(undefined)
                if (e.target.value.trim()) setAddressError('')
              }}
              onKeyDown={(e) => { if (e.key === 'Escape') clearSuggestions() }}
              error={!!addressError}
              helperText={addressError}
              required
              fullWidth
              autoFocus
              autoComplete="off"
              placeholder="123 Main St, Chicago, IL 60601"
              inputProps={{
                'aria-label': 'Property address',
                'aria-autocomplete': 'list',
                'aria-controls': status === 'OK' ? 'dialog-address-suggestions' : undefined,
                'aria-expanded': status === 'OK',
              }}
            />
            {status === 'OK' && data.length > 0 && (
              <List
                id="dialog-address-suggestions"
                ref={suggestionsRef}
                role="listbox"
                aria-label="Address suggestions"
                sx={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  zIndex: 1400,
                  bgcolor: 'background.paper',
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  boxShadow: 3,
                  mt: 0.5,
                  maxHeight: 240,
                  overflowY: 'auto',
                  p: 0,
                }}
              >
                {data.map(({ place_id, description }) => (
                  <ListItem key={place_id} disablePadding>
                    <ListItemButton
                      role="option"
                      onClick={() => handleSelect(description, place_id)}
                      aria-label={description}
                      sx={{ py: 1 }}
                    >
                      <ListItemText
                        primary={description}
                        primaryTypographyProps={{ variant: 'body2' }}
                      />
                    </ListItemButton>
                  </ListItem>
                ))}
              </List>
            )}
          </Box>

          <TextField
            label="Unit Count"
            type="number"
            value={unitCount}
            onChange={(e) => {
              const val = e.target.value === '' ? '' : parseInt(e.target.value, 10)
              setUnitCount(val === '' ? '' : isNaN(val as number) ? '' : val as number)
              setOverrideType(null) // reset override when units change
            }}
            helperText="Enter number of units to auto-detect analysis type"
            fullWidth
            inputProps={{ min: 1, 'aria-label': 'Unit count' }}
          />

          {/* Detected type chip with override */}
          {units !== null && units > 0 && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <Chip
                icon={effectiveType === 'multifamily' ? <ApartmentIcon /> : <HomeWorkIcon />}
                label={
                  effectiveType === 'multifamily'
                    ? `Detected: Multifamily (${units} units)`
                    : `Detected: Single-Family (${units} unit${units !== 1 ? 's' : ''})`
                }
                color={effectiveType === 'multifamily' ? 'primary' : 'success'}
                size="small"
              />
              <Tooltip title="Override the auto-detected analysis type">
                <Button
                  size="small"
                  variant="text"
                  startIcon={<InfoOutlinedIcon fontSize="small" />}
                  onClick={() =>
                    setOverrideType(
                      effectiveType === 'multifamily' ? 'single-family' : 'multifamily',
                    )
                  }
                  sx={{ textTransform: 'none', fontSize: '0.75rem' }}
                >
                  {effectiveType === 'multifamily'
                    ? 'Switch to Single-Family?'
                    : 'Switch to Multifamily?'}
                </Button>
              </Tooltip>
            </Box>
          )}

          {/* Manual type selector when no units entered */}
          {(units === null || units === 0) && (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: 'block' }}>
                Or select analysis type manually:
              </Typography>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button
                  variant={effectiveType === 'single-family' ? 'contained' : 'outlined'}
                  size="small"
                  startIcon={<HomeWorkIcon />}
                  onClick={() => setOverrideType('single-family')}
                  aria-pressed={effectiveType === 'single-family'}
                >
                  Single-Family
                </Button>
                <Button
                  variant={effectiveType === 'multifamily' ? 'contained' : 'outlined'}
                  size="small"
                  startIcon={<ApartmentIcon />}
                  onClick={() => setOverrideType('multifamily')}
                  aria-pressed={effectiveType === 'multifamily'}
                >
                  Multifamily
                </Button>
              </Box>
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={createDealMutation.isPending || createSingleFamilyMutation.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleStart}
          disabled={createDealMutation.isPending || createSingleFamilyMutation.isPending || !address.trim()}
          startIcon={(createDealMutation.isPending || createSingleFamilyMutation.isPending) ? <CircularProgress size={16} /> : undefined}
          aria-label="Start analysis"
        >
          {(createDealMutation.isPending || createSingleFamilyMutation.isPending) ? 'Starting…' : 'Start Analysis'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Single-Family sessions panel (placeholder — ARV sessions list)
// ---------------------------------------------------------------------------

function SingleFamilyPanel() {
  // The ARV session list is not yet backed by a list API, so we show a
  // placeholder that directs users to start a new analysis.
  return (
    <Box sx={{ py: 4, textAlign: 'center' }}>
      <HomeWorkIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
      <Typography variant="body1" color="text.secondary" gutterBottom>
        No single-family analyses yet.
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Click "New Analysis" above and enter a property address to get started.
      </Typography>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Multifamily deals panel
// ---------------------------------------------------------------------------

function MultifamilyPanel() {
  const navigate = useNavigate()

  const { data: deals, isLoading, isError, error } = useQuery({
    queryKey: ['multifamily', 'deals'],
    queryFn: () => multifamilyService.listDeals(),
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading deals" />
      </Box>
    )
  }

  if (isError) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        {(error as Error)?.message ?? 'Failed to load deals'}
      </Alert>
    )
  }

  if (!deals || deals.length === 0) {
    return (
      <Box sx={{ py: 4, textAlign: 'center' }}>
        <ApartmentIcon sx={{ fontSize: 48, color: 'text.disabled', mb: 1 }} />
        <Typography variant="body1" color="text.secondary" gutterBottom>
          No multifamily deals yet.
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Click "New Analysis" above and enter a 5+ unit property to create a deal.
        </Typography>
      </Box>
    )
  }

  return (
    <TableContainer component={Paper} variant="outlined">
      <Table aria-label="Multifamily deals">
        <TableHead>
          <TableRow>
            <TableCell>Address</TableCell>
            <TableCell align="right">Units</TableCell>
            <TableCell align="right">Purchase Price</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Updated</TableCell>
            <TableCell align="center">Open</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {deals.map((deal: DealSummary) => (
            <TableRow
              key={deal.id}
              hover
              sx={{ cursor: 'pointer' }}
              onClick={() => navigate(`/multifamily/deals/${deal.id}`)}
            >
              <TableCell>
                <Typography variant="body2" fontWeight={500}>
                  {deal.property_address}
                </Typography>
              </TableCell>
              <TableCell align="right">{deal.unit_count}</TableCell>
              <TableCell align="right">{formatCurrency(deal.purchase_price)}</TableCell>
              <TableCell>
                <Chip
                  label={deal.status ?? 'draft'}
                  color={dealStatusColor(deal.status)}
                  size="small"
                />
              </TableCell>
              <TableCell>{formatDate(deal.updated_at)}</TableCell>
              <TableCell align="center">
                <Tooltip title="Open deal">
                  <Button
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/multifamily/deals/${deal.id}`)
                    }}
                    aria-label={`Open deal ${deal.property_address}`}
                    sx={{ minWidth: 0 }}
                  >
                    <OpenInNewIcon fontSize="small" />
                  </Button>
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

/**
 * Unified analysis landing page.
 *
 * On desktop: two side-by-side panels (Single-Family | Multifamily).
 * On mobile: tabbed layout.
 */
export function AnalysisLandingPage() {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))

  const [dialogOpen, setDialogOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState(0)

  return (
    <Box>
      {/* Page header */}
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          mb: 3,
          flexWrap: 'wrap',
          gap: 2,
        }}
      >
        <Box>
          <Typography variant="h5" component="h1" fontWeight={600}>
            Analysis
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Single-family ARV and multifamily pro-forma workflows
          </Typography>
        </Box>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialogOpen(true)}
          aria-label="Start a new analysis"
        >
          New Analysis
        </Button>
      </Box>

      {/* Content — tabbed on mobile, side-by-side on desktop */}
      {isMobile ? (
        <Box>
          <Tabs
            value={mobileTab}
            onChange={(_e, v) => setMobileTab(v)}
            aria-label="Analysis type tabs"
            sx={{ mb: 2 }}
          >
            <Tab
              label="Single-Family"
              icon={<HomeWorkIcon />}
              iconPosition="start"
              id="analysis-tab-0"
              aria-controls="analysis-tabpanel-0"
            />
            <Tab
              label="Multifamily"
              icon={<ApartmentIcon />}
              iconPosition="start"
              id="analysis-tab-1"
              aria-controls="analysis-tabpanel-1"
            />
          </Tabs>
          <Box
            role="tabpanel"
            id="analysis-tabpanel-0"
            aria-labelledby="analysis-tab-0"
            hidden={mobileTab !== 0}
          >
            {mobileTab === 0 && <SingleFamilyPanel />}
          </Box>
          <Box
            role="tabpanel"
            id="analysis-tabpanel-1"
            aria-labelledby="analysis-tab-1"
            hidden={mobileTab !== 1}
          >
            {mobileTab === 1 && <MultifamilyPanel />}
          </Box>
        </Box>
      ) : (
        <Grid container spacing={3}>
          {/* Single-Family column */}
          <Grid item xs={12} md={5}>
            <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <HomeWorkIcon color="success" />
                <Typography variant="h6" component="h2">
                  Single-Family
                </Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <SingleFamilyPanel />
            </Paper>
          </Grid>

          {/* Multifamily column */}
          <Grid item xs={12} md={7}>
            <Paper variant="outlined" sx={{ p: 2, height: '100%' }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                <ApartmentIcon color="primary" />
                <Typography variant="h6" component="h2">
                  Multifamily Deals
                </Typography>
              </Box>
              <Divider sx={{ mb: 2 }} />
              <MultifamilyPanel />
            </Paper>
          </Grid>
        </Grid>
      )}

      {/* New Analysis dialog */}
      <NewAnalysisDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
      />
    </Box>
  )
}

export default AnalysisLandingPage
