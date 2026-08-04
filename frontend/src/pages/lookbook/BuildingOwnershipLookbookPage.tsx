/**
 * DEV lookbook — Building ownership card layout alternatives.
 * Static mocks using Command Center tokens. Vote A / B / C before production.
 */
import { useMemo, useState } from 'react'
import {
  Box,
  Button,
  Chip,
  Divider,
  Paper,
  Stack,
  Tab,
  Tabs,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material'
import {
  ccCardSx,
  ccMetaSx,
  ccPageBgSx,
  ccSectionTitleSx,
  ccSubsectionTitleSx,
} from '@/components/lead-detail/commandCenterChrome'

type Variant = 'a' | 'b' | 'c'

const FAKE = {
  title: 'Building ownership',
  condoized: 'unclear' as const,
  confidence: 'low',
  lastChecked: 'Jul 1, 2026 12:00 PM',
  units: '12 units',
  sale: '01/15/2019 · $1.2M',
  pin: '14-20-123-456-0000 · Class 3-18',
  salePossible: 'Unknown',
  systemNote: 'Incomplete data (missing PINs) — cannot classify reliably',
  pinExplain: '3 PINs at this address · no condo class. Imported units: 12. Multiple PINs alone do not mean condo.',
  pins: [
    { pin: '14-20-123-456-0000', address: '3508 N Sacramento Ave', cls: '3-18', condo: 'No' },
    { pin: '14-20-123-457-0000', address: '3508 N Sacramento Ave Unit 2', cls: '3-18', condo: 'No' },
    { pin: '14-20-123-458-0000', address: '3508 N Sacramento Ave Unit 3', cls: '2-11', condo: 'No' },
  ],
}

const VARIANT_COPY: Record<Variant, { label: string; blurb: string }> = {
  a: {
    label: 'A · Split header + metric strip',
    blurb: 'Title left / last-checked right. Condoized + chips on one row. Units · Sale · PIN as three equal cells.',
  },
  b: {
    label: 'B · CTA in header',
    blurb: 'Title left / Run check right (Open Tasks pattern). Condoized row with confidence flush right. Compact 2×2 facts.',
  },
  c: {
    label: 'C · Verdict band',
    blurb: 'Title + status chip. Condoized toggles spaced across the row. Single-line stats with dividers; note + sale on one row.',
  },
}

function LookbookFrame({
  label,
  width,
  children,
}: {
  label: string
  width: 1024 | 390
  children: React.ReactNode
}) {
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 }}>
      <Typography
        sx={{
          fontSize: '0.65rem',
          fontWeight: 600,
          letterSpacing: 0.08,
          textTransform: 'uppercase',
          color: 'text.secondary',
        }}
      >
        {label}
      </Typography>
      <Box
        sx={{
          width,
          maxWidth: '100%',
          overflow: 'hidden',
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          bgcolor: 'grey.50',
          boxShadow: '0 1px 2px rgba(16, 24, 40, 0.04)',
          p: 2,
        }}
      >
        {children}
      </Box>
    </Box>
  )
}

function FakeToggles({ value }: { value: string }) {
  return (
    <ToggleButtonGroup exclusive size="small" value={value} onChange={() => undefined}>
      <ToggleButton value="yes" sx={{ cursor: 'default' }}>
        Yes
      </ToggleButton>
      <ToggleButton value="no" sx={{ cursor: 'default' }}>
        No
      </ToggleButton>
      <ToggleButton value="unclear" sx={{ cursor: 'default' }}>
        Unclear
      </ToggleButton>
    </ToggleButtonGroup>
  )
}

function PinTable() {
  return (
    <Table size="small" sx={{ minWidth: 420 }}>
      <TableHead>
        <TableRow>
          <TableCell>PIN</TableCell>
          <TableCell>Address</TableCell>
          <TableCell>Class</TableCell>
          <TableCell>Condo signal</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {FAKE.pins.map((row) => (
          <TableRow key={row.pin}>
            <TableCell>{row.pin}</TableCell>
            <TableCell>{row.address}</TableCell>
            <TableCell>{row.cls}</TableCell>
            <TableCell>{row.condo}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ minWidth: 0, px: { sm: 1.5 }, py: 0.75 }}>
      <Typography sx={{ ...ccMetaSx, mb: 0.25, fontSize: '0.7rem' }}>{label}</Typography>
      <Typography variant="body2" fontWeight={500} noWrap title={value}>
        {value}
      </Typography>
    </Box>
  )
}

function BuildingOwnershipLookbookSurface({ variant }: { variant: Variant }) {
  const cardSx = { ...ccCardSx, mb: 0 }

  if (variant === 'a') {
    return (
      <Paper sx={cardSx} data-variant="a" data-testid="lookbook-bo-surface">
        <Stack
          direction="row"
          alignItems="flex-start"
          justifyContent="space-between"
          gap={1}
          sx={{ mb: 1.5 }}
        >
          <Typography sx={{ ...ccSectionTitleSx, mb: 0 }} component="h2">
            {FAKE.title}
          </Typography>
          <Typography sx={{ ...ccMetaSx, textAlign: 'right', flexShrink: 0 }}>
            Last check {FAKE.lastChecked}
          </Typography>
        </Stack>

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          alignItems={{ xs: 'flex-start', sm: 'center' }}
          justifyContent="space-between"
          gap={1}
          sx={{ mb: 1.5 }}
        >
          <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
            <Typography variant="body2" fontWeight={600}>
              Condoized?
            </Typography>
            <FakeToggles value={FAKE.condoized} />
          </Stack>
          <Stack direction="row" gap={0.75} flexWrap="wrap" justifyContent="flex-end">
            <Chip size="small" variant="outlined" label={`${FAKE.confidence} confidence`} />
            <Chip size="small" variant="outlined" label={`Sale possible: ${FAKE.salePossible}`} />
          </Stack>
        </Stack>

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr 1fr' },
            border: 1,
            borderColor: 'divider',
            borderRadius: 1,
            mb: 1.5,
            '& > *:not(:last-of-type)': {
              borderRight: { sm: '1px solid' },
              borderColor: { sm: 'divider' },
              borderBottom: { xs: '1px solid', sm: 'none' },
              borderBottomColor: { xs: 'divider' },
            },
          }}
        >
          <MetricCell label="Imported units" value={FAKE.units} />
          <MetricCell label="Most recent sale" value={FAKE.sale} />
          <MetricCell label="Lead PIN" value={FAKE.pin} />
        </Box>

        <Typography sx={{ ...ccMetaSx, mb: 1.5 }}>{FAKE.systemNote}</Typography>

        <Typography sx={ccSubsectionTitleSx}>PINs at address (3)</Typography>
        <Typography sx={{ ...ccMetaSx, mb: 1 }}>{FAKE.pinExplain}</Typography>
        <Box sx={{ mb: 1.5, overflowX: 'auto' }}>
          <PinTable />
        </Box>

        <Divider sx={{ my: 1.5 }} />
        <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
          <Button variant="outlined" size="small" sx={{ cursor: 'default' }}>
            Re-run automated check
          </Button>
          <Button variant="text" size="small" sx={{ cursor: 'default' }}>
            Advanced ownership form
          </Button>
        </Stack>
      </Paper>
    )
  }

  if (variant === 'b') {
    return (
      <Paper sx={cardSx} data-variant="b" data-testid="lookbook-bo-surface">
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          gap={1}
          sx={{ mb: 1.5 }}
        >
          <Typography sx={{ ...ccSectionTitleSx, mb: 0 }} component="h2">
            {FAKE.title}
          </Typography>
          <Button variant="outlined" size="small" sx={{ cursor: 'default', flexShrink: 0 }}>
            Re-run check
          </Button>
        </Stack>

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          alignItems={{ xs: 'flex-start', sm: 'center' }}
          justifyContent="space-between"
          gap={1}
          sx={{ mb: 1.5 }}
        >
          <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
            <Typography variant="body2" fontWeight={600}>
              Condoized?
            </Typography>
            <FakeToggles value={FAKE.condoized} />
          </Stack>
          <Chip size="small" variant="outlined" label={`${FAKE.confidence} confidence`} />
        </Stack>

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
            columnGap: 2,
            rowGap: 1,
            mb: 1.5,
          }}
        >
          <MetricCell label="Imported units" value={FAKE.units} />
          <MetricCell label="Most recent sale" value={FAKE.sale} />
          <MetricCell label="Lead PIN" value={FAKE.pin} />
          <MetricCell label="Whole-building sale" value={FAKE.salePossible} />
        </Box>

        <Box
          sx={{
            px: 1.5,
            py: 1,
            mb: 1.5,
            borderRadius: 1,
            bgcolor: 'action.hover',
          }}
        >
          <Typography sx={{ ...ccMetaSx, mb: 0, fontSize: '0.75rem' }}>System note</Typography>
          <Typography variant="body2">{FAKE.systemNote}</Typography>
        </Box>

        <Typography sx={ccSubsectionTitleSx}>PINs at address (3)</Typography>
        <Typography sx={{ ...ccMetaSx, mb: 1 }}>{FAKE.pinExplain}</Typography>
        <Box sx={{ mb: 1.5, overflowX: 'auto' }}>
          <PinTable />
        </Box>

        <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
          <Typography sx={ccMetaSx}>Last check {FAKE.lastChecked}</Typography>
          <Button variant="text" size="small" sx={{ cursor: 'default' }}>
            Advanced ownership form
          </Button>
        </Stack>
      </Paper>
    )
  }

  // variant C
  return (
    <Paper sx={cardSx} data-variant="c" data-testid="lookbook-bo-surface">
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        gap={1}
        sx={{ mb: 1.5 }}
        flexWrap="wrap"
      >
        <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
          <Typography sx={{ ...ccSectionTitleSx, mb: 0 }} component="h2">
            {FAKE.title}
          </Typography>
          <Chip size="small" color="warning" variant="outlined" label="Needs more research" />
        </Stack>
        <Chip size="small" variant="outlined" label={`${FAKE.confidence} confidence`} />
      </Stack>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        alignItems={{ xs: 'stretch', sm: 'center' }}
        justifyContent="space-between"
        gap={1}
        sx={{ mb: 1.5 }}
      >
        <Typography variant="body2" fontWeight={600} sx={{ flexShrink: 0 }}>
          Condoized?
        </Typography>
        <Box sx={{ flex: 1, display: 'flex', justifyContent: { xs: 'flex-start', sm: 'flex-end' } }}>
          <FakeToggles value={FAKE.condoized} />
        </Box>
      </Stack>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        divider={<Divider orientation="vertical" flexItem sx={{ display: { xs: 'none', sm: 'block' } }} />}
        spacing={{ xs: 1, sm: 0 }}
        sx={{
          mb: 1.5,
          py: 1,
          borderTop: 1,
          borderBottom: 1,
          borderColor: 'divider',
          '& > *': { flex: 1, px: { sm: 1.5 } },
        }}
      >
        <MetricCell label="Units" value={FAKE.units} />
        <MetricCell label="Sale" value={FAKE.sale} />
        <MetricCell label="PIN" value={FAKE.pin} />
      </Stack>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        gap={1}
        sx={{ mb: 1.5 }}
      >
        <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }}>
          {FAKE.systemNote}
        </Typography>
        <Chip
          size="small"
          variant="outlined"
          label={`Sale possible: ${FAKE.salePossible}`}
          sx={{ flexShrink: 0 }}
        />
      </Stack>

      <Typography sx={ccSubsectionTitleSx}>PINs at address (3)</Typography>
      <Typography sx={{ ...ccMetaSx, mb: 1 }}>{FAKE.pinExplain}</Typography>
      <Box sx={{ mb: 1.5, overflowX: 'auto' }}>
        <PinTable />
      </Box>

      <Divider sx={{ my: 1.5 }} />
      <Stack direction="row" justifyContent="flex-end" alignItems="center" flexWrap="wrap" gap={1}>
        <Typography sx={{ ...ccMetaSx, mr: 'auto' }}>Last check {FAKE.lastChecked}</Typography>
        <Button variant="text" size="small" sx={{ cursor: 'default' }}>
          Advanced form
        </Button>
        <Button variant="outlined" size="small" sx={{ cursor: 'default' }}>
          Re-run automated check
        </Button>
      </Stack>
    </Paper>
  )
}

function RelatedCondoHeaderMock() {
  return (
    <Paper
      elevation={0}
      sx={{
        ...ccCardSx,
        display: 'flex',
        alignItems: 'center',
        gap: 2,
        py: 1.5,
      }}
      data-testid="lookbook-bo-related"
    >
      <Box
        sx={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          border: '3px solid',
          borderColor: 'warning.main',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Typography fontWeight={700} fontSize="0.9rem">
          30%
        </Typography>
      </Box>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Typography sx={{ ...ccSectionTitleSx, mb: 0.25, fontSize: '0.9rem' }}>
          Condo check · Check unclear
        </Typography>
        <Typography sx={ccMetaSx}>
          Header panel (related) — tap scrolls to Building ownership. Drivers: Missing PINs / data
        </Typography>
      </Box>
      <Chip size="small" label="Scrolls ↓" variant="outlined" />
    </Paper>
  )
}

export default function BuildingOwnershipLookbookPage() {
  const [variant, setVariant] = useState<Variant>('a')
  const copy = useMemo(() => VARIANT_COPY[variant], [variant])

  return (
    <Box
      sx={{
        ...ccPageBgSx,
        minHeight: '100vh',
        p: { xs: 2, sm: 3 },
        maxWidth: 1400,
        mx: 'auto',
      }}
      data-testid="lookbook-building-ownership"
    >
      <Typography variant="h5" fontWeight={700} sx={{ mb: 0.5 }}>
        Lookbook · Building ownership
      </Typography>
      <Typography sx={{ ...ccMetaSx, mb: 2, maxWidth: 720 }}>
        Static layout options using Command Center card tokens.{' '}
        <strong>A</strong> was chosen and shipped to production Building ownership.
        B / C remain for reference only.
      </Typography>

      <Tabs
        value={variant}
        onChange={(_e, next: Variant) => setVariant(next)}
        sx={{ mb: 1, minHeight: 40 }}
      >
        <Tab value="a" label="A · Split + strip" sx={{ textTransform: 'none', minHeight: 40 }} />
        <Tab value="b" label="B · CTA header" sx={{ textTransform: 'none', minHeight: 40 }} />
        <Tab value="c" label="C · Verdict band" sx={{ textTransform: 'none', minHeight: 40 }} />
      </Tabs>
      <Typography sx={{ ...ccMetaSx, mb: 2.5 }}>{copy.blurb}</Typography>

      <Box
        data-variant={variant}
        sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'flex-start', mb: 3 }}
      >
        <LookbookFrame label="Desktop · 1024" width={1024}>
          <BuildingOwnershipLookbookSurface variant={variant} />
        </LookbookFrame>
        <LookbookFrame label="Mobile · 390" width={390}>
          <BuildingOwnershipLookbookSurface variant={variant} />
        </LookbookFrame>
      </Box>

      <Typography
        sx={{
          fontSize: '0.65rem',
          fontWeight: 600,
          letterSpacing: 0.08,
          textTransform: 'uppercase',
          color: 'text.secondary',
          mb: 1,
        }}
      >
        Related · Header Condo check panel
      </Typography>
      <Box sx={{ maxWidth: 1024 }}>
        <RelatedCondoHeaderMock />
      </Box>
    </Box>
  )
}
