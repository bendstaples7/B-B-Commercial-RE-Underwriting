import { Link as RouterLink } from 'react-router-dom'
import { Box, Chip, Link } from '@mui/material'
import type { RelatedPropertySummary } from '@/types'
import { LeadStatusChip } from '@/components/LeadStatusChip'

export interface RelatedPropertyRowProps {
  prop: RelatedPropertySummary
  /** Base test id; id is appended as `${testIdPrefix}-${prop.id}` when set. */
  testIdPrefix?: string
  fontSize?: string
  fontWeight?: number
}

/** Shared street + score + status row for search portfolios and CC sidebar. */
export function RelatedPropertyRow({
  prop,
  testIdPrefix,
  fontSize = '0.875rem',
  fontWeight,
}: RelatedPropertyRowProps) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 1,
        flexWrap: 'wrap',
      }}
    >
      <Link
        component={RouterLink}
        to={`/leads/${prop.id}`}
        underline="hover"
        sx={{
          fontSize,
          fontWeight,
          overflowWrap: 'anywhere',
        }}
        data-testid={testIdPrefix ? `${testIdPrefix}-${prop.id}` : undefined}
      >
        {prop.property_street || `Lead #${prop.id}`}
        {prop.property_city ? ` · ${prop.property_city}` : ''}
      </Link>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, flexShrink: 0 }}>
        {prop.lead_score != null && (
          <Chip label={prop.lead_score} size="small" variant="outlined" sx={{ height: 20 }} />
        )}
        {prop.lead_status && <LeadStatusChip status={prop.lead_status} />}
      </Box>
    </Box>
  )
}
