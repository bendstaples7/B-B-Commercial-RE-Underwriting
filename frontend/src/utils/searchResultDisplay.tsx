import React from 'react'
import { Box } from '@mui/material'
import type { SearchMatchContext } from '@/types'

/** Returns a label like "Phone" | "Email" for the match type badge. */
export function matchTypeLabel(type: SearchMatchContext['type']): string {
  switch (type) {
    case 'phone':
      return 'Phone'
    case 'email':
      return 'Email'
    case 'address':
      return 'Address'
    case 'name':
      return 'Name'
    case 'lead_id':
      return 'Lead ID'
  }
}

/**
 * Renders a value string with the query substring highlighted in bold.
 */
export function highlightMatch(value: string, query: string): React.ReactNode {
  const q = query.trim()
  if (!q) return value

  const lv = value.toLowerCase()
  const lq = q.toLowerCase()
  const idx = lv.indexOf(lq)

  if (idx !== -1) {
    return (
      <>
        {value.slice(0, idx)}
        <Box component="span" sx={{ fontWeight: 700, color: 'text.primary' }}>
          {value.slice(idx, idx + q.length)}
        </Box>
        {value.slice(idx + q.length)}
      </>
    )
  }

  const queryDigits = q.replace(/\D/g, '')
  if (queryDigits.length >= 4) {
    const valueDigits = value.replace(/\D/g, '')
    const digitIdx = valueDigits.indexOf(queryDigits)
    if (digitIdx !== -1) {
      let digitsFound = 0
      let startOrig = -1
      let endOrig = -1
      for (let vi = 0; vi < value.length; vi++) {
        if (/\d/.test(value[vi])) {
          if (digitsFound === digitIdx) startOrig = vi
          if (digitsFound === digitIdx + queryDigits.length - 1) {
            endOrig = vi
            break
          }
          digitsFound++
        }
      }
      if (startOrig !== -1 && endOrig !== -1) {
        return (
          <>
            {value.slice(0, startOrig)}
            <Box component="span" sx={{ fontWeight: 700, color: 'text.primary' }}>
              {value.slice(startOrig, endOrig + 1)}
            </Box>
            {value.slice(endOrig + 1)}
          </>
        )
      }
    }
  }

  return value
}
