/**
 * DealDetailPage — tab router for a single multifamily deal.
 *
 * Eight tabs: Rent Roll, Market Rents, Sale Comps, Rehab Plan,
 * Lenders, Funding, Pro Forma, Dashboard.
 *
 * Requirements: 14.1
 */
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Box,
  Breadcrumbs,
  CircularProgress,
  Alert,
  Tab,
  Tabs,
  Typography,
  Chip,
  Button,
} from '@mui/material'
import NavigateNextIcon from '@mui/icons-material/NavigateNext'
import { multifamilyService } from '@/services/api'
import { RentRollTab } from '@/components/multifamily/RentRollTab'
import { MarketRentsTab } from '@/components/multifamily/MarketRentsTab'
import { SaleCompsTab } from '@/components/multifamily/SaleCompsTab'
import { RehabPlanTab } from '@/components/multifamily/RehabPlanTab'
import { LendersTab } from '@/components/multifamily/LendersTab'
import { FundingTab } from '@/components/multifamily/FundingTab'
import { ProFormaTab } from '@/components/multifamily/ProFormaTab'
import { DashboardTab } from '@/components/multifamily/DashboardTab'

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

const TAB_LABELS = [
  'Rent Roll',
  'Market Rents',
  'Sale Comps',
  'Rehab Plan',
  'Lenders',
  'Funding',
  'Pro Forma',
  'Dashboard',
] as const

type TabLabel = (typeof TAB_LABELS)[number]

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function DealDetailPage() {
  const { dealId: dealIdParam } = useParams<{ dealId: string }>()
  const [activeTab, setActiveTab] = useState<number>(0)

  const dealId = Number(dealIdParam)

  const {
    data: deal,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['deal', dealId],
    queryFn: () => multifamilyService.getDeal(dealId),
    enabled: !isNaN(dealId) && dealId > 0,
  })

  if (isNaN(dealId) || dealId <= 0) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="error">Invalid deal ID.</Alert>
        <Button component={Link} to="/multifamily/deals" sx={{ mt: 2 }}>
          Back to Deals
        </Button>
      </Box>
    )
  }

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress aria-label="Loading deal" />
      </Box>
    )
  }

  if (isError || !deal) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="error">
          {(error as Error)?.message ?? 'Failed to load deal'}
        </Alert>
        <Button component={Link} to="/multifamily/deals" sx={{ mt: 2 }}>
          Back to Deals
        </Button>
      </Box>
    )
  }

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setActiveTab(newValue)
  }

  const renderTab = (label: TabLabel) => {
    switch (label) {
      case 'Rent Roll':
        return <RentRollTab dealId={dealId} unitCount={deal.unit_count} />
      case 'Market Rents':
        return <MarketRentsTab dealId={dealId} />
      case 'Sale Comps':
        return <SaleCompsTab dealId={dealId} />
      case 'Rehab Plan':
        return <RehabPlanTab dealId={dealId} />
      case 'Lenders':
        return <LendersTab dealId={dealId} />
      case 'Funding':
        return <FundingTab dealId={dealId} />
      case 'Pro Forma':
        return <ProFormaTab dealId={dealId} />
      case 'Dashboard':
        return <DashboardTab dealId={dealId} />
    }
  }

  return (
    <Box>
      {/* Breadcrumb */}
      <Breadcrumbs
        separator={<NavigateNextIcon fontSize="small" />}
        aria-label="breadcrumb"
        sx={{ mb: 2 }}
      >
        <Typography
          component={Link}
          to="/multifamily/deals"
          color="inherit"
          sx={{ textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
        >
          Multifamily Deals
        </Typography>
        <Typography color="text.primary" noWrap sx={{ maxWidth: 300 }}>
          {deal.property_address}
        </Typography>
      </Breadcrumbs>

      {/* Deal header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h5" component="h1" fontWeight={600} noWrap>
            {deal.property_address}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {[deal.property_city, deal.property_state, deal.property_zip]
              .filter(Boolean)
              .join(', ') || 'No location details'}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <Chip label={`${deal.unit_count} units`} size="small" variant="outlined" />
          <Chip
            label={formatCurrency(deal.purchase_price)}
            size="small"
            color="primary"
            variant="outlined"
          />
          <Chip
            label={deal.status ?? 'draft'}
            size="small"
            color={deal.status === 'active' ? 'success' : 'default'}
          />
        </Box>
      </Box>

      {/* Tab bar */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={activeTab}
          onChange={handleTabChange}
          variant="scrollable"
          scrollButtons="auto"
          aria-label="Deal detail tabs"
        >
          {TAB_LABELS.map((label, index) => (
            <Tab
              key={label}
              label={label}
              id={`deal-tab-${index}`}
              aria-controls={`deal-tabpanel-${index}`}
            />
          ))}
        </Tabs>
      </Box>

      {/* Tab panels */}
      {TAB_LABELS.map((label, index) => (
        <Box
          key={label}
          role="tabpanel"
          hidden={activeTab !== index}
          id={`deal-tabpanel-${index}`}
          aria-labelledby={`deal-tab-${index}`}
        >
          {activeTab === index && renderTab(label)}
        </Box>
      ))}
    </Box>
  )
}

export default DealDetailPage
