import { buildLeadQueueSearch } from '@/utils/fromQueue'

export type LogActivityType = 'call' | 'note' | 'email'

const LOG_ACTIVITY_TYPES = new Set<LogActivityType>(['call', 'note', 'email'])

export function parseLogActivityParam(param: string | null): LogActivityType | null {
  if (!param) return null
  const normalized = param.toLowerCase() as LogActivityType
  return LOG_ACTIVITY_TYPES.has(normalized) ? normalized : null
}

export function buildLeadLogUrl(
  leadId: number,
  log: LogActivityType,
  queueKey?: string,
  outreach?: string | null,
): string {
  const params = new URLSearchParams()
  params.set('log', log)
  if (queueKey) params.set('queue', queueKey)
  if (outreach) params.set('outreach', outreach)
  return `/leads/${leadId}?${params.toString()}`
}

export function buildLeadUrl(leadId: number, queueKey?: string, outreach?: string | null): string {
  return `/leads/${leadId}${buildLeadQueueSearch(queueKey, outreach)}`
}
