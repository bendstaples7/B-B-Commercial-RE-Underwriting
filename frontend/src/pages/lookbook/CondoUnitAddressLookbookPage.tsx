/**
 * DEV lookbook — property address edit + dismiss incorrect recent sale.
 */
import { useState } from 'react'
import { Box, Paper, Stack, Typography } from '@mui/material'
import { PropertySidebar } from '@/components/lead-detail/PropertySidebar'
import { RecommendedActionPanel } from '@/components/RecommendedActionPanel'
import { ccCardSx, ccPageBgSx } from '@/components/lead-detail/commandCenterChrome'
import type { CommandCenterPayload } from '@/types'

const FAKE_PAYLOAD = {
  id: 113834,
  owner_first_name: 'Alex',
  owner_last_name: 'Owner',
  property_street: '717 W Bittersweet Pl',
  address_2: 'Unit L2',
  property_city: 'Chicago',
  property_state: 'IL',
  property_zip: '60613',
  property_type: 'Condo',
  county_assessor_pin: '14163050211081',
  is_cook_county_eligible: true,
  lead_status: 'skip_trace',
  lead_category: 'residential',
  lead_score: 38,
  most_recent_sale: '2025-11-01',
  most_recent_sale_display: '11/01/2025',
  most_recent_sale_price: 425000,
  contacts_likely_prior_owner: true,
  contacts: [
    {
      id: 1,
      first_name: 'Alex',
      last_name: 'Owner',
      role: 'owner',
      is_primary: true,
      phones: [{ id: 1, value: '(312) 555-0100', label: 'mobile', confidence_score: 40 }],
      emails: [],
    },
  ],
  phones: [],
  organizations: [],
} as unknown as CommandCenterPayload

export default function CondoUnitAddressLookbookPage() {
  const [dismissed, setDismissed] = useState(false)

  return (
    <Box sx={{ ...ccPageBgSx, p: 2, minHeight: '100vh' }} data-testid="condo-unit-address-lookbook">
      <Typography variant="h6" sx={{ mb: 2 }}>
        Condo unit address + dismiss recent sale
      </Typography>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="flex-start">
        <Paper sx={{ ...ccCardSx, p: 2, flex: 1, minWidth: 0 }} data-testid="lookbook-ra-panel">
          <RecommendedActionPanel
            recommendedAction={{
              value: 'hold',
              label: 'Recent-sale hold',
              explanation:
                'Because of a recent sale, the owner and mailing details on file are likely tied to the prior owner.',
              winning_rule: 'recent_sale_hold',
              signals: {},
            }}
            leadStatus="skip_trace"
            openTasks={[]}
            isMailable
            mailEligible={false}
            mailIneligibleReason={dismissed ? null : 'recently_sold'}
            mailEligibleDate="2027-11-01"
            contactsLikelyPriorOwner={!dismissed}
            embedded
            showActionCenterTiles
            onAction={async () => undefined}
            onDismissRecentSale={
              dismissed
                ? undefined
                : async () => {
                    setDismissed(true)
                  }
            }
          />
        </Paper>
        <Box sx={{ width: { xs: '100%', md: 340 }, flexShrink: 0 }}>
          <PropertySidebar commandCenterData={FAKE_PAYLOAD} />
        </Box>
      </Stack>
    </Box>
  )
}
