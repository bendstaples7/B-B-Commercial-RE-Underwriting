/**
 * Hostile CC header packing harness — real MUI + production packing tokens.
 * Served by Vite for Playwright geometry / paint gates (not a static HTML twin).
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Box, Chip, CssBaseline, Typography } from '@mui/material'
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
import { PropertyOverviewQuickStats } from '@/components/lead-detail/PropertyOverviewQuickStats'
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

function HarnessHeader() {
  return (
    <Box
      component="header"
      data-testid="property-overview-header"
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
          // Match production ULCC: one horizontal bar on md+.
          flexWrap: { xs: 'wrap', md: 'nowrap' },
          alignItems: 'center',
          gap: { xs: 1.25, md: 1.25 },
          minWidth: 0,
          width: '100%',
        }}
      >
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
                857-859 N Hoyne Ave, Chicago, IL 60622
              </Typography>
              <Typography sx={ccHeroSecondarySx} data-testid="property-overview-aka">
                Also known as: 857 N Hoyne Ave / 859 N Hoyne Ave
              </Typography>
              <Chip
                size="small"
                label="Mailing, No Contact Made"
                color="primary"
                data-testid="property-overview-status"
                sx={{ mt: 0.5, height: 22, fontSize: '0.7rem' }}
              />
            </Box>
          </Box>
          <PropertyOverviewQuickStats commandCenterData={HOSTILE_PAYLOAD} />
        </Box>

        <Box sx={ccHeaderTrailingPanelsSx} data-testid="cc-header-trailing-panels">
          <HeaderCondoCheckPanel commandCenterData={HOSTILE_PAYLOAD} />
          <HeaderLeadScorePanel
            score={HOSTILE_SCORE.total_score}
            tier={HOSTILE_SCORE.score_tier}
            scoreRecord={HOSTILE_SCORE}
          />
        </Box>
      </Box>
    </Box>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ p: 2, bgcolor: 'grey.50', minHeight: '100vh' }}>
        <HarnessHeader />
      </Box>
    </ThemeProvider>
  </StrictMode>,
)
