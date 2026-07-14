/**
 * LeadBriefingPanel — on-demand briefing UI smoke tests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/testUtils'
import userEvent from '@testing-library/user-event'
import { LeadBriefingPanel } from '@/components/LeadBriefingPanel'
import { commandCenterService } from '@/services/api'

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return {
    ...actual,
    commandCenterService: {
      ...actual.commandCenterService,
      generateBriefing: vi.fn(),
    },
  }
})

describe('LeadBriefingPanel', () => {
  beforeEach(() => {
    vi.mocked(commandCenterService.generateBriefing).mockReset()
  })

  it('shows generate CTA and loads five bullets on click', async () => {
    vi.mocked(commandCenterService.generateBriefing).mockResolvedValue({
      lead_id: 1,
      bullets: ['One', 'Two', 'Three', 'Four', 'Five'],
      generated_at: '2026-07-14T16:00:00.000Z',
      timeline_entries_used: 3,
      open_tasks_used: 1,
    })
    const user = userEvent.setup()
    render(<LeadBriefingPanel leadId={1} />)

    expect(screen.getByTestId('lead-briefing-panel')).toBeInTheDocument()
    await user.click(screen.getByTestId('lead-briefing-generate'))

    await waitFor(() => {
      expect(screen.getByTestId('lead-briefing-bullets')).toBeInTheDocument()
    })
    expect(screen.getByTestId('lead-briefing-bullet-0')).toHaveTextContent('One')
    expect(screen.getByTestId('lead-briefing-bullet-4')).toHaveTextContent('Five')
    expect(commandCenterService.generateBriefing).toHaveBeenCalledWith(1)
  })

  it('shows an error when generation fails', async () => {
    vi.mocked(commandCenterService.generateBriefing).mockRejectedValue({
      response: { data: { message: 'GOOGLE_AI_API_KEY is not set' } },
    })
    const user = userEvent.setup()
    render(<LeadBriefingPanel leadId={2} />)

    await user.click(screen.getByTestId('lead-briefing-generate'))

    await waitFor(() => {
      expect(screen.getByTestId('lead-briefing-error')).toHaveTextContent(
        'GOOGLE_AI_API_KEY is not set',
      )
    })
  })

  it('hydrates from initialBriefing and labels Refresh', async () => {
    render(
      <LeadBriefingPanel
        leadId={3}
        initialBriefing={{
          bullets: ['Last contact was Monday.', 'Next is a walkthrough.', 'C', 'D', 'E'],
          generated_at: '2026-07-10T12:00:00.000Z',
          updated_at: '2026-07-10T12:00:00.000Z',
          mode: 'create',
        }}
      />,
    )

    expect(screen.getByTestId('lead-briefing-bullet-0')).toHaveTextContent('Last contact was Monday.')
    expect(screen.getByTestId('lead-briefing-generate')).toHaveTextContent('Refresh')
    expect(commandCenterService.generateBriefing).not.toHaveBeenCalled()
  })
})
