/**
 * AnalysisLandingPage — unified entry point for both single-family ARV
 * and multifamily pro-forma workflows.
 *
 * Shows existing ARV sessions and multifamily deals side-by-side, plus a
 * "New Analysis" dialog that routes to the correct workflow based on unit count.
 */
import { useState } from 'react'
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
import UploadFileIcon from '@mui/icons-material/UploadFile'
import { multifamilyService } from '@/services/api'
import type { DealCreatePayload, DealSummary } from '@/types'

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
  /** Called when a single-family analysis is started (navigates to ARV workflow). */
  onSingleFamily: (address: string) => void
}

function NewAnalysisDialog({ open, onClose, onSingleFamily }: NewAnalysisDialogProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [address, setAddress] = useState('')
  const [unitCount, setUnitCount] = useState<number | ''>('')
  const [overrideType, setOverrideType] = useState<AnalysisType | null>(null)
  const [addressError, setAddressError] = useState('')

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

  const handleClose = () => {
    if (createDealMutation.isPending) return
    setAddress('')
    setUnitCount('')
    setOverrideType(null)
    setAddressError('')
    createDealMutation.reset()
    onClose()
  }

  const handleStart = () => {
    if (!address.trim()) {
      setAddressError('Property address is required')
      return
    }
    setAddressError('')

    const type = effectiveType ?? (typeof unitCount === 'number' && unitCount >= 5 ? 'multifamily' : 'single-family')

    if (type === 'multifamily') {
      createDealMutation.mutate({
        property_address: address.trim(),
        unit_count: typeof unitCount === 'number' ? unitCount : 5,
        purchase_price: 0,
        close_date: new Date().toISOString().split('T')[0],
      })
    } else {
      handleClose()
      onSingleFamily(address.trim())
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
          {createDealMutation.isError && (
            <Alert severity="error">
              {(createDealMutation.error as Error)?.message ?? 'Failed to create deal'}
            </Alert>
          )}

          <TextField
            label="Property Address"
            value={address}
            onChange={(e) => {
              setAddress(e.target.value)
              if (e.target.value.trim()) setAddressError('')
            }}
            error={!!addressError}
            helperText={addressError}
            required
            fullWidth
            autoFocus
            inputProps={{ 'aria-label': 'Property address' }}
          />

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
        <Button onClick={handleClose} disabled={createDealMutation.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleStart}
          disabled={createDealMutation.isPending || !address.trim()}
          startIcon={createDealMutation.isPending ? <CircularProgress size={16} /> : undefined}
          aria-label="Start analysis"
        >
          {createDealMutation.isPending ? 'Creating…' : 'Start Analysis'}
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
  const navigate = useNavigate()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [mobileTab, setMobileTab] = useState(0)

  const handleSingleFamily = (address: string) => {
    // Navigate to the ARV workflow with the address pre-filled via query param
    navigate(`/analysis/arv?address=${encodeURIComponent(address)}`)
  }

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
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            startIcon={<UploadFileIcon />}
            onClick={() => navigate('/multifamily/om-intake')}
            aria-label="Upload an Offering Memorandum PDF"
          >
            Upload OM
          </Button>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => setDialogOpen(true)}
            aria-label="Start a new analysis"
          >
            New Analysis
          </Button>
        </Box>
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
        onSingleFamily={handleSingleFamily}
      />
    </Box>
  )
}

export default AnalysisLandingPage
