/**
 * Shared Command Center visual language.
 *
 * Hierarchy (largest ΓåÆ smallest):
 *   property overview address ΓåÆ section title ΓåÆ row / body ΓåÆ meta / caption
 *
 * Cards: one outlined surface per job. Nested Papers/borders are avoided.
 */
import type { SxProps, Theme } from '@mui/material'

/** Soft page canvas behind CC cards. */
export const ccPageBgSx: SxProps<Theme> = {
  bgcolor: 'grey.50',
  minHeight: '100%',
}

/** Hero street address ΓÇö largest text on the page. */
export const ccHeroAddressSx: SxProps<Theme> = {
  fontSize: { xs: '1.35rem', sm: '1.65rem' },
  fontWeight: 700,
  letterSpacing: -0.02,
  lineHeight: 1.25,
  color: 'text.primary',
  // Prefer natural word breaks only ΓÇö do not shatter mid-token on wide layouts.
  overflowWrap: 'break-word',
  wordBreak: 'normal',
}

/** City / state / zip under the hero address. */
export const ccHeroSecondarySx: SxProps<Theme> = {
  fontSize: '0.9rem',
  fontWeight: 400,
  lineHeight: 1.4,
  color: 'text.secondary',
  mt: 0.5,
}

/** Primary section title inside a card ("Action Center", "Activity"). */
export const ccSectionTitleSx: SxProps<Theme> = {
  fontSize: '1rem',
  fontWeight: 700,
  letterSpacing: 0.01,
  lineHeight: 1.3,
  color: 'text.primary',
  mb: 1.5,
}

/** Subsection label inside a card ("Companies"). */
export const ccSubsectionTitleSx: SxProps<Theme> = {
  fontSize: '0.8rem',
  fontWeight: 700,
  letterSpacing: 0.02,
  lineHeight: 1.3,
  color: 'text.secondary',
  mb: 1,
}

/** Primary text on a list row (person/company name, task title). */
export const ccRowTitleSx: SxProps<Theme> = {
  fontSize: '0.95rem',
  fontWeight: 500,
  lineHeight: 1.35,
  color: 'text.primary',
}

/** Supporting copy under a row or section. */
export const ccMetaSx: SxProps<Theme> = {
  fontSize: '0.8rem',
  fontWeight: 400,
  lineHeight: 1.45,
  color: 'text.secondary',
}

/** One job = one card. Tight radius, light border, generous padding. */
export const ccCardSx: SxProps<Theme> = {
  p: { xs: 2, sm: 2.5 },
  mb: 0,
  border: 1,
  borderColor: 'divider',
  borderRadius: 1,
  boxShadow: '0 1px 2px rgba(16, 24, 40, 0.04)',
  bgcolor: 'background.paper',
  maxWidth: '100%',
  overflow: 'hidden',
  boxSizing: 'border-box',
}

/** Quieter supporting block for secondary nested context (not primary CC cards). */
export const ccSupportCardSx: SxProps<Theme> = {
  ...ccCardSx,
  bgcolor: 'action.hover',
  borderColor: 'transparent',
  boxShadow: 'none',
}

/** Gap between cards in a column stack. */
export const ccStackGap = 2.5

/** Action Center icon tile button. */
export const ccActionTileSx: SxProps<Theme> = {
  // Grow equally; do not cap width ΓÇö a maxWidth leaves empty row space that
  // is still too small for the next tile's minWidth, so Deprioritize wraps.
  flex: '1 1 0',
  minWidth: { xs: 'calc(50% - 4px)', sm: 0 },
  maxWidth: { xs: 'calc(50% - 4px)', sm: 'none' },
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 0.75,
  py: 2,
  px: 1,
  borderRadius: 1,
  bgcolor: 'grey.100',
  border: '1px solid',
  borderColor: 'transparent',
  color: 'text.primary',
  textTransform: 'none',
  fontWeight: 600,
  fontSize: '0.8rem',
  lineHeight: 1.2,
  whiteSpace: 'normal',
  '&:hover': {
    bgcolor: 'grey.200',
    borderColor: 'divider',
  },
}

/** Scrollable Activity Feed body. */
export const ccActivityFeedScrollSx: SxProps<Theme> = {
  maxHeight: 360,
  overflowY: 'auto',
  pr: 0.5,
}

/** KPI label under Key Contact. */
export const ccKpiLabelSx: SxProps<Theme> = {
  fontSize: '0.7rem',
  fontWeight: 600,
  letterSpacing: 0.04,
  textTransform: 'uppercase',
  color: 'text.secondary',
  lineHeight: 1.2,
}

/** KPI value. */
export const ccKpiValueSx: SxProps<Theme> = {
  fontSize: '0.95rem',
  fontWeight: 700,
  color: 'text.primary',
  lineHeight: 1.3,
  mt: 0.25,
}

/**
 * Property Overview header — ONE fluid horizontal bar on md+:
 *   [back][address][2×2 KPIs][condo][score]
 *
 * KPI grid (locked):
 *   Est. value     | Last sale
 *   Units/details  | Category
 *
 * Proportional clamp() slots (not fixed px) so the bar holds at any viewport.
 * Address/KPIs hug; trail panels grow into leftover slack (clamp ~10–13vw,
 * 260px cap). FORBID fixed pair widths / flexShrink:0 / address maxWidth
 * ceilings / trail ml:auto canyon.
 */
export const ccHeaderAddressColumnSx: SxProps<Theme> = {
  // Hug street text beside KPIs. At md+ the address keeps its one-line width;
  // KPI cells and trail panels take responsive pressure first.
  flex: { xs: '1 1 calc(100% - 48px)', md: '0 0 auto' },
  minWidth: 0,
  maxWidth: { xs: '100%', md: 'none' },
  width: { md: 'auto' },
}

/** Address + 2×2 KPI band — hug content; trail panels absorb leftover width. */
export const ccHeaderPrimaryClusterSx: SxProps<Theme> = {
  display: 'flex',
  flexWrap: 'nowrap',
  // Vertically center 2×2 KPI callouts against the taller address column.
  alignItems: 'center',
  gap: { xs: 1.25, md: 1 },
  flex: { xs: '1 1 100%', md: '1 1 auto' },
  minWidth: { xs: 0, md: 0 },
  maxWidth: '100%',
}

/**
 * Condo + score on the SAME row as KPIs — grow to fill slack left of condo
 * so Lead Signals stays flush right (no white gap before/after the pair).
 * FORBID md flex-basis/width 100% — that forces a second row under Last sale.
 * FORBID flexShrink:0 / width:368 — breaks responsive packing.
 */
export const ccHeaderTrailingPanelsSx: SxProps<Theme> = {
  display: 'flex',
  flexWrap: 'nowrap',
  alignItems: 'stretch',
  gap: 1,
  // Grow into remaining row width; panels share it evenly.
  flex: { xs: '1 1 100%', md: '1 1 auto' },
  ml: 0,
  minWidth: { xs: '100%', md: 0 },
  maxWidth: '100%',
  width: { md: 'auto' },
  contain: 'layout',
  '& [data-testid="header-condo-check"], & [data-testid="header-lead-score"]': {
    // Basis targets ~10rem (fluid to 260px); minWidth 0 lets panels shrink.
    flex: { md: '1 1 clamp(10rem, 13vw, 260px)' },
    width: { md: 'auto' },
    minWidth: { md: 0 },
    maxWidth: { xs: '100%', md: 'none' },
    ml: '0 !important',
    overflow: 'hidden',
    contain: 'layout style',
    isolation: 'isolate',
  },
}

/** @deprecated Use ccHeaderTrailingPanelsSx — kept name alias during migration. */
export const ccHeaderTrailingPackSx = ccHeaderTrailingPanelsSx

/** Header Paper — visible overflow so Updated/chips are not clipped by the card. */
export const ccHeaderPaperSx: SxProps<Theme> = {
  ...ccCardSx,
  overflow: 'visible',
  p: { xs: 1.25, sm: 1.5 },
  mb: 0,
}

/**
 * 2×2 KPI band — Est | Last sale / Units | Category.
 * Grow 3 = primary slack sink so Last sale sits beside condo.
 */
export const ccHeaderQuickStatsSx: SxProps<Theme> = {
  // Grow within the primary cluster so the KPI→condo gap never parks slack.
  flex: { xs: '1 1 100%', md: '1 1 auto' },
  minWidth: { xs: '100%', md: 0 },
  maxWidth: { xs: '100%', md: 'none' },
  width: { md: 'auto' },
  display: 'grid',
  gridTemplateColumns: 'repeat(2, auto)',
  columnGap: { xs: 1.25, md: 1.25 },
  rowGap: { xs: 0.75, md: 0.65 },
  alignContent: 'center',
  justifyItems: 'start',
  justifyContent: 'start',
  overflow: 'hidden',
  contain: 'layout',
  isolation: 'isolate',
  px: { md: 0.25 },
  mr: { md: 0 },
}
