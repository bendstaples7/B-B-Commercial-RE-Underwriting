/**
 * Original vs corrected owner mailing display helpers for mail-queue readiness.
 */
import type { ReactNode } from 'react'
import { Box } from '@mui/material'
import type { OwnerMailingReadiness } from '@/types'

type MailingParts = OwnerMailingReadiness['raw']
type ParsedParts = NonNullable<OwnerMailingReadiness['parsed']>

const PART_KEYS = ['street', 'city', 'state', 'zip'] as const

function partChanged(rawVal: string | null | undefined, parsedVal: string): boolean {
  return (rawVal || '').trim() !== (parsedVal || '').trim()
}

/** Join mailing parts as "street, city, state zip". */
export function formatOwnerMailingLine(parts: {
  street?: string | null
  city?: string | null
  state?: string | null
  zip?: string | null
}): string {
  const street = (parts.street || '').trim()
  const city = (parts.city || '').trim()
  const state = (parts.state || '').trim()
  const zip = (parts.zip || '').trim()
  const stateZip = [state, zip].filter(Boolean).join(' ')
  return [street, city, stateZip].filter(Boolean).join(', ')
}

/**
 * Render original mailing with changed tokens struck through vs corrected.
 */
export function renderOriginalMailingWithStrikes(
  raw: MailingParts,
  parsed: ParsedParts,
): ReactNode {
  return PART_KEYS.map((key, index) => {
    const rawVal = (raw[key] || '').trim()
    const parsedVal = (parsed[key] || '').trim()
    const changed = partChanged(rawVal, parsedVal)
    const display = rawVal || '—'
    const separator =
      index === 0
        ? null
        : key === 'zip'
          ? ' '
          : ', '
    return (
      <Box component="span" key={key}>
        {separator}
        {changed ? (
          <Box
            component="span"
            data-testid={`mailing-original-${key}-struck`}
            sx={{ textDecoration: 'line-through', opacity: 0.75 }}
          >
            {display}
          </Box>
        ) : (
          <Box component="span" data-testid={`mailing-original-${key}`}>
            {display}
          </Box>
        )}
      </Box>
    )
  })
}
