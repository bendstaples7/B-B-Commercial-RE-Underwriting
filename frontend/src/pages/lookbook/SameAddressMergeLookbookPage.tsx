/**
 * DEV lookbook — same-address merge entry points (banner vs Merge duplicate…).
 */
import { useState } from 'react'
import { Box, Paper, Stack, Typography } from '@mui/material'
import { SameAddressMergeBanner } from '@/components/lead-detail/SameAddressMergeBanner'
import { ccCardSx, ccPageBgSx } from '@/components/lead-detail/commandCenterChrome'
import type { SameAddressLeadSummary } from '@/types'

const CURRENT_PEOPLE = ['JAMES E MALONE']

const TWIN: SameAddressLeadSummary = {
  id: 2497,
  property_street: '1867-1869 N Howe St',
  owner_display_name: 'JAMES E MALONE',
  people_names: ['JAMES E MALONE'],
}

export default function SameAddressMergeLookbookPage() {
  const [lastMerged, setLastMerged] = useState<string | null>(null)

  return (
    <Box sx={{ ...ccPageBgSx, p: 2, minHeight: '100vh' }} data-testid="merge-lookbook">
      <Typography variant="h5" sx={{ mb: 1 }}>
        Same-address merge lookbook
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        What you will see on Command Center for leads like 2496 / 2497.
      </Typography>
      {lastMerged ? (
        <Typography variant="body2" sx={{ mb: 2 }} data-testid="merge-lookbook-last">
          Last combine: {lastMerged}
        </Typography>
      ) : null}

      <Stack spacing={3} maxWidth={900}>
        <Paper sx={{ ...ccCardSx, p: 2 }} data-testid="merge-lookbook-manual">
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>
            A — No auto-detected twin (today on 2496)
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Top-right of the header stack: Merge duplicate…
          </Typography>
          <Box
            sx={{
              border: '1px dashed',
              borderColor: 'divider',
              borderRadius: 1,
              p: 1.5,
              bgcolor: 'background.paper',
            }}
          >
            <Typography variant="h6" sx={{ mb: 0.5 }}>
              1867 N Howe St, Chicago, IL 60614
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              JAMES E MALONE · PIN 14-33-303-031-0000
            </Typography>
            <SameAddressMergeBanner
              leadId={2496}
              twins={[]}
              currentOwnerLabel="JAMES E MALONE"
              currentPeopleNames={CURRENT_PEOPLE}
              onMerged={({ winnerId, loserId }) => {
                setLastMerged(`#${loserId} → #${winnerId}`)
              }}
            />
          </Box>
        </Paper>

        <Paper sx={{ ...ccCardSx, p: 2 }} data-testid="merge-lookbook-auto">
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>
            B — Twin detected (after dual-number matching ships)
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Blue banner with Merge
          </Typography>
          <Box
            sx={{
              border: '1px dashed',
              borderColor: 'divider',
              borderRadius: 1,
              p: 1.5,
              bgcolor: 'background.paper',
            }}
          >
            <Typography variant="h6" sx={{ mb: 0.5 }}>
              1867 N Howe St, Chicago, IL 60614
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              JAMES E MALONE · PIN 14-33-303-031-0000
            </Typography>
            <SameAddressMergeBanner
              leadId={2496}
              twins={[TWIN]}
              currentOwnerLabel="JAMES E MALONE"
              currentPeopleNames={CURRENT_PEOPLE}
              onMerged={({ winnerId, loserId }) => {
                setLastMerged(`#${loserId} → #${winnerId}`)
              }}
            />
          </Box>
        </Paper>
      </Stack>
    </Box>
  )
}
