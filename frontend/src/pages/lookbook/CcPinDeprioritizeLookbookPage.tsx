/**
 * DEV lookbook v2 — dense Property Overview top rail options.
 * Hard rule: marketing street is ONE line (nowrap). AKA under. Pack panels; kill dead whitespace.
 * Vote A / B / C before production.
 */
import { useMemo, useState, type ReactNode } from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Link as MuiLink,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import PauseCircleOutlineIcon from '@mui/icons-material/PauseCircleOutline'
import PhoneOutlinedIcon from '@mui/icons-material/PhoneOutlined'
import NoteOutlinedIcon from '@mui/icons-material/NoteOutlined'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import LocalPostOfficeOutlinedIcon from '@mui/icons-material/LocalPostOfficeOutlined'
import ManageSearchOutlinedIcon from '@mui/icons-material/ManageSearchOutlined'
import {
  ccActionTileSx,
  ccCardSx,
  ccHeaderAddressColumnSx,
  ccHeaderPrimaryClusterSx,
  ccHeaderTrailingPanelsSx,
  ccHeroAddressSx,
  ccHeroSecondarySx,
  ccMetaSx,
  ccPageBgSx,
} from '@/components/lead-detail/commandCenterChrome'
import { CondoCheckSummary } from '@/components/lead-detail/CondoCheckSummary'
import { HeaderLeadScorePanel } from '@/components/lead-detail/HeaderLeadScorePanel'
import { PropertyOverviewQuickStats } from '@/components/lead-detail/PropertyOverviewQuickStats'
import type { CommandCenterPayload, PropertyScoreRecord } from '@/types'

type Variant = 'a' | 'b' | 'c'

const FAKE_PAYLOAD = {
  id: 10265,
  owner_first_name: null,
  owner_last_name: null,
  property_street: '3715-3721 N Leavitt St',
  property_city: 'Chicago',
  property_state: 'IL',
  property_zip: '60618',
  property_type: 'Commercial',
  county_assessor_pin: null,
  assessor_aka_street: '2155 W Bradley Pl',
  assessor_aka_city: 'Chicago',
  assessor_aka_state: 'IL',
  assessor_aka_zip: '60618',
  is_cook_county_eligible: true,
  lead_status: 'skip_trace',
  lead_category: 'commercial',
  lead_score: 42,
  assessed_value: 1200000,
  most_recent_sale: '2019-01-15',
  most_recent_sale_price: 890000,
  units: 12,
  condo_risk_status: 'likely_condo',
  condo_confidence: 'high',
  condo_check_reason: 'Unit numbers and multiple PINs at tax situs',
  condo_check_drivers: ['rule_4_unit_numbers', 'rule_2_multi_pin'],
  condo_checked_at: '2026-07-29',
  condo_analysis_id: 1,
  building_sale_possible: 'no',
  contacts: [],
  organizations: [],
} as unknown as CommandCenterPayload

const FAKE_SCORE: PropertyScoreRecord = {
  id: 1,
  property_id: 10265,
  score_version: 'v1',
  total_score: 42,
  score_tier: 'C',
  data_quality_score: 70,
  recommended_action: 'needs_manual_review',
  top_signals: [
    { dimension: 'absentee_owner', points: 12 },
    { dimension: 'years_owned', points: 8 },
    { dimension: 'tax_delinquency', points: 6 },
    { dimension: 'equity', points: 5 },
  ],
  score_details: {
    absentee_owner: 12,
    years_owned: 8,
    tax_delinquency: 6,
    equity: 5,
  },
  missing_data: [],
  created_at: '2026-07-29T12:00:00Z',
}

const STREET = '3715-3721 N Leavitt St, Chicago, IL 60618'
const AKA = '2155 W Bradley Pl, Chicago, IL 60618'

const VARIANT_COPY: Record<Variant, { label: string; blurb: string }> = {
  a: {
    label: 'A · Left stack + packed right',
    blurb:
      'Street ONE line (nowrap, address flex-grows). AKA under. Production KPI grid. ≤2 full-label score drivers. Condo+score packed after KPIs (no ml:auto canyon).',
  },
  b: {
    label: 'B · Full-width street row',
    blurb:
      'Row 1: full-width nowrap street. Row 2: AKA/meta left; production KPI grid + condo + score packed right. Same single Confirm deprioritize tile.',
  },
  c: {
    label: 'C · Ultra-tight strip',
    blurb:
      'Street nowrap; AKA under; production KPI grid under meta; narrower condo/score. Same single Confirm deprioritize tile.',
  },
}

/** Option A — production: one-line content-sized street. */
const streetSxReadable = {
  ...ccHeroAddressSx,
  fontSize: { xs: '1.15rem', sm: '1.35rem' },
  minWidth: 0,
  maxWidth: '100%',
  whiteSpace: 'nowrap' as const,
  overflow: 'hidden' as const,
  textOverflow: 'ellipsis' as const,
  overflowWrap: 'normal' as const,
  wordBreak: 'keep-all' as const,
}

const akaSxReadable = {
  ...ccHeroSecondarySx,
  mt: 0.15,
  fontSize: '0.8rem',
  minWidth: 0,
  maxWidth: '100%',
  textAlign: 'left' as const,
  whiteSpace: 'nowrap' as const,
  overflow: 'hidden' as const,
  textOverflow: 'ellipsis' as const,
}

/** Variants B/C contrast — historical nowrap+ellipsis. */
const streetSx = {
  ...ccHeroAddressSx,
  fontSize: { xs: '1.15rem', sm: '1.35rem' },
  minWidth: 0,
  maxWidth: '100%',
  whiteSpace: 'nowrap' as const,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  overflowWrap: 'normal' as const,
  wordBreak: 'keep-all' as const,
}

const akaSx = {
  ...ccHeroSecondarySx,
  mt: 0.15,
  fontSize: '0.8rem',
  minWidth: 0,
  maxWidth: '100%',
  textAlign: 'left' as const,
  whiteSpace: 'nowrap' as const,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
}

function LookbookFrame({
  label,
  width,
  children,
}: {
  label: string
  width: number | '100%'
  children: ReactNode
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        minWidth: 0,
        width: width === '100%' ? '100%' : undefined,
        flex: width === '100%' ? '1 1 100%' : undefined,
      }}
    >
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
          width: width === '100%' ? '100%' : width,
          maxWidth: '100%',
          overflow: 'hidden',
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          bgcolor: 'grey.50',
          p: { xs: 1, sm: 1.25 },
        }}
      >
        {children}
      </Box>
    </Box>
  )
}

function MetaLine() {
  return (
    <Typography
      sx={{
        ...ccHeroSecondarySx,
        mt: 0.35,
        display: 'flex',
        flexWrap: 'nowrap',
        alignItems: 'baseline',
        columnGap: 1,
        overflow: 'hidden',
        whiteSpace: 'nowrap',
      }}
      component="div"
    >
      <Box component="span" sx={{ flexShrink: 0 }}>
        Owner:{' '}
        <MuiLink
          component="button"
          type="button"
          variant="inherit"
          underline="hover"
          sx={{ font: 'inherit', color: 'primary.main', cursor: 'default' }}
        >
          Bradley Place LLC
        </MuiLink>
      </Box>
      <Box component="span" aria-hidden sx={{ color: 'text.disabled', flexShrink: 0 }}>
        ·
      </Box>
      <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, minWidth: 0 }}>
        Parcel ID / PIN: —
        <Button size="small" variant="text" sx={{ cursor: 'default', minWidth: 0, py: 0, flexShrink: 0 }}>
          Look up
        </Button>
      </Box>
      <Chip size="small" label="Skip Trace" variant="outlined" sx={{ cursor: 'default', ml: 0.5, height: 22 }} />
    </Typography>
  )
}

function DevQuickStats() {
  return (
    <PropertyOverviewQuickStats commandCenterData={FAKE_PAYLOAD} />
  )
}

/** Trailing condo + score only (packed after KPIs, no ml:auto) — never includes quick-stats. */
function PackedPanels({ ultraTight }: { ultraTight?: boolean }) {
  return (
    <Box
      sx={{
        ...ccHeaderTrailingPanelsSx,
        ...(ultraTight
          ? {
              '& [data-testid="header-condo-check"], & [data-testid="header-lead-score"]': {
                width: 180,
                minWidth: 160,
                maxWidth: 200,
                flex: '0 1 auto',
                ml: '0 !important',
                py: 0.35,
                px: 1,
              },
            }
          : {}),
      }}
      data-testid="cc-header-trailing-panels"
    >
      <Box sx={{ flex: '0 1 auto', minWidth: 0 }}>
        <CondoCheckSummary commandCenterData={FAKE_PAYLOAD} testIdStem="header-condo" />
      </Box>
      <HeaderLeadScorePanel
        score={FAKE_SCORE.total_score}
        tier={FAKE_SCORE.score_tier}
        scoreRecord={FAKE_SCORE}
      />
    </Box>
  )
}

function TaxBanner() {
  return (
    <Alert
      severity="info"
      sx={{ mt: 0.75, py: 0.25, '& .MuiAlert-message': { width: '100%' } }}
      data-testid="lookbook-tax-situs-banner"
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1.5,
          flexWrap: 'wrap',
          width: '100%',
        }}
      >
        <Typography variant="body2" sx={{ fontSize: '0.75rem', minWidth: 0, flex: '1 1 240px' }}>
          Tax situs 2155 W Bradley Pl · 12 PINs — apply closest or analyze building.
        </Typography>
        <Stack direction="row" gap={0.75} flexShrink={0}>
          <Button size="small" variant="outlined" sx={{ cursor: 'default' }}>
            Apply closest
          </Button>
          <Button size="small" variant="text" sx={{ cursor: 'default' }}>
            Analyze building
          </Button>
        </Stack>
      </Box>
    </Alert>
  )
}

function HeaderVariantA() {
  return (
    <Paper
      component="header"
      elevation={0}
      data-testid="lookbook-property-overview-header"
      data-variant="a"
      sx={{ ...ccCardSx, p: 1.25, mb: 0 }}
    >
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'nowrap',
          alignItems: 'flex-start',
          gap: 1.5,
          minWidth: 0,
        }}
      >
        <IconButton size="small" edge="start" aria-label="Back" sx={{ cursor: 'default', mt: 0.25 }}>
          <ArrowBackIcon fontSize="small" />
        </IconButton>

        <Box sx={ccHeaderPrimaryClusterSx}>
          <Box sx={ccHeaderAddressColumnSx}>
            <Box data-testid="lookbook-property-overview-address">
              <Typography sx={streetSxReadable} title={STREET}>
                {STREET}
              </Typography>
              <Typography
                component="div"
                data-testid="lookbook-property-overview-aka"
                sx={akaSxReadable}
                title={AKA}
              >
                Also known as:{' '}
                <Box component="span" sx={{ color: 'text.primary', fontWeight: 500 }}>
                  {AKA}
                </Box>
              </Typography>
            </Box>
            <MetaLine />
          </Box>
          <DevQuickStats />
        </Box>

        <PackedPanels />
      </Box>
      <TaxBanner />
    </Paper>
  )
}

function HeaderVariantB() {
  return (
    <Paper
      component="header"
      elevation={0}
      data-testid="lookbook-property-overview-header"
      data-variant="b"
      sx={{ ...ccCardSx, p: 1.25, mb: 0 }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0, mb: 0.75 }}>
        <IconButton size="small" edge="start" aria-label="Back" sx={{ cursor: 'default' }}>
          <ArrowBackIcon fontSize="small" />
        </IconButton>
        <Box data-testid="lookbook-property-overview-address" sx={{ flex: 1, minWidth: 0 }}>
          <Typography sx={streetSx} title={STREET}>
            {STREET}
          </Typography>
        </Box>
      </Box>

      <Box
        sx={{
          display: 'flex',
          flexWrap: 'nowrap',
          alignItems: 'center',
          gap: 1.5,
          minWidth: 0,
          pl: 5,
        }}
      >
        <Box sx={{ flex: '1 1 auto', minWidth: 0 }}>
          <Typography
            component="div"
            data-testid="lookbook-property-overview-aka"
            sx={akaSx}
            title={AKA}
          >
            Also known as:{' '}
            <Box component="span" sx={{ color: 'text.primary', fontWeight: 500 }}>
              {AKA}
            </Box>
          </Typography>
          <MetaLine />
        </Box>
        <DevQuickStats />
        <PackedPanels />
      </Box>
      <Box sx={{ pl: 5 }}>
        <TaxBanner />
      </Box>
    </Paper>
  )
}

function HeaderVariantC() {
  return (
    <Paper
      component="header"
      elevation={0}
      data-testid="lookbook-property-overview-header"
      data-variant="c"
      sx={{ ...ccCardSx, p: 1.25, mb: 0 }}
    >
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'nowrap',
          alignItems: 'flex-start',
          gap: 1.25,
          minWidth: 0,
        }}
      >
        <IconButton size="small" edge="start" aria-label="Back" sx={{ cursor: 'default', mt: 0.25 }}>
          <ArrowBackIcon fontSize="small" />
        </IconButton>

        <Box sx={{ flex: '1 1 0', minWidth: 0 }}>
          <Box data-testid="lookbook-property-overview-address">
            <Typography sx={streetSx} title={STREET}>
              {STREET}
            </Typography>
            <Typography
              component="div"
              data-testid="lookbook-property-overview-aka"
              sx={akaSx}
              title={AKA}
            >
              Also known as:{' '}
              <Box component="span" sx={{ color: 'text.primary', fontWeight: 500 }}>
                {AKA}
              </Box>
            </Typography>
          </Box>
          <MetaLine />
          <Box sx={{ mt: 0.75, display: 'flex', justifyContent: 'flex-start' }}>
            <DevQuickStats />
          </Box>
          <TaxBanner />
        </Box>

        <PackedPanels ultraTight />
      </Box>
    </Paper>
  )
}

function FakeTile({
  label,
  icon,
  filled,
  outlined,
}: {
  label: string
  icon: ReactNode
  filled?: boolean
  outlined?: boolean
}) {
  return (
    <Button
      sx={{
        ...ccActionTileSx,
        cursor: 'default',
        minWidth: 88,
        maxWidth: 120,
        py: 1.25,
        ...(filled
          ? {
              bgcolor: 'primary.main',
              color: 'primary.contrastText',
              '&:hover': { bgcolor: 'primary.dark', borderColor: 'primary.dark' },
            }
          : {}),
        ...(outlined
          ? {
              bgcolor: 'background.paper',
              borderColor: 'divider',
              '&:hover': { bgcolor: 'action.hover', borderColor: 'divider' },
            }
          : {}),
      }}
    >
      {icon}
      {label}
    </Button>
  )
}

function ActionCenter() {
  return (
    <Paper elevation={0} sx={{ ...ccCardSx, p: 1.5, mb: 0 }} data-testid="lookbook-action-center">
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 2,
          flexWrap: 'wrap',
          mb: 1.25,
        }}
      >
        <Typography sx={{ fontSize: '0.8rem', fontWeight: 600, color: 'text.secondary', minWidth: 0 }}>
          <Box component="span" sx={{ fontWeight: 700 }}>
            Recommended next action:{' '}
          </Box>
          Confirm deprioritize?
          <Box component="span" sx={{ fontWeight: 500 }}>
            {' — '}
            Likely condoized / multi-PIN tax situs — confirm deprioritize.
          </Box>
        </Typography>
      </Box>
      <Stack direction="row" flexWrap="wrap" useFlexGap gap={1}>
        <FakeTile label="Log Call" icon={<PhoneOutlinedIcon fontSize="small" />} />
        <FakeTile label="Log Note" icon={<NoteOutlinedIcon fontSize="small" />} />
        <FakeTile label="Log Email" icon={<EmailOutlinedIcon fontSize="small" />} />
        <FakeTile
          label="Add to Mail Queue"
          icon={<LocalPostOfficeOutlinedIcon fontSize="small" />}
        />
        <FakeTile
          label="Move to Skip Trace"
          icon={<ManageSearchOutlinedIcon fontSize="small" />}
        />
        {/* Same universal Deprioritize slot — elevated label + fill when likely_condo */}
        <FakeTile
          label="Confirm deprioritize"
          icon={<PauseCircleOutlineIcon fontSize="small" />}
          filled
        />
      </Stack>
      <Box
        sx={{
          mt: 1.5,
          p: 1.5,
          border: 1,
          borderColor: 'divider',
          borderRadius: 1,
          maxWidth: 400,
        }}
        data-testid="lookbook-deprioritize-dialog"
      >
        <Typography fontWeight={700} sx={{ mb: 0.75, fontSize: '0.9rem' }}>
          Confirm deprioritize
        </Typography>
        <TextField
          label="Reason"
          size="small"
          fullWidth
          value="Likely condoized / multi-PIN tax situs — confirm deprioritize."
          InputProps={{ readOnly: true }}
          sx={{ mb: 1 }}
        />
        <Stack direction="row" justifyContent="flex-end" gap={1}>
          <Button size="small" sx={{ cursor: 'default' }}>
            Cancel
          </Button>
          <Button size="small" variant="contained" sx={{ cursor: 'default' }}>
            Deprioritize
          </Button>
        </Stack>
      </Box>
    </Paper>
  )
}

function RelatedNote() {
  return (
    <Paper elevation={0} sx={{ ...ccCardSx, py: 1.25 }} data-testid="lookbook-cc-pin-related">
      <Stack direction="row" alignItems="center" justifyContent="space-between" gap={2}>
        <Typography sx={ccMetaSx}>
          Related · All variants keep marketing street on <strong>one nowrap line</strong> (ellipsis
          if the rail is squeezed). AKA sits under — never beside in a way that forces the street to
          wrap.
        </Typography>
        <Stack direction="row" alignItems="center" gap={1} flexShrink={0}>
          <CircularProgress size={16} />
          <Typography variant="body2" fontWeight={600}>
            Looking up PIN…
          </Typography>
        </Stack>
      </Stack>
    </Paper>
  )
}

function Surface({ variant }: { variant: Variant }) {
  return (
    <Stack spacing={1.5} data-variant={variant} data-testid="lookbook-cc-pin-surface">
      {variant === 'a' ? <HeaderVariantA /> : null}
      {variant === 'b' ? <HeaderVariantB /> : null}
      {variant === 'c' ? <HeaderVariantC /> : null}
      <ActionCenter />
    </Stack>
  )
}

export default function CcPinDeprioritizeLookbookPage() {
  const [variant, setVariant] = useState<Variant>('a')
  const copy = useMemo(() => VARIANT_COPY[variant], [variant])

  return (
    <Box
      sx={{
        ...ccPageBgSx,
        minHeight: '100vh',
        p: { xs: 1.5, sm: 2 },
        width: '100%',
        maxWidth: '100%',
        boxSizing: 'border-box',
      }}
      data-testid="lookbook-cc-pin-deprioritize"
    >
      <Typography variant="h5" fontWeight={700} sx={{ mb: 0.5 }} component="h1">
        Lookbook · Top rail (v2)
      </Typography>
      <Typography sx={{ ...ccMetaSx, mb: 2, maxWidth: 920 }}>
        Option <strong>A</strong> matches production: street <strong>one line</strong> (content-sized),
        KPIs adjacent, ≤2 full score drivers, condo+score trail. B/C keep contrast variants.
      </Typography>

      <Tabs
        value={variant}
        onChange={(_e, next: Variant) => setVariant(next)}
        sx={{ mb: 1, minHeight: 40 }}
      >
        <Tab value="a" label="A · Packed right" sx={{ textTransform: 'none', minHeight: 40 }} />
        <Tab value="b" label="B · Full-width street" sx={{ textTransform: 'none', minHeight: 40 }} />
        <Tab value="c" label="C · Ultra-tight" sx={{ textTransform: 'none', minHeight: 40 }} />
      </Tabs>
      <Typography sx={{ ...ccMetaSx, mb: 2 }}>{copy.blurb}</Typography>

      <Stack spacing={2.5} data-variant={variant} sx={{ width: '100%', mb: 2 }}>
        <LookbookFrame label="Desktop · full width" width="100%">
          <Surface variant={variant} />
        </LookbookFrame>
        <LookbookFrame label="Mobile · 390 (street still nowrap + ellipsis)" width={390}>
          <Surface variant={variant} />
        </LookbookFrame>
      </Stack>

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
        Related
      </Typography>
      <RelatedNote />
    </Box>
  )
}
