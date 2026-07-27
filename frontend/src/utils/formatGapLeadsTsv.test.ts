import { describe, it, expect } from 'vitest'
import { formatGapLeadsTsv } from './formatGapLeadsTsv'

describe('formatGapLeadsTsv', () => {
  it('builds Excel-ready TSV with headers and lead id', () => {
    const text = formatGapLeadsTsv(
      [
        {
          lead_id: 4324,
          owner_name: 'Test Owner',
          property_street: '1104 W Wellington',
          mailing_address: null,
          reason: 'No owner mailing street address',
          resolution: 'Skip Trace',
        },
      ],
      'invalid_local',
    )
    expect(text).toBe(
      [
        'Lead ID\tOwner\tProperty\tMailing\tReason\tWhere now',
        '4324\tTest Owner\t1104 W Wellington\t\tNo owner mailing street address\tSkip Trace',
      ].join('\n'),
    )
  })

  it('includes omit count for olc_omitted kind', () => {
    const text = formatGapLeadsTsv(
      [
        {
          lead_id: 903,
          owner_name: 'Omitted',
          property_street: '1 Main',
          mailing_address: '2 Mail',
          reason: 'Not on OLC order',
          resolution: 'Ready to Mail',
          omit_count: 1,
        },
      ],
      'olc_omitted',
    )
    expect(text.split('\n')[0]).toContain('Omit count')
    expect(text.split('\n')[1]).toContain('\t1')
  })
})
