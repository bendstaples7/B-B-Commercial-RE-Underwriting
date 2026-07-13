import { describe, it, expect } from 'vitest'
import {
  formatImportNote,
  formatImportedSource,
  isImportedSourceRedundantWithDealSource,
} from '@/components/lead-detail/leadDetailFormatters'
import type { CommandCenterPayload } from '@/types'

function payload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: null,
    owner_last_name: null,
    property_street: null,
    property_city: null,
    property_state: null,
    lead_score: 0,
    lead_status: 'awaiting_skip_trace',
    has_property_match: false,
    analysis_session_id: null,
    recommended_action: { value: null, label: null, explanation: null, signals: {} },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    ...overrides,
  }
}

describe('leadDetailFormatters', () => {
  it('formats hubspot imported source with deal name', () => {
    expect(
      formatImportedSource(
        payload({ source: 'hubspot_import', hubspot_deal_name: '3508 Sacramento' }),
      ),
    ).toBe('HubSpot — 3508 Sacramento')
  })

  it('treats CoStar variants as redundant with Deal Source CoStar', () => {
    expect(isImportedSourceRedundantWithDealSource('skip as costar', 'CoStar')).toBe(true)
    expect(isImportedSourceRedundantWithDealSource('CoStar', 'CoStar')).toBe(true)
    expect(isImportedSourceRedundantWithDealSource('Deal Machine', 'CoStar')).toBe(false)
  })

  it('hides import note when redundant with deal source', () => {
    expect(
      formatImportNote(payload({ source: 'skip as costar', deal_source: 'CoStar' })),
    ).toBeNull()
  })

  it('keeps import note when it adds distinct provenance', () => {
    expect(
      formatImportNote(payload({ source: 'Driving for dollars sheet', deal_source: 'CoStar' })),
    ).toBe('Driving for dollars sheet')
  })
})
