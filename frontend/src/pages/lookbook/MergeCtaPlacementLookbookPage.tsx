/**
 * DEV lookbook — three candidate placements for the Merge duplicate CTA.
 * Visual mock only (no live merge wiring).
 */
import { useState } from 'react'
import {
  Box,
  Button,
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
import PhoneIcon from '@mui/icons-material/Phone'
import StickyNote2OutlinedIcon from '@mui/icons-material/StickyNote2Outlined'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import LocalPostOfficeOutlinedIcon from '@mui/icons-material/LocalPostOfficeOutlined'
import PersonSearchOutlinedIcon from '@mui/icons-material/PersonSearchOutlined'
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline'
import MergeTypeIcon from '@mui/icons-material/MergeType'
import MoreVertIcon from '@mui/icons-material/MoreVert'
import { ccCardSx, ccHeroAddressSx, ccPageBgSx } from '@/components/lead-detail/commandCenterChrome'

const tileSx = {
  flex: '1 1 0',
  minWidth: 72,
  maxWidth: 120,
  height: 72,
  display: 'flex',
  flexDirection: 'column' as const,
  alignItems: 'center',
  justifyContent: 'center',
  gap: 0.5,
  textTransform: 'none' as const,
  fontSize: '0.7rem',
  lineHeight: 1.15,
  border: 1,
  borderColor: 'divider',
  bgcolor: 'background.paper',
  color: 'text.primary',
  cursor: 'pointer',
}

function FakeHeader({
  showOverflow,
  overflowOpen,
  onOverflowClick,
  overflowAnchor,
  onOverflowClose,
}: {
  showOverflow?: boolean
  overflowOpen?: boolean
  onOverflowClick?: (e: React.MouseEvent<HTMLElement>) => void
  overflowAnchor?: HTMLElement | null
  onOverflowClose?: () => void
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 2,
        flexWrap: 'wrap',
        mb: 1,
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
          {showOverflow ? (
            <>
              <IconButton
                size="small"
                aria-label="Lead options"
                data-testid="merge-placement-overflow-trigger"
                onClick={onOverflowClick}
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
                anchorEl={overflowAnchor ?? null}
                open={Boolean(overflowOpen)}
                onClose={onOverflowClose}
                data-testid="merge-placement-overflow-menu"
              >
                <MenuItem data-testid="merge-placement-overflow-merge" sx={{ cursor: 'pointer' }}>
                  <ListItemIcon>
                    <MergeTypeIcon fontSize="small" />
                  </ListItemIcon>
                  <ListItemText>Merge duplicate…</ListItemText>
                </MenuItem>
                <MenuItem disabled>
                  <ListItemText>Copy lead link</ListItemText>
                </MenuItem>
                <MenuItem disabled>
                  <ListItemText>Open in new tab</ListItemText>
                </MenuItem>
              </Menu>
            </>
          ) : null}
          <Typography variant="caption" color="text.secondary">
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

function ActionCenterMock({ highlightMerge }: { highlightMerge?: boolean }) {
  const tiles: Array<{ label: string; icon: React.ReactNode; merge?: boolean }> = [
    { label: 'Log Call', icon: <PhoneIcon fontSize="small" /> },
    { label: 'Log Note', icon: <StickyNote2OutlinedIcon fontSize="small" /> },
    { label: 'Log Email', icon: <EmailOutlinedIcon fontSize="small" /> },
    { label: 'Mail', icon: <LocalPostOfficeOutlinedIcon fontSize="small" /> },
    { label: 'Skip Trace', icon: <PersonSearchOutlinedIcon fontSize="small" /> },
  ]
  if (highlightMerge) {
    tiles.push({ label: 'Merge duplicate', icon: <MergeTypeIcon fontSize="small" />, merge: true })
  }
  tiles.push({ label: 'Deprioritize', icon: <PauseCircleOutlineIcon fontSize="small" /> })

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Action Center
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        {tiles.map((tile) => (
          <Button
            key={tile.label}
            data-testid={
              tile.merge ? 'merge-placement-action-tile' : `merge-placement-tile-${tile.label}`
            }
            sx={{
              ...tileSx,
              ...(tile.merge
                ? {
                    border: '2px solid',
                    borderColor: 'warning.main',
                    bgcolor: 'rgba(237, 108, 2, 0.08)',
                  }
                : {}),
            }}
          >
            {tile.icon}
            {tile.label}
          </Button>
        ))}
      </Box>
    </Box>
  )
}

function KeyContactMock({ highlightMerge }: { highlightMerge?: boolean }) {
  return (
    <Paper sx={{ ...ccCardSx, p: 2, maxWidth: 320 }} data-testid="merge-placement-key-contact">
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle2">Key Contact</Typography>
        <Button size="small" variant="text" sx={{ cursor: 'pointer' }}>
          + Add person
        </Button>
      </Box>
      <Typography fontWeight={600}>JAMES E MALONE</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        No phone on file
      </Typography>
      <Typography variant="body2" color="text.secondary">
        No email on file
      </Typography>
      <Typography variant="body2" sx={{ mt: 1 }}>
        160 SURREY LANE, BARRINGTON, IL 60010
      </Typography>
      <Stack spacing={1} sx={{ mt: 1.5 }}>
        <Button size="small" variant="outlined" sx={{ cursor: 'pointer', justifyContent: 'flex-start' }}>
          Edit phone & details
        </Button>
        {highlightMerge ? (
          <Button
            size="small"
            variant="outlined"
            startIcon={<MergeTypeIcon />}
            data-testid="merge-placement-key-contact-merge"
            sx={{
              cursor: 'pointer',
              justifyContent: 'flex-start',
              border: '2px solid',
              borderColor: 'warning.main',
              bgcolor: 'rgba(237, 108, 2, 0.08)',
            }}
          >
            Merge duplicate…
          </Button>
        ) : null}
      </Stack>
    </Paper>
  )
}

export default function MergeCtaPlacementLookbookPage() {
  const [overflowAnchor, setOverflowAnchor] = useState<HTMLElement | null>(null)

  return (
    <Box sx={{ ...ccPageBgSx, p: 2, minHeight: '100vh' }} data-testid="merge-cta-placement-lookbook">
      <Typography variant="h5" sx={{ mb: 1 }}>
        Merge duplicate — placement options
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Product choice: <strong>Option 2</strong> (header ⋯). Options 1 and 3 kept for
        comparison only.
      </Typography>

      <Stack spacing={3} maxWidth={980}>
        <Paper sx={{ ...ccCardSx, p: 2 }} data-testid="merge-placement-option-1">
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>
            Option 1 — Action Center tile
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Sits with Log Call / Mail / Skip Trace — most visible for a normal workflow action.
          </Typography>
          <FakeHeader />
          <ActionCenterMock highlightMerge />
        </Paper>

        <Paper
          sx={{ ...ccCardSx, p: 2, border: '2px solid', borderColor: 'success.main' }}
          data-testid="merge-placement-option-2"
        >
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>
            Option 2 — Header overflow (⋯) next to status (chosen)
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Quiet but always available. Click the highlighted ⋯ next to the status chip.
          </Typography>
          <FakeHeader
            showOverflow
            overflowOpen={Boolean(overflowAnchor)}
            overflowAnchor={overflowAnchor}
            onOverflowClick={(e) => setOverflowAnchor(e.currentTarget)}
            onOverflowClose={() => setOverflowAnchor(null)}
          />
          <ActionCenterMock />
        </Paper>

        <Paper sx={{ ...ccCardSx, p: 2 }} data-testid="merge-placement-option-3">
          <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 0.5 }}>
            Option 3 — Key Contact card (right rail)
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Next to people / mailing cleanup — framed as same owner + building hygiene.
          </Typography>
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <Box sx={{ flex: 1, minWidth: 280 }}>
              <FakeHeader />
              <ActionCenterMock />
            </Box>
            <KeyContactMock highlightMerge />
          </Box>
        </Paper>
      </Stack>
    </Box>
  )
}
