import type { RelatedPropertySummary, SearchResultItem } from '@/types'

export interface SearchPersonGroup {
  key: string
  ownerDisplayName: string
  propertyCount: number
  /** Best relevance among members (page ordering). */
  relevanceScore: number | null
  /** Lead that matched search (for match_context); prefer highest relevance. */
  primaryLead: SearchResultItem
  properties: RelatedPropertySummary[]
}

function mergePortfolio(
  leads: SearchResultItem[],
): RelatedPropertySummary[] {
  const byId = new Map<number, RelatedPropertySummary>()
  for (const lead of leads) {
    const rows =
      lead.portfolio_properties && lead.portfolio_properties.length > 0
        ? lead.portfolio_properties
        : [
            {
              id: lead.id,
              property_street: lead.property_street ?? lead.label,
              lead_status: lead.lead_status,
              lead_score: lead.lead_score,
            },
          ]
    for (const row of rows) {
      if (!byId.has(row.id)) {
        byId.set(row.id, row)
      }
    }
  }
  return Array.from(byId.values()).sort((a, b) => {
    const sa = a.lead_score ?? -1
    const sb = b.lead_score ?? -1
    if (sb !== sa) return sb - sa
    return a.id - b.id
  })
}

/** Collapse same-person search hits into one group with nested buildings. */
export function groupSearchLeadsByPerson(leads: SearchResultItem[]): SearchPersonGroup[] {
  const order: string[] = []
  const buckets = new Map<string, SearchResultItem[]>()

  for (const lead of leads) {
    const key = lead.person_key || `lead:${lead.id}`
    if (!buckets.has(key)) {
      order.push(key)
      buckets.set(key, [])
    }
    buckets.get(key)!.push(lead)
  }

  return order.map((key) => {
    const members = buckets.get(key)!
    const primaryLead = members.reduce((best, cur) => {
      const br = best.relevance_score ?? -1
      const cr = cur.relevance_score ?? -1
      if (cr > br) return cur
      if (cr === br && cur.id < best.id) return cur
      return best
    }, members[0])

    const properties = mergePortfolio(members)
    const ownerDisplayName =
      primaryLead.owner_display_name?.trim() ||
      primaryLead.label.split('·')[0]?.trim() ||
      'Unknown'

    return {
      key,
      ownerDisplayName,
      propertyCount: Math.max(properties.length, primaryLead.property_count ?? 1),
      relevanceScore: primaryLead.relevance_score ?? null,
      primaryLead,
      properties,
    }
  })
}
