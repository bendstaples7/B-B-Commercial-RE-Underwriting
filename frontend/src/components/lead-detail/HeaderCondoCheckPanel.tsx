/**
 * Header Condo check panel — score-style gauge + driver callouts.
 * Independent of Est. value / Last sale / Units KPI cells.
 */
import type React from 'react'
import { Box } from '@mui/material'
import type { CommandCenterPayload } from '@/types'
import {
  CondoCheckSummary,
  humanizeCondoDriver,
} from '@/components/lead-detail/CondoCheckSummary'
import {
  resolveCondoCheckLines,
  shouldShowCondoCheckCell,
} from '@/components/lead-detail/PropertyOverviewQuickStats'

export { humanizeCondoDriver }

export interface HeaderCondoCheckPanelProps {
  commandCenterData: CommandCenterPayload
  onOpenBuildingOwnership?: () => void
}

export function HeaderCondoCheckPanel({
  commandCenterData,
  onOpenBuildingOwnership,
}: HeaderCondoCheckPanelProps) {
  if (!shouldShowCondoCheckCell(commandCenterData)) return null

  const lines = resolveCondoCheckLines(commandCenterData)
  const clickable = Boolean(onOpenBuildingOwnership)

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (!clickable) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onOpenBuildingOwnership?.()
    }
  }

  return (
    <Box
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? onOpenBuildingOwnership : undefined}
      onKeyDown={clickable ? handleKeyDown : undefined}
      aria-label={
        clickable
          ? `Condo check: ${lines.verdict}. Open Building ownership`
          : `Condo check: ${lines.verdict}`
      }
      sx={{
        flex: { xs: '1 1 100%', md: '1 1 clamp(12rem, 16vw, 300px)' },
        width: { md: 'auto' },
        minWidth: { md: '12rem' },
        maxWidth: { xs: '100%', md: 'none' },
        cursor: clickable ? 'pointer' : 'default',
        borderRadius: 1,
        '&:hover': clickable
          ? {
              '& [data-testid="header-condo-check"]': {
                borderColor: 'text.disabled',
                bgcolor: 'action.hover',
              },
            }
          : undefined,
        '&:focus-visible': {
          outline: '2px solid',
          outlineColor: 'primary.main',
          outlineOffset: 2,
        },
      }}
    >
      <CondoCheckSummary
        commandCenterData={commandCenterData}
        testIdStem="header-condo"
      />
    </Box>
  )
}

export default HeaderCondoCheckPanel
