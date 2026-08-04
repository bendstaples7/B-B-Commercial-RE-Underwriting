import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThemeProvider, createTheme } from '@mui/material'
import { MailHistorySection } from './MailHistorySection'
import type { CommandCenterPayload, PropertyDetail } from '@/types'

const theme = createTheme()

function basePayload(overrides: Partial<CommandCenterPayload> = {}): CommandCenterPayload {
  return {
    id: 1,
    owner_first_name: 'Taylor',
    owner_last_name: 'G',
    property_street: '1023 W WELLINGTON AVE',
    lead_score: 50,
    lead_status: 'skip_trace',
    contacts: [],
    recommended_action: {
      value: 'nurture',
      recommended_contact_method: 'phone',
      label: 'Nurture',
      explanation: null,
      signals: {},
    },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 25 },
    ...overrides,
  } as CommandCenterPayload
}

describe('MailHistorySection', () => {
  it('shows normalized legacy mailer history', () => {
    render(
      <ThemeProvider theme={theme}>
        <MailHistorySection
          commandCenterData={basePayload()}
          propertyDetail={
            {
              id: 1,
              mailer_history: 'Boyfriend, OLM, Blue,  6/21/2024',
              marketing_lists: [],
            } as unknown as PropertyDetail
          }
        />
      </ThemeProvider>,
    )

    expect(screen.getByTestId('mail-history-section')).toBeInTheDocument()
    expect(screen.getByText('Mail history')).toBeInTheDocument()
    expect(screen.getByText('1 mailer')).toBeInTheDocument()
    expect(screen.getByText('Boyfriend, OLM, Blue')).toBeInTheDocument()
    expect(screen.getByText('6/21/2024')).toBeInTheDocument()
    expect(screen.getByText(/No attributed responses/i)).toBeInTheDocument()
  })

  it('labels timeline-sourced mailers as Timeline (not Imported)', () => {
    render(
      <ThemeProvider theme={theme}>
        <MailHistorySection
          commandCenterData={basePayload({
            mailer_history_summary: {
              count: 1,
              last_sent_at: '02/01/2024',
              rows: [
                {
                  id: 'tl-1',
                  sent_at: '02/01/2024',
                  label: 'Legacy letter',
                  creative: null,
                  template_name: null,
                  campaign_id: null,
                  olc_order_id: null,
                  address_feedback: null,
                  cancelled: false,
                  source: 'timeline',
                },
              ],
            },
          } as Partial<CommandCenterPayload>)}
          propertyDetail={
            {
              id: 1,
              mailer_history: null,
              marketing_lists: [],
            } as unknown as PropertyDetail
          }
        />
      </ThemeProvider>,
    )
    expect(screen.getByText('Timeline')).toBeInTheDocument()
    expect(screen.queryByText('Imported')).not.toBeInTheDocument()
  })

  it('shows returned addresses and attributed responses when present', () => {
    render(
      <ThemeProvider theme={theme}>
        <MailHistorySection
          commandCenterData={basePayload({
            mail_queue_status: 'queued',
            mail_attributed_responses: [
              {
                id: 9,
                event_type: 'call_logged',
                occurred_at: '2024-02-01T12:00:00Z',
                summary: 'Callback after letter',
                metadata: { mail_campaign_id: 44 },
              },
            ],
          })}
          propertyDetail={
            {
              id: 1,
              returned_addresses: '200 Alt Ave',
              mailer_history: null,
            } as unknown as PropertyDetail
          }
        />
      </ThemeProvider>,
    )

    expect(screen.getByText('In mail queue')).toBeInTheDocument()
    expect(screen.getByText(/Returned addresses: 200 Alt Ave/)).toBeInTheDocument()
    expect(screen.getByText('Callback after letter')).toBeInTheDocument()
    expect(screen.getByText('44')).toBeInTheDocument()
  })
})
