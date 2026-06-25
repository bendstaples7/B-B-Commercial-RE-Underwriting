import type { CommandCenterPayload } from '@/types'

export function formatImportedSource(data: CommandCenterPayload): string | null {
  if (data.source === 'hubspot_import') {
    return `HubSpot${data.hubspot_deal_name ? ` — ${data.hubspot_deal_name}` : ''}`
  }
  return data.source ?? null
}
