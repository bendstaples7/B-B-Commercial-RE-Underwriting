import type { ReactNode } from 'react'
import { Box, Typography } from '@mui/material'

export const PRIOR_OWNER_STALE_MESSAGE =
  'Likely prior owner — skip trace after sale to confirm.'

/** Compact label used at the top of the Info tab (no full-section wash). */
export function PriorOwnerStaleBanner({
  testId,
  staleSince,
}: {
  testId?: string
  staleSince?: string | null
}) {
  const sinceLabel = staleSince
    ? ` Sale ${staleSince} is newer than last skip trace.`
    : ''
  return (
    <Box
      data-testid={testId}
      role="status"
      sx={{
        mb: 2,
        position: 'relative',
        borderRadius: 1,
        minHeight: 44,
        bgcolor: 'rgba(45, 45, 45, 0.82)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1.5,
        py: 1,
      }}
    >
      <Typography
        variant="body2"
        fontWeight={600}
        sx={{ color: 'common.white', textAlign: 'center' }}
      >
        {PRIOR_OWNER_STALE_MESSAGE}
        {sinceLabel}
      </Typography>
    </Box>
  )
}

/**
 * Regular contact/mailing content with a transparent gray wash over the area
 * and the prior-owner sentence centered in that wash.
 * Overlay does not block clicks.
 */
export function PriorOwnerStaleOverlay({
  children,
  testId,
  bannerTestId,
  showBanner = true,
}: {
  children: ReactNode
  testId?: string
  bannerTestId?: string
  showBanner?: boolean
}) {
  return (
    <Box
      data-testid={testId}
      sx={{
        position: 'relative',
        borderRadius: 1,
        overflow: 'hidden',
        minHeight: showBanner ? 72 : undefined,
      }}
    >
      <Box sx={{ position: 'relative', zIndex: 0, px: 0.25, py: 0.25 }}>
        {children}
      </Box>

      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          bgcolor: 'rgba(45, 45, 45, 0.72)',
          pointerEvents: 'none',
          zIndex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          px: 1.5,
        }}
      >
        {showBanner ? (
          <Typography
            data-testid={bannerTestId}
            role="status"
            variant="caption"
            fontWeight={700}
            sx={{
              color: 'common.white',
              textAlign: 'center',
              lineHeight: 1.35,
              maxWidth: '100%',
            }}
          >
            {PRIOR_OWNER_STALE_MESSAGE}
          </Typography>
        ) : null}
      </Box>
    </Box>
  )
}
