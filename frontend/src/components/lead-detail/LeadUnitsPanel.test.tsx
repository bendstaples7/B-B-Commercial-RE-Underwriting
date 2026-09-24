import { act, fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { render } from '@/test/testUtils'
import { leadService } from '@/services/leadApi'
import type { CommandCenterPayload } from '@/types'
import { LeadUnitsPanel } from './LeadUnitsPanel'

vi.mock('@/services/leadApi', () => ({
  leadService: {
    replaceLeadUnits: vi.fn(),
  },
}))

function commandCenterData(
  leadId: number,
  label: string,
): CommandCenterPayload {
  return {
    id: leadId,
    lead_units: [
      {
        id: leadId * 10,
        lead_id: leadId,
        unit_label: label,
        unit_type: 'residential',
        beds: null,
        baths: null,
        sqft: null,
        current_rent: null,
        sort_order: 0,
      },
    ],
    lead_subtype: null,
  } as CommandCenterPayload
}

describe('LeadUnitsPanel', () => {
  it('ignores a save response for a previous lead after navigation', async () => {
    let resolveSave: (value: Awaited<ReturnType<typeof leadService.replaceLeadUnits>>) => void = () => {}
    vi.mocked(leadService.replaceLeadUnits).mockReturnValue(
      new Promise((resolve) => {
        resolveSave = resolve
      }),
    )

    const { rerender } = render(
      <LeadUnitsPanel leadId={1} commandCenterData={commandCenterData(1, 'Unit A')} />,
    )

    fireEvent.change(screen.getByTestId('cc-lead-units-label-0'), {
      target: { value: 'Edited Unit A' },
    })
    fireEvent.click(screen.getByTestId('cc-lead-units-save'))
    expect(leadService.replaceLeadUnits).toHaveBeenCalledWith(1, {
      lead_subtype: null,
      units: [
        expect.objectContaining({
          unit_label: 'Edited Unit A',
          unit_type: 'residential',
          sort_order: 0,
        }),
      ],
    })

    rerender(
      <LeadUnitsPanel leadId={2} commandCenterData={commandCenterData(2, 'Unit B')} />,
    )
    expect(screen.getByTestId('cc-lead-units-label-0')).toHaveValue('Unit B')

    await act(async () => {
      resolveSave({
        lead_id: 1,
        lead_subtype: null,
        units: 1,
        lead_units: [
          {
            id: 10,
            lead_id: 1,
            unit_label: 'Saved Unit A',
            unit_type: 'residential',
            beds: null,
            baths: null,
            sqft: null,
            current_rent: null,
            sort_order: 0,
          },
        ],
      })
    })

    expect(screen.getByTestId('cc-lead-units-label-0')).toHaveValue('Unit B')
  })
})
