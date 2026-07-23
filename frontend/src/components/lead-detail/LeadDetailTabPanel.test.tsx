import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { LeadDetailTabPanel } from '@/components/lead-detail/LeadDetailTabPanel'
import type { CommandCenterPayload, PropertyDetail } from '@/types'

function renderInfo(
  commandCenter: Partial<CommandCenterPayload>,
  lead: Partial<PropertyDetail> = {},
) {
  const commandCenterData = {
    id: 1,
    owner_first_name: 'Hilberto',
    owner_last_name: 'Olivier',
    property_street: '853 W George',
    property_city: 'Chicago',
    property_state: 'IL',
    lead_score: 50,
    lead_status: 'skip_trace',
    contacts: [
      {
        id: 10,
        first_name: 'Hilberto',
        last_name: 'Olivier',
        role: 'owner',
        is_primary: true,
        phones: [],
        emails: [],
      },
    ],
    mailing_address: '100 Prior Ln',
    mailing_city: 'Chicago',
    mailing_state: 'IL',
    mailing_zip: '60614',
    recommended_action: {
      value: 'hold',
      recommended_contact_method: null,
      label: 'Hold',
      explanation: null,
      signals: {},
    },
    open_tasks: [],
    timeline: { entries: [], total: 0, page: 1, per_page: 25 },
    ...commandCenter,
  } as CommandCenterPayload

  const leadData = {
    id: 1,
    owner_first_name: 'Hilberto',
    owner_last_name: 'Olivier',
    property_street: '853 W George',
    mailing_address: '100 Prior Ln',
    mailing_city: 'Chicago',
    mailing_state: 'IL',
    mailing_zip: '60614',
    contacts: commandCenterData.contacts,
    enrichment_records: [],
    marketing_lists: [],
    analysis_session: null,
    ...lead,
  } as PropertyDetail

  return render(
    <MemoryRouter>
      <LeadDetailTabPanel
        leadId={1}
        leadData={leadData}
        commandCenterData={commandCenterData}
        scoreLoading={false}
      />
    </MemoryRouter>,
  )
}

describe('LeadDetailTabPanel prior-owner Info', () => {
  it('labels contacts Past owner, shows mailing, and banners when stale', () => {
    renderInfo({
      contacts_likely_prior_owner: true,
      contacts_stale_since: '2024-07-17',
      past_owners: [
        {
          id: 9,
          captured_at: '2024-07-18T12:00:00Z',
          reason: 'recent_sale',
          sale_date: '2024-07-17',
          owner_names: [{ first_name: 'Hilberto', last_name: 'Olivier' }],
          phones: [],
          emails: [],
          mailing_address: '100 Prior Ln',
        },
      ],
    })

    expect(screen.getByTestId('info-likely-prior-owner-banner')).toBeInTheDocument()
    expect(screen.getByTestId('info-past-owner-contact')).toHaveTextContent('Past owner')
    expect(screen.getByTestId('info-past-owner-contact')).toHaveTextContent('100 Prior Ln')
    // Lazy recent_sale for same sale is hidden to avoid duplicating live Past owner
    expect(screen.queryByTestId('info-past-owners')).not.toBeInTheDocument()
  })

  it('keeps Owner label and shows past_owners table when not stale', () => {
    renderInfo({
      contacts_likely_prior_owner: false,
      past_owners: [
        {
          id: 11,
          captured_at: '2024-01-01T12:00:00Z',
          reason: 'contact_replaced',
          sale_date: '2023-01-01',
          owner_names: [{ first_name: 'Prior', last_name: 'Seller' }],
          phones: [{ value: '555-0100' }],
          emails: [],
          mailing_address: '9 Old St',
        },
      ],
    })

    expect(screen.queryByTestId('info-likely-prior-owner-banner')).not.toBeInTheDocument()
    expect(screen.getByTestId('info-owner-contact')).toHaveTextContent('Owner')
    expect(screen.getByTestId('info-past-owners')).toBeInTheDocument()
    expect(screen.getByTestId('info-past-owner-11')).toHaveTextContent('Prior Seller')
    expect(screen.getByTestId('info-past-owner-11')).toHaveTextContent('9 Old St')
  })

  it('shows Other Addresses with mailing fields on Info', () => {
    renderInfo({}, { returned_addresses: '200 Alt Ave, Chicago IL' })

    expect(screen.getByTestId('info-owner-contact')).toHaveTextContent('100 Prior Ln')
    expect(screen.getByTestId('info-owner-contact')).toHaveTextContent('Other Addresses')
    expect(screen.getByTestId('info-owner-contact')).toHaveTextContent('200 Alt Ave, Chicago IL')
  })

  it('does not show Additional Address from address_2 on Info', () => {
    renderInfo({}, { address_2: '2041 W Cuyler Ave Chicago IL 60618' })

    expect(screen.getByTestId('info-owner-contact')).toHaveTextContent('100 Prior Ln')
    expect(screen.getByTestId('info-owner-contact')).not.toHaveTextContent('Additional Address')
    expect(screen.getByTestId('info-owner-contact')).not.toHaveTextContent(
      '2041 W Cuyler Ave Chicago IL 60618',
    )
  })

  it('omits Other Addresses when returned_addresses is blank', () => {
    renderInfo({}, { returned_addresses: '   ' })

    expect(screen.getByTestId('info-owner-contact')).not.toHaveTextContent('Other Addresses')
  })
})

describe('LeadDetailTabPanel Marketing mail history', () => {
  it('shows normalized legacy mailer history on Marketing tab', () => {
    render(
      <MemoryRouter initialEntries={['/leads/1?tab=marketing']}>
        <LeadDetailTabPanel
          leadId={1}
          leadData={{
            id: 1,
            owner_first_name: 'Taylor',
            owner_last_name: 'G',
            property_street: '1023 W WELLINGTON AVE',
            mailing_address: '5N290 Fox Bluff Dr',
            mailing_city: 'Saint Charles',
            mailing_state: 'IL',
            mailing_zip: '60175',
            contacts: [],
            enrichment_records: [],
            marketing_lists: [],
            analysis_session: null,
            mailer_history: 'Boyfriend, OLM, Blue,  6/21/2024',
          } as unknown as PropertyDetail}
          commandCenterData={{
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
          } as unknown as CommandCenterPayload}
          scoreLoading={false}
        />
      </MemoryRouter>,
    )

    expect(screen.getByText('Mail history')).toBeInTheDocument()
    expect(screen.getByText('1 mailer')).toBeInTheDocument()
    expect(screen.getByText('Boyfriend, OLM, Blue')).toBeInTheDocument()
    expect(screen.getByText('6/21/2024')).toBeInTheDocument()
    expect(screen.getByText(/not a member of any marketing lists/i)).toBeInTheDocument()
  })
})
