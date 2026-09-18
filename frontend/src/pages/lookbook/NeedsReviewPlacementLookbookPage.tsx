/**
 * DEV lookbook — three placements for Needs Review “Possible duplicate records”
 * (no top banner). Visual mock only.
 */
import { useState } from 'react'
import {
  Box,
  Button,
  Chip,
  Divider,
  Link,
  Paper,
  Popover,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material'
import MergeTypeIcon from '@mui/icons-material/MergeType'
import CloseIcon from '@mui/icons-material/Close'
import { ccCardSx, ccHeroAddressSx, ccPageBgSx } from '@/components/lead-detail/commandCenterChrome'

const REASON = 'Possible duplicate records'
const DETAIL =
  'Same owner + same building may be listed more than once. Confirm which record to keep.'

function CurrentQueuesLine({
  viewingFrom = 'Needs Review',
  queues = ['Needs Review', 'No Next Action'],
  needsReviewInteractive,
  onNeedsReviewClick,
}: {
  viewingFrom?: string
  queues?: string[]
  needsReviewInteractive?: boolean
  onNeedsReviewClick?: (e: React.MouseEvent<HTMLElement>) => void
}) {
  return (
    <Typography
      variant="caption"
      data-testid="lookbook-current-queues"
      sx={{ fontSize: '0.65rem', lineHeight: 1.35, color: 'text.secondary', mt: 0.5 }}
    >
      <Box component="span" sx={{ fontWeight: 700 }}>
        Current queues:{' '}
      </Box>
      {queues.map((name, index) => {
        const viewing = name === viewingFrom
        const isNeedsReview = name === 'Needs Review'
        return (
          <Box component="span" key={name}>
            {index > 0 ? ', ' : null}
            {isNeedsReview && needsReviewInteractive ? (
              <Box
                component="button"
                type="button"
                data-testid="lookbook-needs-review-chip"
                onClick={onNeedsReviewClick}
                sx={{
                  font: 'inherit',
                  fontWeight: viewing ? 700 : 400,
                  color: viewing ? 'text.primary' : 'text.secondary',
                  cursor: 'pointer',
                  border: 0,
                  bgcolor: 'transparent',
                  p: 0,
                  textDecoration: 'underline',
                }}
              >
                {viewing ? <strong>{name}</strong> : name}
              </Box>
            ) : (
              <Box
                component="span"
                data-testid={
                  isNeedsReview ? 'lookbook-needs-review-chip-static' : undefined
                }
                sx={{ fontWeight: viewing ? 700 : 400, color: viewing ? 'text.primary' : 'inherit' }}
              >
                {viewing ? <strong>{name}</strong> : name}
              </Box>
            )}
          </Box>
        )
      })}
    </Typography>
  )
}

function FakeHeader({
  needsReviewInteractive,
  onNeedsReviewClick,
}: {
  needsReviewInteractive?: boolean
  onNeedsReviewClick?: (e: React.MouseEvent<HTMLElement>) => void
} = {}) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 2 }}>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography sx={ccHeroAddressSx}>100 Live UI Smoke St, Chicago, IL 60601</Typography>
        <Typography variant="body1" sx={{ mt: 0.25, fontWeight: 600 }}>
          Live UI
        </Typography>
        <Typography variant="caption" color="text.secondary">
          PIN 00-00-000-000-0000
        </Typography>
        <Box sx={{ mt: 0.75 }}>
          <Chip size="small" color="primary" label="Skip Trace" />
        </Box>
      </Box>
      <Box
        sx={{
          minWidth: 160,
          maxWidth: 220,
          py: 1,
          px: 1.5,
          borderRadius: 1,
          border: '1px solid',
          borderColor: 'divider',
          bgcolor: 'background.paper',
        }}
        data-testid="lookbook-lead-signals-box"
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box
            sx={{
              width: 56,
              height: 56,
              borderRadius: '50%',
              border: '5px solid',
              borderColor: 'warning.light',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <Typography variant="h6" fontWeight={700} lineHeight={1}>
              35
            </Typography>
            <Typography variant="caption" color="text.secondary" fontSize="0.65rem">
              Low
            </Typography>
          </Box>
          <Typography
            variant="caption"
            fontWeight={700}
            color="text.secondary"
            sx={{ textTransform: 'uppercase', letterSpacing: 0.04, fontSize: '0.65rem' }}
          >
            Lead signals / score
          </Typography>
        </Box>
        <CurrentQueuesLine
          needsReviewInteractive={needsReviewInteractive}
          onNeedsReviewClick={onNeedsReviewClick}
        />
      </Box>
    </Box>
  )
}

function DuplicateActionsCompact() {
  return (
    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
      <Button size="small" variant="contained" startIcon={<MergeTypeIcon />}>
        Keep suggested (#99)
      </Button>
      <Button size="small" variant="outlined" startIcon={<CloseIcon />}>
        Not a duplicate
      </Button>
    </Box>
  )
}

function ClusterMiniTable() {
  return (
    <Table size="small" sx={{ mt: 1 }}>
      <TableHead>
        <TableRow>
          <TableCell>Lead</TableCell>
          <TableCell>Street</TableCell>
          <TableCell>Signals</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        <TableRow>
          <TableCell>
            <Typography variant="body2" fontWeight={600}>
              #1 (this lead)
            </Typography>
          </TableCell>
          <TableCell>100 Live UI Smoke St</TableCell>
          <TableCell>phone</TableCell>
        </TableRow>
        <TableRow selected>
          <TableCell>
            <Link underline="hover" variant="body2">
              #99
            </Link>{' '}
            <Chip size="small" label="Suggested keep" sx={{ ml: 0.5 }} />
          </TableCell>
          <TableCell>100 Live UI Smoke St Unit 2</TableCell>
          <TableCell>HubSpot · phone · email</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  )
}

/** Option 1 — popover on the Needs Review chip (header stays quiet). */
function OptionChipPopover() {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const open = Boolean(anchor)

  return (
    <Paper
      sx={{ ...ccCardSx, p: 2 }}
      data-testid="lookbook-option-chip-popover"
      data-live-ui-surface
    >
      <Typography variant="overline" color="text.secondary">
        Option 1 — Needs Review chip popover
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Click Needs Review in the score box for reason + actions. No banner in the header stack.
      </Typography>
      <FakeHeader
        needsReviewInteractive
        onNeedsReviewClick={(e) => setAnchor(e.currentTarget)}
      />
      <Popover
        open={open}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        PaperProps={{ 'data-testid': 'lookbook-needs-review-popover' } as object}
      >
        <Box sx={{ p: 2, width: 360, maxWidth: '90vw' }}>
          <Typography variant="subtitle2" fontWeight={700}>
            {REASON}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {DETAIL}
          </Typography>
          <ClusterMiniTable />
          <DuplicateActionsCompact />
        </Box>
      </Popover>
    </Paper>
  )
}

/** Option 2 — folded into the same-address merge banner area. */
function OptionMergeBanner() {
  return (
    <Paper
      sx={{ ...ccCardSx, p: 2 }}
      data-testid="lookbook-option-merge-banner"
      data-live-ui-surface
    >
      <Typography variant="overline" color="text.secondary">
        Shipped — Same-address merge area (always-visible comparison)
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Possible duplicate records show a this-vs-other comparison and Merge on
        Command Center — not buried in the Needs Review chip.
      </Typography>
      <FakeHeader />
      <Box
        data-testid="lookbook-merge-review-banner"
        sx={{
          mt: 1.5,
          px: 1.5,
          py: 1.25,
          borderRadius: 1,
          bgcolor: 'rgba(2, 136, 209, 0.08)',
          border: '1px solid',
          borderColor: 'info.light',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 1.5,
        }}
      >
        <Box sx={{ flex: 1, minWidth: 200 }}>
          <Typography variant="subtitle2" fontWeight={700} color="info.dark">
            {REASON}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {DETAIL} Suggested keep: lead #99.
          </Typography>
        </Box>
        <Button size="small" variant="contained" color="info" startIcon={<MergeTypeIcon />}>
          Review duplicates
        </Button>
        <Button size="small" variant="text" color="inherit">
          Not a duplicate
        </Button>
      </Box>
    </Paper>
  )
}

/** Option 3 — Property Sidebar Work Queues section. */
function OptionSidebar() {
  return (
    <Paper
      sx={{ ...ccCardSx, p: 2 }}
      data-testid="lookbook-option-sidebar"
      data-live-ui-surface
    >
      <Typography variant="overline" color="text.secondary">
        Option 3 — Property Sidebar
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Header score box lists current queues; reason + actions sit under Work Queues in the sidebar.
      </Typography>
      <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <FakeHeader />
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            Recommended Action / Open Tasks would continue below — no review banner here.
          </Typography>
        </Box>
        <Paper
          variant="outlined"
          sx={{ width: 280, flexShrink: 0, p: 1.5 }}
          data-testid="lookbook-sidebar-work-queues"
        >
          <Typography
            variant="overline"
            sx={{ fontSize: '0.65rem', letterSpacing: 1, color: 'text.disabled' }}
          >
            Work Queues
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5, mb: 1 }}>
            <Chip size="small" color="warning" label="Needs Review" />
            <Chip size="small" label="No Next Action" />
          </Box>
          <Divider sx={{ my: 1 }} />
          <Typography variant="caption" color="text.secondary" display="block">
            Needs Review reason
          </Typography>
          <Typography variant="body2" fontWeight={700} sx={{ mt: 0.25 }}>
            {REASON}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
            {DETAIL}
          </Typography>
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
            Related: <Link underline="hover">#99</Link> (suggested keep)
          </Typography>
          <DuplicateActionsCompact />
        </Paper>
      </Box>
    </Paper>
  )
}

export default function NeedsReviewPlacementLookbookPage() {
  return (
    <Box sx={{ ...ccPageBgSx, p: 3, minHeight: '100vh' }} data-testid="needs-review-placement-lookbook">
      <Typography variant="h5" fontWeight={700} gutterBottom>
        Needs Review placement options
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3, maxWidth: 720 }}>
        Wording locked to <strong>{REASON}</strong>. Duplicate clusters use the
        always-visible comparison callout (option 2). Chip popover remains for
        other Needs Review reasons.
      </Typography>
      <Stack spacing={3}>
        <OptionChipPopover />
        <OptionMergeBanner />
        <OptionSidebar />
      </Stack>
    </Box>
  )
}
