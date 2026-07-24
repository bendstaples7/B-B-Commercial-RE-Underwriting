/**
 * Shared Command Center visual language.
 *
 * Hierarchy (largest → smallest):
 *   property overview address → section title → row / body → meta / caption
 *
 * Cards: one outlined surface per job. Nested Papers/borders are avoided.
 */
import type { SxProps, Theme } from '@mui/material'

/** Soft page canvas behind CC cards. */
export const ccPageBgSx: SxProps<Theme> = {
  bgcolor: 'grey.50',
  minHeight: '100%',
}

/** Hero street address — largest text on the page. */
export const ccHeroAddressSx: SxProps<Theme> = {
  fontSize: { xs: '1.35rem', sm: '1.65rem' },
  fontWeight: 700,
  letterSpacing: -0.02,
  lineHeight: 1.25,
  color: 'text.primary',
  overflowWrap: 'anywhere',
  wordBreak: 'break-word',
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

/** Quieter supporting block (building ownership, secondary context). */
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
  flex: '1 1 0',
  minWidth: { xs: '42%', sm: 100 },
  maxWidth: { sm: 140 },
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
