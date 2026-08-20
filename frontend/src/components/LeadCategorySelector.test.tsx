import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LeadCategorySelector } from '@/components/LeadCategorySelector'
import { commandCenterService } from '@/services/api'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    updateCategory: vi.fn(),
  },
}))

describe('LeadCategorySelector', () => {
  beforeEach(() => {
    vi.mocked(commandCenterService.updateCategory).mockResolvedValue({
      lead_category: 'residential',
      lead_category_locked: true,
      property_type: null,
      lead_score: 40,
    })
  })

  it('opens menu and saves Residential (not a silent no-op)', async () => {
    const user = userEvent.setup()
    const onChanged = vi.fn()
    render(
      <LeadCategorySelector
        leadId={42}
        category="commercial"
        onChanged={onChanged}
      />,
    )
    expect(screen.getByTestId('lead-category-selector')).toHaveTextContent('Commercial')
    await user.click(screen.getByTestId('lead-category-selector'))
    expect(screen.getByTestId('lead-category-menu')).toBeInTheDocument()
    await user.click(screen.getByTestId('lead-category-option-residential'))
    await waitFor(() => {
      expect(commandCenterService.updateCategory).toHaveBeenCalledWith(42, 'residential')
    })
    await waitFor(() => {
      expect(onChanged).toHaveBeenCalledWith('residential')
    })
  })
})
