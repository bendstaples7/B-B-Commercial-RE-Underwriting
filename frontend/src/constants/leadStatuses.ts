import { LEAD_STATUS_LABELS } from '@/components/LeadStatusChip'
import type { LeadStatus } from '@/types'

export const ALL_LEAD_STATUSES = Object.keys(LEAD_STATUS_LABELS) as LeadStatus[]
