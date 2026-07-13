import type { CommandCenterPayload } from '@/types'

/** True when free-text import source is redundant with Deal Source (e.g. both CoStar). */
export function isImportedSourceRedundantWithDealSource(
  source: string | null | undefined,
  dealSource: string | null | undefined,
): boolean {
  const imported = (source ?? '').trim()
  const deal = (dealSource ?? '').trim()
  if (!imported || !deal) return false
  if (imported.toLowerCase() === deal.toLowerCase()) return true
  // CoStar variants in the sheet ("skip as costar") vs Deal Source "CoStar"
  const costarRe = /co[\s_-]*star/i
  if (costarRe.test(imported) && costarRe.test(deal)) return true
  return false
}

export function formatImportedSource(data: CommandCenterPayload): string | null {
  if (data.source === 'hubspot_import') {
    return `HubSpot${data.hubspot_deal_name ? ` — ${data.hubspot_deal_name}` : ''}`
  }
  return data.source ?? null
}

/** Raw import provenance when it adds info beyond Deal Source; otherwise null. */
export function formatImportNote(data: CommandCenterPayload): string | null {
  const formatted = formatImportedSource(data)
  if (!formatted) return null
  if (isImportedSourceRedundantWithDealSource(data.source, data.deal_source)) {
    return null
  }
  return formatted
}
