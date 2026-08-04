/**
 * Hostile CC header packing harness — real MUI + production packing tokens.
 * Served by Vite for Playwright geometry / paint gates (not a static HTML twin).
 *
 * ?fixture=residential — no-condo header for KPI centering symmetry gate
 * (default) — condo hostile Hoyne fixture
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Box, Chip, CssBaseline, IconButton, Typography } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import {
  ccHeaderAddressColumnSx,
  ccHeaderPaperSx,
  ccHeaderPrimaryClusterSx,
  ccHeaderTrailingPanelsSx,
  ccHeroAddressSx,
  ccHeroSecondarySx,
} from '@/components/lead-detail/commandCenterChrome'
import { HeaderCondoCheckPanel } from '@/components/lead-detail/HeaderCondoCheckPanel'
import { HeaderLeadScorePanel } from '@/components/lead-detail/HeaderLeadScorePanel'
import {
  PropertyOverviewQuickStats,
  shouldShowCondoCheckCell,
} from '@/components/lead-detail/PropertyOverviewQuickStats'
import type { CommandCenterPayload, PropertyScoreRecord } from '@/types'

const theme = createTheme()

/** Hoyne-style hostile fixture — long Units type + Category + condo + score @ 1280. */
const HOSTILE_PAYLOAD = {
  id: 857859,
  owner_first_name: null,
  owner_last_name: null,
  property_street: '857-859 N Hoyne Ave',
  property_city: 'Chicago',
  property_state: 'IL',
  property_zip: '60622',
  property_type: 'multifamily low-rise (3 floors or less)',
  assessor_aka_street: '857 N Hoyne Ave / 859 N Hoyne Ave',
  lead_status: 'mailing_no_contact_made',
  lead_category: 'Condo / Co-op',
  lead_score: 44,
  assessed_value: null,
  most_recent_sale: '2021-09-15',
  most_recent_sale_price: 1546500,
  units: 12,
  condo_risk_status: 'likely_condo',
  condo_confidence: 'low',
  condo_check_reason: 'Missing PINs / data',
  condo_check_drivers: ['rule_7_missing_data'],
  condo_checked_at: '2026-08-01',
  condo_analysis_id: 99,
  building_ownership_pending: true,
  building_sale_possible: 'unknown',
  has_property_match: true,
  analysis_session_id: null,
  recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
  open_tasks: [],
  timeline: { entries: [], total: 0, page: 1, per_page: 20 },
  contacts: [],
  organizations: [],
} as unknown as CommandCenterPayload

/** Plain residential — short address, no condo, max slack for centering gate. */
const RESIDENTIAL_PAYLOAD = {
  id: 10970,
  owner_first_name: 'Alejandro',
  owner_last_name: 'Carbajal',
  property_street: '2951 N Gresham Ave',
  property_city: 'Chicago',
  property_state: 'IL',
  property_zip: '60618',
  property_type: 'Two to Six Units',
  lead_status: 'skip_trace',
  lead_category: 'residential',
  lead_score: 52,
  assessed_value: 420000,
  most_recent_sale: null,
  most_recent_sale_price: null,
  units: 2,
  condo_risk_status: null,
  condo_confidence: null,
  condo_check_reason: null,
  condo_check_drivers: null,
  condo_checked_at: null,
  condo_analysis_id: null,
  building_ownership_pending: false,
  building_sale_possible: null,
  has_property_match: true,
  analysis_session_id: null,
  recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
  open_tasks: [],
  timeline: { entries: [], total: 0, page: 1, per_page: 20 },
  contacts: [],
  organizations: [],
} as unknown as CommandCenterPayload

const HOSTILE_SCORE: PropertyScoreRecord = {
  id: 1,
  property_id: 857859,
  score_version: 'v1',
  total_score: 44,
  score_tier: 'C',
  data_quality_score: 70,
  recommended_action: 'needs_manual_review',
  top_signals: [
    { dimension: 'mailing_equity', points: 12 },
    { dimension: 'absentee_owner', points: 8 },
    { dimension: 'tax_delinquency', points: 6 },
    { dimension: 'years_owned', points: 5 },
  ],
  score_details: {
    mailing_equity: 12,
    absentee_owner: 8,
    tax_delinquency: 6,
    years_owned: 5,
  },
  missing_data: [],
  created_at: '2026-08-01T12:00:00Z',
}

const RESIDENTIAL_SCORE: PropertyScoreRecord = {
  ...HOSTILE_SCORE,
  property_id: 10970,
  total_score: 52,
  score_tier: 'B',
}

function HarnessHeader({
  payload,
  score,
  addressLine,
}: {
  payload: CommandCenterPayload
  score: PropertyScoreRecord
  addressLine: string
}) {
  const showCondo = shouldShowCondoCheckCell(payload)
  const centerKpis = !showCondo

  return (
    <Box
      component="header"
      data-testid="property-overview-header"
      data-cc-fixture={showCondo ? 'condo-hostile' : 'residential'}
      sx={{
        ...ccHeaderPaperSx,
        width: '100%',
        maxWidth: '100%',
        boxSizing: 'border-box',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexWrap: { xs: 'wrap', md: 'nowrap' },
          alignItems: 'center',
          gap: { xs: 1.25, md: 1.25 },
          minWidth: 0,
          width: '100%',
        }}
      >
        <IconButton
          data-testid="back-button"
          edge="start"
          aria-label="Go back"
          size="small"
          sx={{ mt: 0.25, flex: '0 0 auto' }}
        >
          <ArrowBackIcon />
        </IconButton>
        <Box sx={ccHeaderPrimaryClusterSx} data-testid="cc-header-primary-cluster">
          <Box sx={ccHeaderAddressColumnSx}>
            <Box
              data-testid="property-overview-address"
              sx={{ minWidth: 0, width: { xs: '100%', md: 'auto' }, maxWidth: '100%' }}
            >
              <Typography
                data-testid="property-overview-address-line"
                sx={{
                  ...ccHeroAddressSx,
                  fontSize: '1.35rem',
                  minWidth: 0,
                  maxWidth: '100%',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {addressLine}
              </Typography>
              {showCondo ? (
                <Typography sx={ccHeroSecondarySx} data-testid="property-overview-aka">
                  Also known as: 857 N Hoyne Ave / 859 N Hoyne Ave
                </Typography>
              ) : null}
              <Chip
                size="small"
                label={showCondo ? 'Mailing, No Contact Made' : 'Skip Trace'}
                color="primary"
                data-testid="property-overview-status"
                sx={{ mt: 0.5, height: 22, fontSize: '0.7rem' }}
              />
            </Box>
          </Box>
          <PropertyOverviewQuickStats commandCenterData={payload} centerInGap={centerKpis} />
        </Box>

        <Box
          sx={ccHeaderTrailingPanelsSx}
          data-testid="cc-header-trailing-panels"
          data-cc-trail-mode={centerKpis ? 'grow-score' : 'grow-with-condo'}
        >
          <HeaderCondoCheckPanel commandCenterData={payload} />
          <HeaderLeadScorePanel
            score={score.total_score}
            tier={score.score_tier}
            scoreRecord={score}
          />
        </Box>
      </Box>
    </Box>
  )
}

const params = new URLSearchParams(window.location.search)
const fixture = params.get('fixture') === 'residential' ? 'residential' : 'condo'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ p: 2, bgcolor: 'grey.50', minHeight: '100vh' }}>
        {fixture === 'residential' ? (
          <HarnessHeader
            payload={RESIDENTIAL_PAYLOAD}
            score={RESIDENTIAL_SCORE}
            addressLine="2951 N Gresham Ave, Chicago, IL 60618"
          />
        ) : (
          <HarnessHeader
            payload={HOSTILE_PAYLOAD}
            score={HOSTILE_SCORE}
            addressLine="857-859 N Hoyne Ave, Chicago, IL 60622"
          />
        )}
      </Box>
    </ThemeProvider>
  </StrictMode>,
)
