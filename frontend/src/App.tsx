import { createContext, useContext, useState, Component } from 'react'
import { Routes, Route, Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { useLoadScript } from '@react-google-maps/api'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Typography,
  Box,
  Paper,
  AppBar,
  Toolbar,
  Button,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  IconButton,
  Divider,
  useMediaQuery,
  useTheme,
  Dialog,
  CircularProgress,
  Alert,
  AlertTitle,
  Stepper,
  Step,
  StepLabel,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  LinearProgress,
  Tooltip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import DownloadIcon from '@mui/icons-material/Download'
import MenuIcon from '@mui/icons-material/Menu'
import HomeIcon from '@mui/icons-material/Home'
import PeopleIcon from '@mui/icons-material/People'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import CampaignIcon from '@mui/icons-material/Campaign'
import AccountBalanceIcon from '@mui/icons-material/AccountBalance'
import Avatar from '@mui/material/Avatar'
import { WorkflowStep, PropertyFacts, PropertyType, ConstructionType, InteriorCondition } from './types'
import { analysisService } from './services/api'
import { PropertyFactsForm } from './components/PropertyFactsForm'
import { LeadListPage } from './components/LeadListPage'
import { LeadDetailPage } from './components/LeadDetailPage'
import { ImportWizard } from './components/ImportWizard'
import { ImportHistoryTable } from './components/ImportHistoryTable'
import { MarketingListManager } from './components/MarketingListManager'
import { OAuthCallback } from './components/OAuthCallback'
import { DealListPage } from './pages/multifamily/DealListPage'
import { DealDetailPage } from './pages/multifamily/DealDetailPage'
import { LenderProfilesPage } from './pages/multifamily/LenderProfilesPage'
import { AnalysisLandingPage } from './pages/AnalysisLandingPage'
import { GeminiNarrativePanel } from './components/GeminiNarrativePanel'

const DRAWER_WIDTH = 240

/** Context that exposes whether the Google Maps JS API has finished loading. */
export const GoogleMapsLoadedContext = createContext(false)
export const useGoogleMapsLoaded = () => useContext(GoogleMapsLoadedContext)

// Must be defined outside the component to keep a stable reference.
// @react-google-maps/api reloads the script if this array changes identity.
const GOOGLE_MAPS_LIBRARIES: ['places'] = ['places']

/** Navigation items for the sidebar / mobile drawer. */
const NAV_ITEMS = [
  { label: 'Analysis', path: '/analysis', icon: <HomeIcon /> },
  { label: 'Leads', path: '/leads', icon: <PeopleIcon /> },
  { label: 'Import', path: '/import', icon: <CloudUploadIcon /> },
  { label: 'Marketing', path: '/marketing', icon: <CampaignIcon /> },
  { label: 'Lender Profiles', path: '/multifamily/lender-profiles', icon: <AccountBalanceIcon /> },
] as const

// ---------------------------------------------------------------------------
// Page wrapper components that handle route params / navigation
// ---------------------------------------------------------------------------

/** Wraps LeadDetailPage to extract leadId from URL params. */
function LeadDetailRoute() {
  const { leadId } = useParams<{ leadId: string }>()
  const navigate = useNavigate()

  const id = Number(leadId)
  if (!leadId || Number.isNaN(id)) {
    return (
      <Box sx={{ p: 4 }}>
        <Typography color="error">Invalid lead ID.</Typography>
        <Button component={Link} to="/leads" sx={{ mt: 1 }}>
          Back to Leads
        </Button>
      </Box>
    )
  }

  return (
    <LeadDetailPage
      leadId={id}
      onBack={() => navigate('/leads')}
      onAnalysisStarted={() => {
        // Could navigate to analysis view in the future
      }}
    />
  )
}

/** Wraps LeadListPage to navigate on lead selection. */
function LeadListRoute() {
  const navigate = useNavigate()
  return <LeadListPage onLeadSelect={(id) => navigate(`/leads/${id}`)} />
}

/** Wraps ImportWizard + ImportHistoryTable together. */
function ImportRoute() {
  const [showWizard, setShowWizard] = useState(false)

  if (showWizard) {
    return (
      <ImportWizard
        onComplete={() => setShowWizard(false)}
        onCancel={() => setShowWizard(false)}
      />
    )
  }

  return (
    <Box sx={{ px: { xs: 1, sm: 2 } }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h5" component="h2">
          Import
        </Typography>
        <Button
          variant="contained"
          startIcon={<CloudUploadIcon />}
          onClick={() => setShowWizard(true)}
          aria-label="Start new import from Google Sheets"
        >
          New Import
        </Button>
      </Box>
      <ImportHistoryTable onImportStarted={() => setShowWizard(false)} />
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Map backend step name strings (e.g. "PROPERTY_FACTS") to WorkflowStep numbers. */
function stepNameToNumber(name: string): number {
  const map: Record<string, number> = {
    PROPERTY_FACTS:    WorkflowStep.PROPERTY_FACTS,
    COMPARABLE_SEARCH: WorkflowStep.COMPARABLE_SEARCH,
    COMPARABLE_REVIEW: WorkflowStep.COMPARABLE_REVIEW,
    WEIGHTED_SCORING:  WorkflowStep.WEIGHTED_SCORING,
    VALUATION_MODELS:  WorkflowStep.VALUATION,
    REPORT_GENERATION: WorkflowStep.REPORT,
  }
  return map[name] ?? WorkflowStep.PROPERTY_FACTS
}

/** Serialise camelCase PropertyFacts → snake_case backend payload. */
function serializeFacts(facts: PropertyFacts): Record<string, any> {
  return {
    address:              facts.address,
    property_type:        facts.propertyType,
    units:                facts.units,
    bedrooms:             facts.bedrooms,
    bathrooms:            facts.bathrooms,
    square_footage:       facts.squareFootage,
    lot_size:             facts.lotSize,
    year_built:           facts.yearBuilt,
    construction_type:    facts.constructionType,
    basement:             facts.basement,
    parking_spaces:       facts.parkingSpaces,
    assessed_value:       facts.assessedValue,
    annual_taxes:         facts.annualTaxes,
    zoning:               facts.zoning ?? '',
    interior_condition:   facts.interiorCondition,
    latitude:             facts.coordinates?.lat ?? null,
    longitude:            facts.coordinates?.lng ?? null,
    data_source:          facts.dataSource ?? 'manual',
    user_modified_fields: facts.userModifiedFields ?? [],
    ...(facts.lastSalePrice != null && { last_sale_price: facts.lastSalePrice }),
    ...(facts.lastSaleDate  != null && { last_sale_date:  facts.lastSaleDate  }),
  }
}

// ---------------------------------------------------------------------------
// Helper: map snake_case backend response → camelCase PropertyFacts
// ---------------------------------------------------------------------------

function mapBackendFactsToFrontend(raw: Record<string, any>): Partial<PropertyFacts> {
  // Backend stores enum values as lowercase (e.g. 'multi_family').
  // Frontend enum values are uppercase (e.g. 'MULTI_FAMILY').
  // Map by converting to uppercase and replacing hyphens/spaces with underscores.
  const normaliseEnumValue = (val: string | null | undefined): string =>
    (val ?? '').toUpperCase().replace(/-/g, '_').replace(/ /g, '_')

  const rawPT = normaliseEnumValue(raw.property_type)
  const propertyType = Object.values(PropertyType).includes(rawPT as PropertyType)
    ? (rawPT as PropertyType)
    : PropertyType.SINGLE_FAMILY

  const rawCT = normaliseEnumValue(raw.construction_type)
  const constructionType = Object.values(ConstructionType).includes(rawCT as ConstructionType)
    ? (rawCT as ConstructionType)
    : ConstructionType.FRAME

  const rawIC = normaliseEnumValue(raw.interior_condition)
  const interiorCondition = Object.values(InteriorCondition).includes(rawIC as InteriorCondition)
    ? (rawIC as InteriorCondition)
    : InteriorCondition.AVERAGE

  const facts: Partial<PropertyFacts> = {
    address:          raw.address ?? '',
    propertyType,
    constructionType,
    interiorCondition,
    dataSource:       raw.data_source ?? 'cook_county_assessor',
    userModifiedFields: raw.user_modified_fields ?? [],
    basement:         raw.basement ?? false,
    parkingSpaces:    raw.parking_spaces ?? 0,
  }

  if (raw.units        != null) facts.units        = Number(raw.units)
  if (raw.bedrooms     != null) facts.bedrooms     = Number(raw.bedrooms)
  if (raw.bathrooms    != null) facts.bathrooms    = Number(raw.bathrooms)
  if (raw.square_footage != null) facts.squareFootage = Number(raw.square_footage)
  if (raw.lot_size     != null) facts.lotSize      = Number(raw.lot_size)
  if (raw.year_built   != null) facts.yearBuilt    = Number(raw.year_built)
  if (raw.assessed_value != null) facts.assessedValue = Number(raw.assessed_value)
  if (raw.annual_taxes != null) facts.annualTaxes  = Number(raw.annual_taxes)
  if (raw.zoning       != null) facts.zoning       = String(raw.zoning)

  if (raw.latitude != null && raw.longitude != null) {
    facts.coordinates = { lat: Number(raw.latitude), lng: Number(raw.longitude) }
  }

  return facts
}

// ---------------------------------------------------------------------------
// ReportStep — fetches and displays the full analysis report
// ---------------------------------------------------------------------------

function ReportStep({
  sessionId,
  onBack,
  isMutating,
}: {
  sessionId: string
  onBack: () => void
  isMutating: boolean
}) {
  const navigate = useNavigate()
  const { data: report, isLoading, error } = useQuery({
    queryKey: ['report', sessionId],
    queryFn: () => analysisService.generateReport(sessionId),
    staleTime: Infinity, // report doesn't change once generated
  })

  const handleExcelDownload = async () => {
    try {
      const blob = await analysisService.exportToExcel(sessionId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `analysis_${sessionId.slice(0, 8)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('[ReportStep] Excel export failed:', err)
    }
  }

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading report" />
      </Box>
    )
  }

  if (error) {
    return (
      <Alert severity="error">
        <AlertTitle>Failed to load report</AlertTitle>
        {(error as Error).message}
      </Alert>
    )
  }

  const sections = (report as any)?.sections ?? {}

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <Typography variant="h5">Report Generated</Typography>
        <Button
          variant="contained"
          startIcon={<DownloadIcon />}
          onClick={handleExcelDownload}
          size="small"
        >
          Export to Excel
        </Button>
      </Box>

      {/* Section A: Subject Property Facts */}
      {sections.section_a && (
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight="medium">{sections.section_a.title}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <TableContainer>
              <Table size="small">
                <TableBody>
                  {Object.entries(sections.section_a.data).map(([key, val]: [string, any]) => (
                    <TableRow key={key}>
                      <TableCell sx={{ fontWeight: 'bold', width: '35%' }}>{key}</TableCell>
                      <TableCell>{String(val)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Section B: Comparable Sales */}
      {sections.section_b && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight="medium">{sections.section_b.title}</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ overflowX: 'auto' }}>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    {sections.section_b.columns.map((col: string) => (
                      <TableCell key={col} sx={{ fontWeight: 'bold', whiteSpace: 'nowrap' }}>{col}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {sections.section_b.rows.map((row: any, i: number) => (
                    <TableRow key={i} sx={row.Type === 'Subject Property' ? { bgcolor: 'warning.50' } : {}}>
                      {sections.section_b.columns.map((col: string) => (
                        <TableCell key={col} sx={{ whiteSpace: 'nowrap' }}>{row[col] ?? '—'}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Section C: Weighted Ranking */}
      {sections.section_c && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight="medium">{sections.section_c.title}</Typography>
          </AccordionSummary>
          <AccordionDetails sx={{ overflowX: 'auto' }}>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    {sections.section_c.columns.map((col: string) => (
                      <TableCell key={col} sx={{ fontWeight: 'bold', whiteSpace: 'nowrap' }}>{col}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {sections.section_c.rows.map((row: any, i: number) => (
                    <TableRow key={i}>
                      {sections.section_c.columns.map((col: string) => (
                        <TableCell key={col} sx={{ whiteSpace: 'nowrap' }}>{row[col] ?? '—'}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Section D: Valuation Models */}
      {sections.section_d && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight="medium">{sections.section_d.title}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            {sections.section_d.valuations.map((v: any, i: number) => (
              <Box key={i} sx={{ mb: 3 }}>
                <Typography variant="subtitle2" fontWeight="bold" gutterBottom>{v.address}</Typography>
                {v.narrative && (
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    {v.narrative}
                  </Typography>
                )}
                <TableContainer>
                  <Table size="small">
                    <TableBody>
                      {Object.entries(v.metrics).map(([k, val]: [string, any]) => (
                        <TableRow key={k}>
                          <TableCell sx={{ fontWeight: 'bold', width: '40%' }}>{k}</TableCell>
                          <TableCell>{val}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
                {i < sections.section_d.valuations.length - 1 && <Divider sx={{ mt: 2 }} />}
              </Box>
            ))}
          </AccordionDetails>
        </Accordion>
      )}

      {/* Section E: ARV Range */}
      {sections.section_e && (
        <Accordion defaultExpanded>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight="medium">{sections.section_e.title}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2 }}>
              {Object.entries(sections.section_e.arv_range).map(([label, val]: [string, any]) => (
                <Paper key={label} variant="outlined" sx={{ p: 2, flex: '1 1 160px', textAlign: 'center' }}>
                  <Typography variant="caption" color="text.secondary" display="block">{label}</Typography>
                  <Typography variant="h6" fontWeight="bold" color="success.main">{val}</Typography>
                </Paper>
              ))}
            </Box>
          </AccordionDetails>
        </Accordion>
      )}

      {/* Section F: Key Drivers */}
      {sections.section_f && (
        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight="medium">{sections.section_f.title}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Box component="ul" sx={{ m: 0, pl: 3 }}>
              {sections.section_f.drivers.map((d: string, i: number) => (
                <Typography key={i} component="li" variant="body2" sx={{ mb: 0.5 }}>{d}</Typography>
              ))}
            </Box>
          </AccordionDetails>
        </Accordion>
      )}

      <Box sx={{ display: 'flex', gap: 2, mt: 3 }}>
        <Button
          variant="outlined"
          startIcon={<ArrowBackIcon />}
          onClick={onBack}
          disabled={isMutating}
        >
          Back
        </Button>
        <Button variant="outlined" onClick={() => navigate('/analysis')}>
          Start New Analysis
        </Button>
      </Box>
    </Box>
  )
}

// ---------------------------------------------------------------------------
// Error Boundary — catches render errors and shows a useful message
// ---------------------------------------------------------------------------

interface ErrorBoundaryState {
  error: Error | null
}

class AnalysisErrorBoundary extends Component<
  { children: React.ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught render error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <Paper elevation={2} sx={{ p: { xs: 2, sm: 3, md: 4 } }}>
          <Alert
            severity="error"
            action={
              <Button
                color="inherit"
                size="small"
                onClick={() => {
                  this.setState({ error: null })
                  window.location.href = '/analysis'
                }}
              >
                Start Over
              </Button>
            }
          >
            <AlertTitle>Something went wrong</AlertTitle>
            {this.state.error.message}
            {import.meta.env.DEV && (
              <Box
                component="pre"
                sx={{ mt: 1, fontSize: 11, whiteSpace: 'pre-wrap', opacity: 0.7 }}
              >
                {this.state.error.stack}
              </Box>
            )}
          </Alert>
        </Paper>
      )
    }
    return this.props.children
  }
}

/** ARV analysis workflow — session ID lives in the URL, state fetched from backend via React Query. */
function AnalysisRoute() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // ---------------------------------------------------------------------------
  // Fetch session state from backend — this is the single source of truth.
  // Polling is enabled while the session is in a loading state (e.g. async
  // comparable search running). React Query handles caching and deduplication.
  // ---------------------------------------------------------------------------
  const {
    data: session,
    isLoading: sessionLoading,
    error: sessionError,
  } = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => analysisService.getSession(sessionId!),
    enabled: !!sessionId,
    // Poll every 5 seconds while the backend is processing (e.g. Celery task)
    refetchInterval: (query) => {
      const data = query.state.data as any
      return data?.loading === true ? 5000 : false
    },
    // Don't refetch on window focus during active polling — avoids double requests
    refetchOnWindowFocus: false,
    retry: 2,
  })

  // ---------------------------------------------------------------------------
  // Mutations — each action POSTs/PUTs to the backend then invalidates the cache
  // so the query above re-fetches the latest session state automatically.
  // ---------------------------------------------------------------------------

  const confirmFactsMutation = useMutation({
    mutationFn: async (facts: PropertyFacts) => {
      const payload = serializeFacts(facts)
      await analysisService.updateStepData(sessionId!, 1, payload)
      return analysisService.advanceToStep(sessionId!, 2)
    },
    onSuccess: () => {
      // Invalidate so React Query re-fetches and starts polling if loading=true
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
    onError: (err: any) => {
      console.error('[AnalysisRoute] confirmFacts failed:', err)
    },
  })

  const advanceMutation = useMutation({
    mutationFn: (step: number) => analysisService.advanceToStep(sessionId!, step),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
    onError: (err: any) => {
      console.error('[AnalysisRoute] advance failed:', err)
    },
  })

  const goBackMutation = useMutation({
    mutationFn: (step: number) => analysisService.goBackToStep(sessionId!, step),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
    onError: (err: any) => {
      console.error('[AnalysisRoute] goBack failed:', err)
    },
  })

  // ---------------------------------------------------------------------------
  // Derived state from server response
  // ---------------------------------------------------------------------------

  const raw = session as any
  const currentStep: number = raw?.current_step
    ? stepNameToNumber(raw.current_step)
    : WorkflowStep.PROPERTY_FACTS
  const isLoading = raw?.loading === true || sessionLoading
  const stepResults = raw?.step_results ?? null
  const rawPropertyFacts = raw?.subject_property ?? null

  const mappedFacts: PropertyFacts | undefined = rawPropertyFacts
    ? (mapBackendFactsToFrontend(rawPropertyFacts) as PropertyFacts)
    : undefined

  const mutationError = confirmFactsMutation.error || advanceMutation.error || goBackMutation.error
  const errorMessage = mutationError
    ? (mutationError as Error).message
    : sessionError
    ? (sessionError as Error).message
    : null

  // ---------------------------------------------------------------------------
  // Step definitions for the progress stepper
  // Step 1 (Property Facts) is skipped in the stepper since it's the start.
  // The visible steps are the ones the user actively reviews/advances through.
  // ---------------------------------------------------------------------------

  const STEPS = [
    { label: 'Property Facts',    step: WorkflowStep.PROPERTY_FACTS },
    { label: 'Comparable Review', step: WorkflowStep.COMPARABLE_REVIEW },
    { label: 'Weighted Scoring',  step: WorkflowStep.WEIGHTED_SCORING },
    { label: 'Valuation',         step: WorkflowStep.VALUATION },
    { label: 'Report',            step: WorkflowStep.REPORT },
  ]

  // Active stepper index (0-based). COMPARABLE_SEARCH maps to index 1 (same as COMPARABLE_REVIEW).
  const effectiveStep = currentStep === WorkflowStep.COMPARABLE_SEARCH
    ? WorkflowStep.COMPARABLE_REVIEW
    : currentStep
  const stepperIndex = Math.max(0, STEPS.findIndex(s => s.step === effectiveStep))

  const isMutating = confirmFactsMutation.isPending || advanceMutation.isPending || goBackMutation.isPending

  // ---------------------------------------------------------------------------
  // DEV-ONLY: Log step state to console so UI issues can be diagnosed by
  // reading code + logs rather than launching a browser.
  // ---------------------------------------------------------------------------
  if (import.meta.env.DEV) {
    console.group(`[AnalysisRoute] step=${raw?.current_step ?? 'unknown'} (${currentStep})`)
    console.log('subject_property:', rawPropertyFacts ? `${rawPropertyFacts.address}` : null)
    console.log('ranked_comparables:', (raw?.ranked_comparables ?? []).length)
    console.log('valuation_result:', raw?.valuation_result ?? null)
    console.log('step_results keys:', Object.keys(raw?.step_results ?? {}))
    console.log('loading:', isLoading, '| mutating:', isMutating)
    console.groupEnd()
  }

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (!sessionId) {
    return (
      <Alert severity="error">
        No session ID in URL. <Button onClick={() => navigate('/analysis')}>Go back</Button>
      </Alert>
    )
  }

  if (sessionLoading && !session) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
        <CircularProgress aria-label="Loading session" />
      </Box>
    )
  }

  if (sessionError && !session) {
    return (
      <Alert severity="error">
        <AlertTitle>Failed to load session</AlertTitle>
        {(sessionError as Error).message}
        <Button onClick={() => navigate('/analysis')} sx={{ mt: 1 }}>
          Start New Analysis
        </Button>
      </Alert>
    )
  }

  return (
    <Paper elevation={2} sx={{ p: { xs: 2, sm: 3, md: 4 } }}>
      {/* Progress stepper — hidden during the Gemini loading animation */}
      {!confirmFactsMutation.isPending && (
        <Stepper activeStep={stepperIndex} sx={{ mb: 3 }} alternativeLabel>
          {STEPS.map(({ label }) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
      )}

      {errorMessage && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          onClose={() => {
            confirmFactsMutation.reset()
            advanceMutation.reset()
            goBackMutation.reset()
          }}
        >
          <AlertTitle>Analysis Error</AlertTitle>
          {errorMessage}
        </Alert>
      )}

      {currentStep === WorkflowStep.PROPERTY_FACTS && (
        <>
          {confirmFactsMutation.isPending && (
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 3,
                py: 8,
              }}
            >
              <CircularProgress size={48} />
              <Box sx={{ textAlign: 'center' }}>
                <Typography variant="h6" gutterBottom>
                  Searching for Comparable Sales
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Gemini AI is analysing the property and finding comparable sales…
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  This typically takes 20–40 seconds.
                </Typography>
              </Box>
            </Box>
          )}
          {!confirmFactsMutation.isPending && (
            <PropertyFactsForm
              propertyFacts={mappedFacts}
              onAddressSubmit={async (address, coords) => {
                // If the user manually searches for a new address (e.g. the session
                // has no pre-loaded property facts), create a new session and navigate to it.
                // Uses analysisService to respect VITE_API_BASE_URL and centralized error handling.
                try {
                  const response = await analysisService.startAnalysis(address, coords?.lat, coords?.lng)
                  queryClient.setQueryData(['session', response.sessionId], {
                    session_id: response.sessionId,
                    current_step: 'PROPERTY_FACTS',
                    loading: false,
                    subject_property: response.propertyFacts ?? null,
                    step_results: {},
                    completed_steps: [],
                  })
                  navigate(`/analysis/arv/${response.sessionId}`)
                } catch (err: any) {
                  console.error('[AnalysisRoute] onAddressSubmit failed:', err)
                }
              }}
              onSubmit={(facts) => confirmFactsMutation.mutate(facts)}
              loading={isLoading || confirmFactsMutation.isPending}
              error={errorMessage ?? undefined}
            />
          )}
        </>
      )}

      {/* Legacy: sessions that completed comparable search before the auto-advance fix */}
      {currentStep === WorkflowStep.COMPARABLE_SEARCH && (
        <Box>
          <Typography variant="h5" gutterBottom>Comparable Review</Typography>
          <GeminiNarrativePanel narrative={stepResults?.COMPARABLE_SEARCH?.narrative} />
          <Box sx={{ display: 'flex', gap: 2, mt: 2 }}>
            <Button variant="outlined" startIcon={<ArrowBackIcon />}
              onClick={() => goBackMutation.mutate(WorkflowStep.PROPERTY_FACTS)}
              disabled={isMutating}>Back</Button>
            <Button variant="contained"
              onClick={() => advanceMutation.mutate(WorkflowStep.WEIGHTED_SCORING)}
              disabled={isMutating}>
              {advanceMutation.isPending ? 'Loading…' : 'Advance to Weighted Scoring'}
            </Button>
          </Box>
        </Box>
      )}

      {currentStep === WorkflowStep.COMPARABLE_REVIEW && (
        <Box>
          <Typography variant="h5" gutterBottom>
            Comparable Review
          </Typography>
          <GeminiNarrativePanel narrative={stepResults?.COMPARABLE_SEARCH?.narrative} />
          <Box sx={{ display: 'flex', gap: 2, mt: 2 }}>
            <Button
              variant="outlined"
              startIcon={<ArrowBackIcon />}
              onClick={() => goBackMutation.mutate(WorkflowStep.PROPERTY_FACTS)}
              disabled={isMutating}
            >
              Back
            </Button>
            <Button
              variant="contained"
              onClick={() => advanceMutation.mutate(WorkflowStep.WEIGHTED_SCORING)}
              disabled={isMutating}
            >
              {advanceMutation.isPending ? 'Loading…' : 'Advance to Weighted Scoring'}
            </Button>
          </Box>
        </Box>
      )}

      {currentStep === WorkflowStep.WEIGHTED_SCORING && (
        <Box>
          <Typography variant="h5" gutterBottom>
            Weighted Scoring
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Comparable sales ranked by weighted similarity to the subject property.
            Higher scores indicate closer matches.
          </Typography>

          {raw?.ranked_comparables?.length > 0 ? (
            <TableContainer component={Paper} variant="outlined" sx={{ mb: 3 }}>
              <Table size="small" aria-label="Ranked comparables">
                <TableHead>
                  <TableRow>
                    <TableCell>Rank</TableCell>
                    <TableCell>Address</TableCell>
                    <TableCell align="right">Sale Price</TableCell>
                    <TableCell align="right">Sq Ft</TableCell>
                    <TableCell align="right">Beds / Baths</TableCell>
                    <TableCell align="right">Distance</TableCell>
                    <TableCell align="right">Total Score</TableCell>
                    <TableCell>Score Breakdown</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {raw.ranked_comparables.map((rc: any) => (
                    <TableRow key={rc.id} hover>
                      <TableCell>
                        <Chip
                          label={`#${rc.rank}`}
                          size="small"
                          color={rc.rank === 1 ? 'primary' : 'default'}
                        />
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">{rc.comparable.address}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {rc.comparable.year_built} · {rc.comparable.construction_type.replace('_', ' ')} · {rc.comparable.interior_condition.replace('_', ' ')}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        ${rc.comparable.sale_price.toLocaleString()}
                      </TableCell>
                      <TableCell align="right">
                        {rc.comparable.square_footage.toLocaleString()}
                      </TableCell>
                      <TableCell align="right">
                        {rc.comparable.bedrooms} / {rc.comparable.bathrooms}
                      </TableCell>
                      <TableCell align="right">
                        {rc.comparable.distance_miles.toFixed(2)} mi
                      </TableCell>
                      <TableCell align="right">
                        <Typography variant="body2" fontWeight="bold">
                          {rc.total_score.toFixed(0)}%
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ minWidth: 200 }}>
                        {Object.entries(rc.score_breakdown).map(([key, val]: [string, any]) => (
                          <Tooltip
                            key={key}
                            title={`${key.replace('_score', '').replace('_', ' ')}: ${val.toFixed(0)}%`}
                          >
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.25 }}>
                              <Typography variant="caption" sx={{ width: 80, flexShrink: 0, textTransform: 'capitalize' }}>
                                {key.replace('_score', '').replace('_', ' ')}
                              </Typography>
                              <LinearProgress
                                variant="determinate"
                                value={val}
                                sx={{ flex: 1, height: 6, borderRadius: 3 }}
                              />
                            </Box>
                          </Tooltip>
                        ))}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Alert severity="info" sx={{ mb: 3 }}>
              No ranked comparables available.
            </Alert>
          )}

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button
              variant="outlined"
              startIcon={<ArrowBackIcon />}
              onClick={() => goBackMutation.mutate(WorkflowStep.COMPARABLE_REVIEW)}
              disabled={isMutating}
            >
              Back
            </Button>
            <Button
              variant="contained"
              onClick={() => advanceMutation.mutate(WorkflowStep.VALUATION)}
              disabled={isMutating}
            >
              {advanceMutation.isPending ? 'Loading…' : 'Advance to Valuation Models'}
            </Button>
          </Box>
        </Box>
      )}

      {currentStep === WorkflowStep.VALUATION && (
        <Box>
          <Typography variant="h5" gutterBottom>
            Valuation Models
          </Typography>

          {raw?.valuation_result ? (
            <>
              {/* ARV Range Cards */}
              <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                {[
                  { label: 'Conservative ARV', value: raw.valuation_result.conservative_arv, color: 'info.main', subtitle: '25th percentile' },
                  { label: 'Likely ARV', value: raw.valuation_result.likely_arv, color: 'success.main', subtitle: 'Median estimate' },
                  { label: 'Aggressive ARV', value: raw.valuation_result.aggressive_arv, color: 'warning.main', subtitle: '75th percentile' },
                ].map(({ label, value, color, subtitle }) => (
                  <Paper
                    key={label}
                    variant="outlined"
                    sx={{ p: 2, flex: '1 1 160px', textAlign: 'center' }}
                  >
                    <Typography variant="caption" color="text.secondary" display="block">
                      {label}
                    </Typography>
                    <Typography variant="h5" fontWeight="bold" sx={{ color, my: 0.5 }}>
                      ${value.toLocaleString()}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {subtitle}
                    </Typography>
                  </Paper>
                ))}
              </Box>

              {/* Confidence score */}
              {raw.valuation_result.confidence_score != null && (
                <Box sx={{ mb: 3 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                    <Typography variant="body2">Confidence Score</Typography>
                    <Typography variant="body2" fontWeight="bold">
                      {raw.valuation_result.confidence_score.toFixed(0)}%
                    </Typography>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={raw.valuation_result.confidence_score}
                    color={
                      raw.valuation_result.confidence_score >= 70 ? 'success'
                      : raw.valuation_result.confidence_score >= 40 ? 'warning'
                      : 'error'
                    }
                    sx={{ height: 8, borderRadius: 4 }}
                  />
                </Box>
              )}

              {/* Key drivers */}
              {raw.valuation_result.key_drivers?.length > 0 && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" gutterBottom>Key Value Drivers</Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                    {raw.valuation_result.key_drivers.map((driver: string, i: number) => (
                      <Chip key={i} label={driver} size="small" variant="outlined" />
                    ))}
                  </Box>
                </Box>
              )}

              {/* All valuations distribution */}
              {raw.valuation_result.all_valuations?.length > 0 && (
                <Box sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" gutterBottom>
                    Individual Estimates ({raw.valuation_result.all_valuations.length} total)
                  </Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                    {raw.valuation_result.all_valuations.map((v: number, i: number) => (
                      <Chip
                        key={i}
                        label={`$${v.toLocaleString()}`}
                        size="small"
                        variant="outlined"
                        color={
                          v === raw.valuation_result.likely_arv ? 'success'
                          : v === raw.valuation_result.conservative_arv ? 'info'
                          : v === raw.valuation_result.aggressive_arv ? 'warning'
                          : 'default'
                        }
                      />
                    ))}
                  </Box>
                </Box>
              )}
            </>
          ) : (
            <Alert severity="info" sx={{ mb: 3 }}>
              No valuation data available.
            </Alert>
          )}

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button
              variant="outlined"
              startIcon={<ArrowBackIcon />}
              onClick={() => goBackMutation.mutate(WorkflowStep.WEIGHTED_SCORING)}
              disabled={isMutating}
            >
              Back
            </Button>
            <Button
              variant="contained"
              onClick={() => advanceMutation.mutate(WorkflowStep.REPORT)}
              disabled={isMutating}
            >
              {advanceMutation.isPending ? 'Loading…' : 'Generate Report'}
            </Button>
          </Box>
        </Box>
      )}

      {currentStep === WorkflowStep.REPORT && (
        <ReportStep
          sessionId={sessionId!}
          onBack={() => goBackMutation.mutate(WorkflowStep.VALUATION)}
          isMutating={isMutating}
        />
      )}
    </Paper>
  )
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

function App() {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('md'))
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [avatarOpen, setAvatarOpen] = useState(false)

  // Load the Google Maps JS API (with Places library) via @react-google-maps/api.
  // useLoadScript manages the script tag lifecycle and exposes isLoaded so
  // components can gate autocomplete on actual API readiness.
  const { isLoaded: mapsLoaded } = useLoadScript({
    googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? '',
    libraries: GOOGLE_MAPS_LIBRARIES,
  })

  const toggleDrawer = () => setDrawerOpen((prev) => !prev)

  const drawerContent = (
    <Box sx={{ width: DRAWER_WIDTH }} role="navigation" aria-label="Main navigation">
      <Box sx={{ p: 2 }}>
        <Typography variant="h6" component="span" noWrap>
          RE Analysis
        </Typography>
      </Box>
      <Divider />
      <List>
        {NAV_ITEMS.map((item) => (
          <ListItem key={item.path} disablePadding>
            <ListItemButton
              component={Link}
              to={item.path}
              onClick={() => isMobile && setDrawerOpen(false)}
              aria-label={`Navigate to ${item.label}`}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </Box>
  )

  return (
    <GoogleMapsLoadedContext.Provider value={mapsLoaded}>
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      {/* App Bar */}
      <AppBar
        position="fixed"
        sx={{
          zIndex: theme.zIndex.drawer + 1,
        }}
      >
        <Toolbar>
          {isMobile && (
            <IconButton
              color="inherit"
              edge="start"
              onClick={toggleDrawer}
              sx={{ mr: 2 }}
              aria-label="Open navigation menu"
            >
              <MenuIcon />
            </IconButton>
          )}
          <Typography variant="h6" component="h1" noWrap sx={{ flexGrow: 1 }}>
            Real Estate Analysis Platform
          </Typography>
          <Avatar
            src="/images/avatar.png"
            alt="B and B Real Estate"
            onClick={() => setAvatarOpen(true)}
            sx={{
              width: 40,
              height: 40,
              border: '2px solid rgba(255,255,255,0.7)',
              cursor: 'pointer',
              transition: 'transform 0.2s',
              '&:hover': { transform: 'scale(1.1)' },
            }}
          />
          <Dialog
            open={avatarOpen}
            onClose={() => setAvatarOpen(false)}
            maxWidth="sm"
            PaperProps={{
              sx: { borderRadius: 3, overflow: 'hidden', background: 'transparent', boxShadow: 'none' },
            }}
          >
            <Box
              component="img"
              src="/images/avatar.png"
              alt="B and B Real Estate"
              onClick={() => setAvatarOpen(false)}
              sx={{
                width: '100%',
                maxWidth: 400,
                height: 'auto',
                display: 'block',
                cursor: 'pointer',
                borderRadius: 3,
              }}
            />
          </Dialog>
        </Toolbar>
      </AppBar>

      {/* Sidebar navigation */}
      {isMobile ? (
        <Drawer
          variant="temporary"
          open={drawerOpen}
          onClose={toggleDrawer}
          ModalProps={{ keepMounted: true }}
          sx={{
            '& .MuiDrawer-paper': { width: DRAWER_WIDTH },
          }}
        >
          {drawerContent}
        </Drawer>
      ) : (
        <Drawer
          variant="permanent"
          sx={{
            width: DRAWER_WIDTH,
            flexShrink: 0,
            '& .MuiDrawer-paper': {
              width: DRAWER_WIDTH,
              boxSizing: 'border-box',
            },
          }}
        >
          <Toolbar /> {/* Spacer for AppBar */}
          {drawerContent}
        </Drawer>
      )}

      {/* Main content */}
      <Box
        component="main"
        role="main"
        sx={{
          flexGrow: 1,
          p: { xs: 2, sm: 3 },
          mt: '64px', // AppBar height
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
        }}
      >
        <Routes>
          {/* Redirect root to unified analysis landing page */}
          <Route path="/" element={<Navigate to="/analysis" replace />} />
          {/* Unified analysis landing page */}
          <Route path="/analysis" element={<AnalysisLandingPage />} />
          {/* ARV workflow — session ID in URL, state fetched from backend */}
          <Route path="/analysis/arv/:sessionId" element={<AnalysisErrorBoundary><AnalysisRoute /></AnalysisErrorBoundary>} />
          <Route path="/leads" element={<LeadListRoute />} />
          <Route path="/leads/:leadId" element={<LeadDetailRoute />} />
          <Route path="/import" element={<ImportRoute />} />
          <Route path="/import/callback" element={<OAuthCallback />} />
          <Route path="/marketing" element={<MarketingListManager />} />
          {/* Multifamily routes (Req 14.1) */}
          <Route path="/multifamily/deals" element={<DealListPage />} />
          <Route path="/multifamily/deals/:dealId" element={<DealDetailPage />} />
          <Route path="/multifamily/lender-profiles" element={<LenderProfilesPage />} />
        </Routes>
      </Box>
    </Box>
    </GoogleMapsLoadedContext.Provider>
  )
}

export default App
