/**
 * First-paint settle: unanswered-mail nudge dialog landmark.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { CommandCenterPayload } from '@/types'

vi.mock('@/services/api', () => ({
  commandCenterService: {
    getCommandCenter: vi.fn(),
    unansweredMailNudgeKeepCalling: vi.fn().mockResolvedValue({}),
    unansweredMailNudgeSwitchToMail: vi.fn().mockResolvedValue({}),
  },
  leadTaskService: {},
  leadScoreService: { getScore: vi.fn().mockResolvedValue({ latest: null }) },
  queueService: { getNavigation: vi.fn() },
  multifamilyService: {},
}))

vi.mock('@/services/leadApi', () => ({
  leadService: {
    getById: vi.fn().mockResolvedValue({ id: 4490, property_street: '1233 West Foster Avenue' }),
  },
}))

vi.mock('@/services/entityResolutionApi', () => ({
  entityResolutionApi: { getStatus: vi.fn().mockResolvedValue(null) },
}))

vi.mock('@/services/openLetterApi', () => ({
  default: {},
}))

vi.mock('@/components/LeadTaskList', () => ({
  LeadTaskList: () => null,
}))
vi.mock('@/components/LeadTimeline', () => ({
  LeadTimeline: () => null,
}))
vi.mock('@/components/LeadBriefingPanel', () => ({
  LeadBriefingPanel: () => null,
}))
vi.mock('@/components/LogActivityModal', () => ({
  LogActivityModal: () => null,
}))
vi.mock('@/components/RecommendedActionPanel', () => ({
  RecommendedActionPanel: () => null,
}))
vi.mock('@/components/lead-detail/LeadDetailTabPanel', () => ({
  LeadDetailTabPanel: () => null,
}))
vi.mock('@/components/lead-detail/PropertySidebar', () => ({
  PropertySidebar: () => null,
}))
vi.mock('@/components/BuildingOwnershipSection', () => ({
  BuildingOwnershipSection: () => null,
}))

import { commandCenterService } from '@/services/api'
import { UnifiedLeadCommandCenter } from '@/components/UnifiedLeadCommandCenter'

function basePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 4490,
    owner_first_name: 'Sam',
    owner_last_name: 'For Sale By Owner',
    property_street: '1233 West Foster Avenue',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 90,
    lead_status: 'negotiating_remote',
    has_property_match: true,
    analysis_session_id: null,
    unanswered_call_count: 3,
    unanswered_mail_nudge_owed: true,
    recommended_action: {
      value: 'call_ready',
      recommended_contact_method: 'phone',
      label: 'Call',
      explanation: '',
      signals: {},
    },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 20 },
    phones: [],
    ...overrides,
  } as CommandCenterPayload
}

describe('first-paint unanswered-mail nudge', () => {
  beforeEach(() => {
    vi.mocked(commandCenterService.getCommandCenter).mockResolvedValue(basePayload())
  })

  it('settles dialog landmark after command center load when nudge owed', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/leads/4490']}>
          <Routes>
            <Route path="/leads/:id" element={<UnifiedLeadCommandCenter leadId={4490} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const dialog = await waitFor(() =>
      screen.getByTestId('unanswered-mail-nudge-dialog'),
    )
    expect(dialog).toBeInTheDocument()
    expect(screen.getByText('Try Direct Mail instead?')).toBeInTheDocument()
    expect(screen.getByTestId('unanswered-mail-nudge-keep-calling')).toBeInTheDocument()
    expect(screen.getByTestId('unanswered-mail-nudge-switch')).toBeInTheDocument()
  })
})
