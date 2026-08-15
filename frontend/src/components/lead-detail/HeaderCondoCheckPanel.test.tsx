import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HeaderCondoCheckPanel, humanizeCondoDriver } from './HeaderCondoCheckPanel'
import type { CommandCenterPayload } from '@/types'

function basePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: null,
    owner_last_name: null,
    property_street: '3715-3721 N Leavitt St',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: { value: 'nurture', label: 'Nurture', explanation: '', signals: {} },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    ...overrides,
  }
}

describe('humanizeCondoDriver', () => {
  it('maps known rules to short labels', () => {
    expect(humanizeCondoDriver('rule_7_missing_data')).toBe('Missing PINs / data')
    expect(humanizeCondoDriver('rule_4b_commercial_few_pins')).toBe(
      'Few PINs — whole building',
    )
    expect(humanizeCondoDriver('rule_5_multiple_pins_single_owner')).toBe(
      'Multiple PINs — single owner',
    )
  })

  it('strips letter-suffixed rule ids without leaving Rule 4b junk', () => {
    expect(humanizeCondoDriver('rule_4b_unknown_driver')).toBe('Unknown Driver')
  })
})

describe('HeaderCondoCheckPanel', () => {
  it('settles condo check panel with confidence circle and reason drivers', () => {
    render(
      <HeaderCondoCheckPanel
        commandCenterData={basePayload({
          lead_category: 'commercial',
          condo_risk_status: 'needs_review',
          condo_confidence: 'low',
          condo_check_reason: 'Incomplete data (missing PINs) — cannot classify reliably',
          condo_check_drivers: ['rule_7_missing_data'],
          condo_checked_at: '2026-07-01T12:00:00Z',
          condo_analysis_id: 257,
        })}
      />,
    )
    expect(screen.getByTestId('header-condo-check')).toBeInTheDocument()
    expect(screen.getByTestId('header-condo-confidence-value')).toHaveTextContent('30%')
    expect(screen.getByTestId('header-condo-verdict')).toHaveTextContent('Check unclear')
    expect(screen.getByTestId('header-condo-drivers')).toHaveTextContent('Missing PINs / data')
    expect(screen.getByTestId('header-condo-updated')).toHaveTextContent(/Updated:/)
  })

  it('invokes Building ownership scroll on click', async () => {
    const onOpen = vi.fn()
    const user = userEvent.setup()
    render(
      <HeaderCondoCheckPanel
        commandCenterData={basePayload({
          lead_category: 'commercial',
          condo_risk_status: 'needs_review',
          condo_confidence: 'low',
          condo_analysis_id: 1,
        })}
        onOpenBuildingOwnership={onOpen}
      />,
    )
    await user.click(screen.getByTestId('header-condo-check'))
    expect(onOpen).toHaveBeenCalled()
  })

  it('hides for plain residential without condo signals', () => {
    render(
      <HeaderCondoCheckPanel
        commandCenterData={basePayload({
          lead_category: 'residential',
          property_street: '123 Main St',
        })}
      />,
    )
    expect(screen.queryByTestId('header-condo-check')).not.toBeInTheDocument()
  })

  it('shows for CoStar deal_source even when category still residential', () => {
    render(
      <HeaderCondoCheckPanel
        commandCenterData={basePayload({
          lead_category: 'residential',
          deal_source: 'CoStar',
          property_street: '3715-3721 N Leavitt St',
        })}
      />,
    )
    expect(screen.getByTestId('header-condo-check')).toBeInTheDocument()
  })
})
