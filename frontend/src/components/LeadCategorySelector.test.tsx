import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
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
      timeline_entry: {
        id: 1,
        lead_id: 42,
        event_type: 'category_changed',
        occurred_at: '2026-08-20T00:00:00Z',
        source: 'manual',
        actor: 'test-user',
        summary: 'Lead category changed.',
        metadata: null,
        hubspot_activity_id: null,
        is_deleted: false,
        created_at: '2026-08-20T00:00:00Z',
      },
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

  it('keeps Residential / Commercial on one line (no mid-word shatter)', () => {
    const src = readFileSync(resolve(__dirname, './LeadCategorySelector.tsx'), 'utf8')
    expect(src).not.toMatch(/overflowWrap:\s*['"]break-word['"]/)
    expect(src).not.toMatch(/wordBreak:\s*['"]break-word['"]/)
    expect(src).toMatch(/whiteSpace:\s*['"]nowrap['"]/)
    expect(src).toMatch(/wordBreak:\s*['"]keep-all['"]/)
    expect(src).toMatch(/minWidth:\s*['"]max-content['"]/)
  })
})
