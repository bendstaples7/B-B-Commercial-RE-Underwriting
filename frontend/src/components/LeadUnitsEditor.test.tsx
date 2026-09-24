import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { render } from '@/test/testUtils'
import { LeadUnitsEditor, emptyLeadUnitDraft, type LeadUnitDraft } from './LeadUnitsEditor'

describe('LeadUnitsEditor', () => {
  it('adds the next unused default label after removing a middle row', () => {
    const onChange = vi.fn()
    const units: LeadUnitDraft[] = [
      emptyLeadUnitDraft(0),
      emptyLeadUnitDraft(2),
    ]

    render(<LeadUnitsEditor units={units} onChange={onChange} />)

    fireEvent.click(screen.getByTestId('lead-units-add'))

    expect(onChange).toHaveBeenCalledWith([
      units[0],
      units[1],
      expect.objectContaining({ unit_label: 'Unit 2' }),
    ])
  })
})
