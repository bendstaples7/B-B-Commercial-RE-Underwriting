/**
 * LeadStatusChip — reusable colored chip for lead_status pipeline values.
 *
 * Renders the human-readable label and color-codes by pipeline stage category.
 * Used in queue tables, lead detail header, and admin views.
 */
import { Chip } from '@mui/material'
import type { LeadStatus } from '@/types'

// ---------------------------------------------------------------------------
// Label map
// ---------------------------------------------------------------------------

export const LEAD_STATUS_LABELS: Record<LeadStatus, string> = {
  skip_trace: 'Skip Trace',
  awaiting_skip_trace: 'Awaiting Skip Trace',
  mailing_no_contact_made: 'Mailing, No Contact Made',
  mailing_contacted_no_interest: 'Mailing, Contact Made, No Interest',
  mailing_contacted_interested: 'Mailing, Contact Made, Interested',
  negotiating_remote: 'Negotiating Remote',
  in_person_appointment: 'In Person Appointment',
  offer_delivered: 'Offer Delivered',
  deprioritize: 'Deprioritize',
  deal_won: 'Deal Won',
  deal_lost: 'Deal Lost',
  suppressed: 'Suppressed',
  do_not_contact: 'Do Not Contact',
}

// ---------------------------------------------------------------------------
// Color map
// ---------------------------------------------------------------------------

export function getLeadStatusColor(status: string): string {
  switch (status) {
    case 'deal_won':                     return '#2e7d32'  // green
    case 'deal_lost':
    case 'do_not_contact':               return '#c62828'  // red
    case 'suppressed':
    case 'deprioritize':                 return '#757575'  // grey
    case 'negotiating_remote':
    case 'in_person_appointment':
    case 'offer_delivered':              return '#1565c0'  // dark blue
    case 'mailing_contacted_interested': return '#6a1b9a'  // purple
    case 'mailing_contacted_no_interest':return '#e65100'  // orange
    case 'mailing_no_contact_made':      return '#0277bd'  // light blue
    case 'skip_trace':
    case 'awaiting_skip_trace':          return '#37474f'  // dark grey
    default:                             return '#37474f'
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface LeadStatusChipProps {
  status: string
  size?: 'small' | 'medium'
}

export function LeadStatusChip({ status, size = 'small' }: LeadStatusChipProps) {
  // Use Object.hasOwn to guard against prototype-poisoning keys like "__proto__"
  // that would return the object prototype ({}) rather than undefined via bracket access.
  const label = Object.hasOwn(LEAD_STATUS_LABELS, status)
    ? LEAD_STATUS_LABELS[status as LeadStatus]
    : status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  const bgcolor = getLeadStatusColor(status)

  return (
    <Chip
      label={label}
      size={size}
      sx={{ bgcolor, color: '#fff', fontWeight: 700, whiteSpace: 'nowrap' }}
    />
  )
}

export default LeadStatusChip
