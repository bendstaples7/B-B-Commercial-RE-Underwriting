import type { MailCampaignGapKind, MailCampaignGapLead } from '@/services/openLetterApi'

function cell(value: string | number | null | undefined): string {
  const raw = value == null ? '' : String(value)
  // Keep Excel-friendly TSV: strip tabs/newlines inside cells.
  const cleaned = raw.replace(/[\t\r\n]+/g, ' ').trim()
  return /^[=+\-@]/.test(cleaned) ? `'${cleaned}` : cleaned
}

function dispositionLabel(row: MailCampaignGapLead): string {
  if (row.disposition === 'requeued') return 'Requeued'
  if (row.disposition === 'support') return 'Support'
  if (row.disposition === 'invalid_local') return 'Invalid'
  return row.disposition || ''
}

/** Tab-separated table for pasting into Excel / Sheets. */
export function formatGapLeadsTsv(
  leads: MailCampaignGapLead[],
  kind: MailCampaignGapKind | null,
): string {
  const includeOmit = kind === 'olc_omitted'
  const headers = [
    'Lead ID',
    'Owner',
    'Property',
    'Mailing',
    'Reason',
    'Where now',
    ...(includeOmit ? ['Omit count'] : []),
  ]
  const lines = [headers.join('\t')]
  for (const row of leads) {
    const cols = [
      cell(row.lead_id),
      cell(row.owner_name || `Lead ${row.lead_id}`),
      cell(row.property_street),
      cell(row.mailing_address),
      cell(row.reason),
      cell(row.resolution || dispositionLabel(row)),
    ]
    if (includeOmit) {
      cols.push(cell(row.omit_count != null ? String(row.omit_count) : dispositionLabel(row)))
    }
    lines.push(cols.join('\t'))
  }
  return lines.join('\n')
}
