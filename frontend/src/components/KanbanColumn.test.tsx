/**
 * KanbanColumn header count — one chip, no duplicated total / visible / "showing".
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DndContext } from '@dnd-kit/core'
import { KanbanColumn } from './KanbanColumn'
import type { LeadKanbanCard, LeadKanbanColumn } from '@/types'

vi.mock('./DealCard', () => ({
  DealCard: ({ deal }: { deal: { id: number } }) => <div data-testid={`deal-${deal.id}`} />,
}))

function stubLead(id: number): LeadKanbanCard {
  return {
    id,
    property_address: `${id} Main`,
    owner_name: 'Owner',
    lead_status: null,
    recommended_action: null,
    lead_score: 1,
    lead_category: 'residential',
    source_type: 'manual',
    last_contact_date: null,
    analysis_complete: false,
    is_warm: false,
    has_phone: false,
    has_email: false,
    has_property_match: true,
  }
}

function renderColumn(column: LeadKanbanColumn, totalCount: number) {
  return render(
    <DndContext>
      <KanbanColumn column={column} totalCount={totalCount} onLoadMore={vi.fn()} />
    </DndContext>,
  )
}

describe('KanbanColumn header counts', () => {
  it('shows a single total chip when the column is fully loaded', () => {
    const column: LeadKanbanColumn = {
      id: 'skip_trace',
      label: 'Skip Trace',
      icon: '🔍',
      count: 2,
      sort_order: 1,
      leads: [stubLead(1), stubLead(2)],
    }

    renderColumn(column, 2)

    expect(screen.getByText('Skip Trace')).toBeInTheDocument()
    expect(screen.queryByText(/Skip Trace \(/)).not.toBeInTheDocument()
    expect(screen.getByLabelText('2 leads in Skip Trace')).toHaveTextContent('2')
    expect(screen.queryByText(/showing/i)).not.toBeInTheDocument()
  })

  it('shows one "loaded of total" chip when paginated (no separate showing caption)', () => {
    const leads = Array.from({ length: 50 }, (_, i) => stubLead(i + 1))

    const column: LeadKanbanColumn = {
      id: 'skip_trace',
      label: 'Skip Trace',
      icon: '🔍',
      count: 50,
      sort_order: 1,
      leads,
    }

    renderColumn(column, 708)

    expect(screen.getByText('Skip Trace')).toBeInTheDocument()
    expect(screen.getByLabelText('50 of 708 leads loaded in Skip Trace')).toHaveTextContent(
      '50 of 708',
    )
    expect(screen.queryByText(/showing/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Load all 658 more/i })).toBeInTheDocument()
  })
})
