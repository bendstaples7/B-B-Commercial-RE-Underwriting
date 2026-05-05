import { useState } from 'react'
import { Routes, Route, Link, useNavigate, useParams } from 'react-router-dom'
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
} from '@mui/material'
import MenuIcon from '@mui/icons-material/Menu'
import HomeIcon from '@mui/icons-material/Home'
import PeopleIcon from '@mui/icons-material/People'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import CampaignIcon from '@mui/icons-material/Campaign'
import ApartmentIcon from '@mui/icons-material/Apartment'
import Avatar from '@mui/material/Avatar'
import { WorkflowStep, PropertyFacts, PropertyType, ConstructionType, InteriorCondition } from './types'
import { PropertyFactsForm } from './components/PropertyFactsForm'
import { LeadListPage } from './components/LeadListPage'
import { LeadDetailPage } from './components/LeadDetailPage'
import { ImportWizard } from './components/ImportWizard'
import { ImportHistoryTable } from './components/ImportHistoryTable'
import { MarketingListManager } from './components/MarketingListManager'
import { OAuthCallback } from './components/OAuthCallback'
import { CondoReviewPage } from './components/CondoReviewPage'

const DRAWER_WIDTH = 240

/** Navigation items for the sidebar / mobile drawer. */
const NAV_ITEMS = [
  { label: 'Analysis', path: '/', icon: <HomeIcon /> },
  { label: 'Leads', path: '/leads', icon: <PeopleIcon /> },
  { label: 'Import', path: '/import', icon: <CloudUploadIcon /> },
  { label: 'Marketing', path: '/marketing', icon: <CampaignIcon /> },
  { label: 'Condo Filter', path: '/condo-filter', icon: <ApartmentIcon /> },
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

/** Original property analysis view. */
function AnalysisRoute() {
  const [currentStep] = useState<WorkflowStep>(WorkflowStep.PROPERTY_FACTS)
  const [propertyFacts, setPropertyFacts] = useState<PropertyFacts | undefined>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | undefined>()

  const handleAddressSubmit = async (address: string) => {
    setLoading(true)
    setError(undefined)

    try {
      // TODO: Call API to fetch property facts
      await new Promise(resolve => setTimeout(resolve, 1000))

      setPropertyFacts({
        address,
        propertyType: PropertyType.SINGLE_FAMILY,
        units: 1,
        bedrooms: 3,
        bathrooms: 2,
        squareFootage: 1500,
        lotSize: 5000,
        yearBuilt: 2000,
        constructionType: ConstructionType.BRICK,
        basement: true,
        parkingSpaces: 2,
        assessedValue: 250000,
        annualTaxes: 5000,
        zoning: 'R-1',
        interiorCondition: InteriorCondition.AVERAGE,
        coordinates: { lat: 41.8781, lng: -87.6298 },
        dataSource: 'mock',
        userModifiedFields: [],
      })
    } catch {
      setError('Failed to fetch property data. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handlePropertyFactsSubmit = (facts: PropertyFacts) => {
    setPropertyFacts(facts)
    console.log('Property facts confirmed:', facts)
  }

  return (
    <Paper elevation={2} sx={{ p: { xs: 2, sm: 3, md: 4 } }}>
      {currentStep === WorkflowStep.PROPERTY_FACTS && (
        <PropertyFactsForm
          propertyFacts={propertyFacts}
          onAddressSubmit={handleAddressSubmit}
          onSubmit={handlePropertyFactsSubmit}
          loading={loading}
          error={error}
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
          <Route path="/" element={<AnalysisRoute />} />
          <Route path="/leads" element={<LeadListRoute />} />
          <Route path="/leads/:leadId" element={<LeadDetailRoute />} />
          <Route path="/import" element={<ImportRoute />} />
          <Route path="/import/callback" element={<OAuthCallback />} />
          <Route path="/marketing" element={<MarketingListManager />} />
          <Route path="/condo-filter" element={<CondoReviewPage />} />
        </Routes>
      </Box>
    </Box>
  )
}

export default App
