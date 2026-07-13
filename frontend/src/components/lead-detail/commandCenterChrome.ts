/**
 * Shared Command Center visual language.
 *
 * Hierarchy (largest → smallest):
 *   sticky address → section title → row / body → meta / caption
 *
 * Cards: one outlined surface per job. Nested Papers/borders are avoided.
 */
import type { SxProps, Theme } from '@mui/material'

/** Primary section title inside the activity column ("Next steps", "Activity"). */
export const ccSectionTitleSx: SxProps<Theme> = {
  fontSize: '0.95rem',
  fontWeight: 700,
  letterSpacing: 0.01,
  lineHeight: 1.3,
  color: 'text.primary',
  mb: 1.5,
}

/** Subsection label inside a card ("Open tasks", "Companies"). */
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
  fontSize: '0.75rem',
  fontWeight: 400,
  lineHeight: 1.4,
  color: 'text.secondary',
}

/** One job = one card. Outlined, no elevation, consistent padding. */
export const ccCardSx: SxProps<Theme> = {
  p: 2,
  mb: 2,
  border: 1,
  borderColor: 'divider',
  borderRadius: 1,
  boxShadow: 'none',
  bgcolor: 'background.paper',
}

/** Quieter supporting block (building ownership, secondary context). */
export const ccSupportCardSx: SxProps<Theme> = {
  ...ccCardSx,
  bgcolor: 'action.hover',
  borderColor: 'transparent',
}
