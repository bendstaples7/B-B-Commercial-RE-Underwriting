/**
 * Unit tests for Needs Review clarity popover content.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import {
  DuplicateReviewCallout,
  NeedsReviewClarityContent,
  NeedsReviewChipPopover,
} from './NeedsReviewClarityPanel'
import { commandCenterService } from '@/services/api'
import type { CommandCenterPayload } from '@/types'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    mergeInto: vi.fn(),
    dismissDuplicateReview: vi.fn(),
    clearReview: vi.fn(),
  },
}))

function basePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 10,
    owner_first_name: 'Ada',
    owner_last_name: 'Owner',
    property_street: '100 Main',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'mailing_no_contact_made',
    has_property_match: true,
    analysis_session_id: null,
    recommended_action: {
      value: 'ready_for_outreach',
      label: 'Ready',
      explanation: '',
      signals: {},
    },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    review_required: true,
    review_reason: 'New HubSpot activity',
    ...overrides,
  }
}

describe('NeedsReviewClarityContent', () => {
  beforeEach(() => {
    vi.mocked(commandCenterService.mergeInto).mockReset()
    vi.mocked(commandCenterService.dismissDuplicateReview).mockReset()
    vi.mocked(commandCenterService.clearReview).mockReset()
  })

  it('marks non-duplicate review as reviewed', async () => {
    const onResolved = vi.fn()
    vi.mocked(commandCenterService.clearReview).mockResolvedValue({
      lead_id: 10,
      cleared: true,
      previous_reason: 'New HubSpot activity',
    })
    render(
      <MemoryRouter>
        <NeedsReviewClarityContent
          leadId={10}
          commandCenterData={basePayload()}
          onResolved={onResolved}
        />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('needs-review-clarity-reason')).toHaveTextContent(
      'New HubSpot activity',
    )
    await userEvent.click(screen.getByTestId('needs-review-mark-reviewed'))
    await waitFor(() => {
      expect(commandCenterService.clearReview).toHaveBeenCalledWith(10)
      expect(onResolved).toHaveBeenCalledWith({ kind: 'cleared' })
    })
  })

  it('shows Possible duplicate records and Not a duplicate action', async () => {
    const onResolved = vi.fn()
    vi.mocked(commandCenterService.dismissDuplicateReview).mockResolvedValue({
      lead_id: 10,
      dismissed: true,
    })
    render(
      <MemoryRouter>
        <NeedsReviewClarityContent
          leadId={10}
          commandCenterData={basePayload({
            review_reason: 'duplicate_lead_cluster',
            duplicate_cluster: {
              cluster_ids: [10, 20],
              suggested_winner_id: 20,
              confidence: 'ambiguous',
              streets: { 10: '100 Main', 20: '100 Main Unit 2' },
              members: [
                {
                  id: 10,
                  property_street: '100 Main',
                  owner_display_name: 'Ada',
                  is_suggested_winner: false,
                },
                {
                  id: 20,
                  property_street: '100 Main Unit 2',
                  owner_display_name: 'Ada',
                  is_suggested_winner: true,
                  hubspot_confirmed: true,
                },
              ],
            },
          })}
          onResolved={onResolved}
        />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('needs-review-clarity-reason')).toHaveTextContent(
      'Possible duplicate records',
    )
    expect(screen.getByTestId('needs-review-cluster-compare-20')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-cluster-comparison')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-merge-into-winner')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-merge-into-winner')).toHaveTextContent(
      'Keep suggested (#20)',
    )
    await userEvent.click(screen.getByTestId('needs-review-dismiss-duplicate'))
    await waitFor(() => {
      expect(commandCenterService.dismissDuplicateReview).toHaveBeenCalledWith(10)
      expect(onResolved).toHaveBeenCalledWith({ kind: 'dismissed' })
    })
  })
})

describe('NeedsReviewChipPopover', () => {
  it('opens popover from Needs Review chip for non-duplicate reasons', async () => {
    render(
      <MemoryRouter>
        <NeedsReviewChipPopover
          leadId={10}
          commandCenterData={basePayload({
            review_reason: 'New HubSpot activity',
          })}
          onResolved={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('needs-review-clarity-panel')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('work-queue-strip-needs-review'))
    expect(await screen.findByTestId('needs-review-clarity-panel')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-clarity-reason')).toHaveTextContent(
      'New HubSpot activity',
    )
  })

  it('opens popover from inline Current queues name', async () => {
    render(
      <MemoryRouter>
        <NeedsReviewChipPopover
          leadId={10}
          commandCenterData={basePayload({
            review_reason: 'New HubSpot activity',
          })}
          variant="inline"
          viewingFrom
          onResolved={vi.fn()}
        />
      </MemoryRouter>,
    )
    const trigger = screen.getByTestId('work-queue-strip-needs-review')
    expect(trigger).toHaveAttribute('data-viewing-from', 'true')
    await userEvent.click(trigger)
    expect(await screen.findByTestId('needs-review-clarity-panel')).toBeInTheDocument()
  })

  it('scrolls to the duplicate callout instead of opening a popover', async () => {
    const scrollIntoView = vi.fn()
    const callout = document.createElement('div')
    callout.id = 'needs-review-duplicate-callout'
    callout.scrollIntoView = scrollIntoView
    document.body.appendChild(callout)

    render(
      <MemoryRouter>
        <NeedsReviewChipPopover
          leadId={10}
          commandCenterData={basePayload({
            review_reason: 'duplicate_lead_cluster',
          })}
          variant="inline"
          viewingFrom
          onResolved={vi.fn()}
        />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByTestId('work-queue-strip-needs-review'))
    expect(scrollIntoView).toHaveBeenCalled()
    expect(screen.queryByTestId('needs-review-clarity-popover')).not.toBeInTheDocument()
    callout.remove()
  })
})

describe('DuplicateReviewCallout', () => {
  it('shows this-vs-other comparison and dialog merge without a chip click', () => {
    render(
      <MemoryRouter>
        <DuplicateReviewCallout
          leadId={10}
          commandCenterData={basePayload({
            review_reason: 'duplicate_lead_cluster',
            duplicate_cluster: {
              cluster_ids: [10, 20],
              suggested_winner_id: 20,
              confidence: 'ambiguous',
              streets: { 10: '100 Main', 20: '100 Main Unit 2' },
              members: [
                {
                  id: 10,
                  property_street: '100 Main',
                  owner_display_name: 'Ada',
                  is_suggested_winner: false,
                },
                {
                  id: 20,
                  property_street: '100 Main Unit 2',
                  owner_display_name: 'Ada',
                  is_suggested_winner: true,
                  hubspot_confirmed: true,
                },
              ],
            },
          })}
          onResolved={vi.fn()}
          onOpenMerge={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('needs-review-duplicate-callout')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-cluster-comparison')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-open-merge')).toBeInTheDocument()
    expect(screen.queryByTestId('needs-review-merge-into-winner')).not.toBeInTheDocument()
    expect(screen.getByText('100 Main Unit 2')).toBeInTheDocument()
  })

  it('compares the active lead against a sibling while listing larger clusters', () => {
    render(
      <MemoryRouter>
        <DuplicateReviewCallout
          leadId={10}
          commandCenterData={basePayload({
            review_reason: 'duplicate_lead_cluster',
            duplicate_cluster: {
              cluster_ids: [10, 20, 30],
              suggested_winner_id: 20,
              confidence: 'ambiguous',
              streets: {
                10: '100 Main',
                20: '100 Main Unit 2',
                30: '100 Main Unit 3',
              },
              members: [
                {
                  id: 10,
                  property_street: '100 Main',
                  owner_display_name: 'Ada',
                  is_suggested_winner: false,
                },
                {
                  id: 20,
                  property_street: '100 Main Unit 2',
                  owner_display_name: 'Ada',
                  is_suggested_winner: true,
                  hubspot_confirmed: true,
                },
                {
                  id: 30,
                  property_street: '100 Main Unit 3',
                  owner_display_name: 'Ada',
                  is_suggested_winner: false,
                  has_phone: true,
                },
              ],
            },
          })}
          onResolved={vi.fn()}
          onOpenMerge={vi.fn()}
        />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('needs-review-cluster-comparison')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-cluster-compare-20')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-cluster-table')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-cluster-row-20')).toBeInTheDocument()
    expect(screen.getByTestId('needs-review-cluster-row-30')).toBeInTheDocument()
  })
})
