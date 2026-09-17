/**
 * DEV lookbook — same-address merge entry (Option 2: header ⋯ overflow).
 */
import { useState } from 'react'
import {
  Box,
  Chip,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import MergeTypeIcon from '@mui/icons-material/MergeType'
import { SameAddressMergeBanner } from '@/components/lead-detail/SameAddressMergeBanner'
import { ccCardSx, ccHeroAddressSx, ccPageBgSx } from '@/components/lead-detail/commandCenterChrome'
import type { SameAddressLeadSummary } from '@/types'

const CURRENT_PEOPLE = ['JAMES E MALONE']

const TWIN: SameAddressLeadSummary = {
  id: 2497,
  property_street: '1867-1869 N Howe St',
  owner_display_name: 'JAMES E MALONE',
  people_names: ['JAMES E MALONE'],
}

function FakeCommandCenterHeader({
  mergeOpen,
  onOpenMerge,
}: {
  mergeOpen: boolean
  onOpenMerge: () => void
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const menuOpen = Boolean(anchor)

  return (
    <Box
      data-testid="merge-lookbook-cc-header"
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 2,
        flexWrap: 'wrap',
        mb: 0.5,
      }}
    >
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography sx={ccHeroAddressSx}>1867 N Howe St, Chicago, IL 60614</Typography>
        <Typography variant="body1" sx={{ mt: 0.25, fontWeight: 600 }}>
          JAMES E MALONE
        </Typography>
        <Typography variant="caption" color="text.secondary">
          PIN 14-33-303-031-0000
        </Typography>
        <Box sx={{ mt: 0.75, display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
          <Chip size="small" color="primary" label="Mailing, No Contact Made" />
          <IconButton
            size="small"
            aria-label="Lead options"
            data-testid="lead-header-overflow-menu"
            onClick={(event) => setAnchor(event.currentTarget)}
            sx={{
              cursor: 'pointer',
              border: '2px solid',
              borderColor: 'warning.main',
              bgcolor: 'rgba(237, 108, 2, 0.08)',
            }}
          >
            <MoreVertIcon fontSize="small" />
          </IconButton>
          <Menu
            anchorEl={anchor}
            open={menuOpen}
            onClose={() => setAnchor(null)}
            data-testid="lead-header-overflow-menu-panel"
          >
            <MenuItem
              data-testid="same-address-merge-menu-item"
              selected={mergeOpen}
              onClick={() => {
                setAnchor(null)
                onOpenMerge()
              }}
              sx={{ cursor: 'pointer' }}
            >
              <ListItemIcon>
                <MergeTypeIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText>Merge duplicate…</ListItemText>
            </MenuItem>
          </Menu>
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
            Last Sale 08/21/1998 · 2 Units · Duplex · Residential
          </Typography>
        </Box>
      </Box>
      <Box
        sx={{
          width: 88,
          height: 88,
          borderRadius: '50%',
          border: '6px solid',
          borderColor: 'success.light',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Typography variant="h5" fontWeight={700} lineHeight={1}>
          60
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Good Fit
        </Typography>
      </Box>
    </Box>
  )
}

export default function SameAddressMergeLookbookPage() {
  const [lastMerged, setLastMerged] = useState<string | null>(null)
  const [manualOpen, setManualOpen] = useState(false)
  const [autoOpen, setAutoOpen] = useState(false)

  return (
    <Box sx={{ ...ccPageBgSx, p: 2, minHeight: '100vh' }} data-testid="merge-lookbook">
      <Typography variant="h5" sx={{ mb: 1 }}>
        Same-address merge — header ⋯ placement
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        On <code>/leads/:id</code>, open <strong>⋯</strong> next to the status chip →{' '}
        <strong>Merge duplicate…</strong>. When a twin is auto-detected, a blue banner also
        offers <strong>Merge</strong>.
      </Typography>
      {lastMerged ? (
        <Typography variant="body2" sx={{ mb: 2 }} data-testid="merge-lookbook-last">
          Last combine: {lastMerged}
        </Typography>
      ) : null}

      <Stack spacing={3} maxWidth={980}>
        <Paper sx={{ ...ccCardSx, p: 2 }} data-testid="merge-lookbook-cc-placement">
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Manual entry (no auto twin) — ⋯ next to status
          </Typography>
          <FakeCommandCenterHeader
            mergeOpen={manualOpen}
            onOpenMerge={() => setManualOpen(true)}
          />
          <SameAddressMergeBanner
            leadId={2496}
            twins={[]}
            open={manualOpen}
            onOpenChange={setManualOpen}
            currentOwnerLabel="JAMES E MALONE"
            currentPeopleNames={CURRENT_PEOPLE}
            onMerged={({ winnerId, loserId }) => {
              setLastMerged(`#${loserId} → #${winnerId}`)
            }}
          />
          <Box
            sx={{
              mt: 1.5,
              p: 1.5,
              borderRadius: 1,
              bgcolor: 'grey.50',
              border: '1px dashed',
              borderColor: 'divider',
            }}
          >
            <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
              Action Center
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Log Call · Log Note · Log Email · Mail · Skip Trace · Deprioritize
            </Typography>
          </Box>
        </Paper>

        <Paper sx={{ ...ccCardSx, p: 2 }} data-testid="merge-lookbook-auto">
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>
            When a twin is auto-detected
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Blue banner with <strong>Merge</strong> (⋯ menu still available).
          </Typography>
          <FakeCommandCenterHeader mergeOpen={autoOpen} onOpenMerge={() => setAutoOpen(true)} />
          <SameAddressMergeBanner
            leadId={2496}
            twins={[TWIN]}
            open={autoOpen}
            onOpenChange={setAutoOpen}
            currentOwnerLabel="JAMES E MALONE"
            currentPeopleNames={CURRENT_PEOPLE}
            onMerged={({ winnerId, loserId }) => {
              setLastMerged(`#${loserId} → #${winnerId}`)
            }}
          />
        </Paper>
      </Stack>
    </Box>
  )
}
