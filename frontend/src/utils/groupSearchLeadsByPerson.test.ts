import { describe, expect, it } from 'vitest'
import { groupSearchLeadsByPerson } from './groupSearchLeadsByPerson'
import type { SearchResultItem } from '@/types'

function lead(partial: Partial<SearchResultItem> & { id: number }): SearchResultItem {
  return {
    type: 'lead',
    label: `${partial.owner_display_name ?? 'X'} · street`,
    nav_path: `/leads/${partial.id}`,
    ...partial,
  }
}

describe('groupSearchLeadsByPerson', () => {
  it('collapses same person_key into one group with nested properties', () => {
    const groups = groupSearchLeadsByPerson([
      lead({
        id: 1,
        person_key: 'u|janson|gilbert',
        owner_display_name: 'GILBERT JANSON',
        property_street: '2623 N Southport Ave',
        property_count: 2,
        relevance_score: 10,
        portfolio_properties: [
          { id: 1, property_street: '2623 N Southport Ave', lead_score: 68.89 },
          { id: 2, property_street: '5339 N Winthrop Ave', lead_score: 68.89 },
        ],
      }),
      lead({
        id: 2,
        person_key: 'u|janson|gilbert',
        owner_display_name: 'GILBERT E JANSON',
        property_street: '5339 N Winthrop Ave',
        property_count: 2,
        relevance_score: 9,
        portfolio_properties: [
          { id: 2, property_street: '5339 N Winthrop Ave', lead_score: 68.89 },
          { id: 1, property_street: '2623 N Southport Ave', lead_score: 68.89 },
        ],
      }),
      lead({
        id: 3,
        person_key: 'u|olivares|gilberto',
        owner_display_name: 'Gilberto Olivares',
        property_street: '2553 N Drake Ave 1',
        property_count: 1,
        relevance_score: 11,
      }),
    ])

    expect(groups).toHaveLength(2)
    expect(groups[0].ownerDisplayName).toBe('GILBERT JANSON')
    expect(groups[0].propertyCount).toBe(2)
    expect(groups[0].properties.map((p) => p.id).sort()).toEqual([1, 2])
    expect(groups[1].propertyCount).toBe(1)
    expect(groups[1].primaryLead.id).toBe(3)
  })
})
