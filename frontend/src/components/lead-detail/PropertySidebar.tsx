import { useState, type ReactNode } from 'react'
import {
  Box,
  Chip,
  IconButton,
  Link,
  Paper,
  Tooltip,
  Typography,
} from '@mui/material'
import PhoneIcon from '@mui/icons-material/Phone'
import EmailIcon from '@mui/icons-material/Email'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { formatPhoneNumber, phoneCopyText, phoneTelHref } from '@/utils/phone'
import type { CommandCenterPayload, LeadPhone } from '@/types'
import { formatImportedSource } from './leadDetailFormatters'
import { formatPhoneConfidence } from '@/utils/helpers'

function SidebarSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography
        variant="overline"
        sx={{ fontSize: '0.65rem', letterSpacing: 1, color: 'text.disabled', display: 'block', mb: 0.5 }}
      >
        {title}
      </Typography>
      {children}
    </Box>
  )
}

function SidebarRow({
  label,
  value,
  alwaysShow = false,
  testId,
}: {
  label: string
  value: ReactNode
  alwaysShow?: boolean
  testId?: string
}) {
  const isEmpty = value == null || value === ''
  if (isEmpty && !alwaysShow) return null
  return (
    <Box sx={{ display: 'flex', gap: 1, mb: 0.5 }} data-testid={testId}>
      <Typography variant="caption" color="text.secondary" sx={{ minWidth: 90, flexShrink: 0 }}>
        {label}
      </Typography>
      <Typography
        variant="caption"
        sx={{ wordBreak: 'break-word', color: isEmpty ? 'text.disabled' : 'text.primary' }}
      >
        {isEmpty ? '—' : value}
      </Typography>
    </Box>
  )
}

function CopyablePhone({ phone }: { phone: LeadPhone | string }) {
  const [copied, setCopied] = useState(false)
  const value = typeof phone === 'string' ? phone : phone.value
  const confidenceLabel = typeof phone === 'string'
    ? null
    : formatPhoneConfidence(phone.confidence_score, phone.notes)
  const displayPhone = formatPhoneNumber(value)
  const handleCopy = () => {
    navigator.clipboard.writeText(phoneCopyText(value))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5, flexWrap: 'wrap' }}>
      <PhoneIcon sx={{ fontSize: 13, color: 'text.secondary' }} />
      <Link href={phoneTelHref(value)} variant="caption" underline="hover">
        {displayPhone}
      </Link>
      {confidenceLabel && (
        <Tooltip title={confidenceLabel}>
          <Chip
            label={confidenceLabel}
            size="small"
            variant="outlined"
            sx={{ height: 18, fontSize: '0.65rem', maxWidth: 160 }}
            data-testid={`phone-confidence-${value}`}
          />
        </Tooltip>
      )}
      <Tooltip title={copied ? 'Copied!' : 'Copy'}>
        <IconButton size="small" onClick={handleCopy} sx={{ p: 0.25 }}>
          <ContentCopyIcon sx={{ fontSize: 11 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

function CopyableEmail({ email }: { email: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(email)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5 }}>
      <EmailIcon sx={{ fontSize: 13, color: 'text.secondary' }} />
      <Link href={`mailto:${email}`} variant="caption" underline="hover" noWrap>
        {email}
      </Link>
      <Tooltip title={copied ? 'Copied!' : 'Copy'}>
        <IconButton size="small" onClick={handleCopy} sx={{ p: 0.25 }}>
          <ContentCopyIcon sx={{ fontSize: 11 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

export interface PropertySidebarProps {
  commandCenterData: CommandCenterPayload
}

export function PropertySidebar({ commandCenterData }: PropertySidebarProps) {
  type SidebarExtras = {
    phones?: LeadPhone[]
    emails?: string[]
    socials?: string
    lot_size?: number | string
    units?: number | string | null
    units_allowed?: number | string | null
    zoning?: string | null
    tax_bill_2021?: number | string | null
    most_recent_sale?: string | null
    address_2?: string | null
    returned_addresses?: string | null
    needs_skip_trace?: boolean
    skip_tracer?: string | null
    date_skip_traced?: string | null
    mailer_history?: string | Record<string, unknown> | null
    up_next_to_mail?: boolean
    marketing_memberships?: Array<{
      list_name: string
      outreach_status: string
      status_updated_at?: string
      added_at?: string
    }>
    data_source?: string | null
    date_identified?: string | null
    created_at?: string | null
    follow_up_date?: string | null
  }

  const data = commandCenterData as CommandCenterPayload & SidebarExtras

  const ownerName =
    [commandCenterData.owner_first_name, commandCenterData.owner_last_name]
      .filter(Boolean)
      .join(' ') || ''
  const owner2Name =
    [commandCenterData.owner_2_first_name, commandCenterData.owner_2_last_name]
      .filter(Boolean)
      .join(' ') || ''

  const phones: LeadPhone[] = data.phones?.length
    ? data.phones
    : [
        commandCenterData.phone_1,
        commandCenterData.phone_2,
        commandCenterData.phone_3,
        commandCenterData.phone_4,
        commandCenterData.phone_5,
        commandCenterData.phone_6,
        commandCenterData.phone_7,
      ]
        .filter(Boolean)
        .map((value) => ({ value: value as string, confidence_score: 50 }))

  const emails: string[] = data.emails?.length
    ? data.emails
    : [
        commandCenterData.email_1,
        commandCenterData.email_2,
        commandCenterData.email_3,
        commandCenterData.email_4,
        commandCenterData.email_5,
      ].filter(Boolean) as string[]

  const marketingMemberships = data.marketing_memberships

  return (
    <Paper
      variant="outlined"
      data-testid="property-sidebar"
      sx={{
        position: 'sticky',
        top: 80,
        maxHeight: 'calc(100vh - 100px)',
        overflowY: 'auto',
        display: { xs: 'none', sm: 'none', md: 'none', lg: 'block' },
        minWidth: 280,
        maxWidth: 320,
        flexShrink: 0,
        p: 2,
      }}
    >
      <SidebarSection title="Contact Info">
        {ownerName && (
          <Typography variant="caption" fontWeight={600} display="block" sx={{ mb: 0.75 }}>
            {ownerName}
          </Typography>
        )}
        {owner2Name && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
            {owner2Name}
          </Typography>
        )}
        {phones.map((p, i) => (
          <CopyablePhone key={p.id ?? `${p.value}-${i}`} phone={p} />
        ))}
        {emails.map((e, i) => (
          <CopyableEmail key={i} email={e} />
        ))}
        {data.socials && <SidebarRow label="Socials" value={data.socials} />}
      </SidebarSection>

      {(owner2Name || commandCenterData.ownership_type || commandCenterData.acquisition_date) && (
        <SidebarSection title="Owner">
          {owner2Name && <SidebarRow label="Owner 2" value={owner2Name} />}
          <SidebarRow label="Type" value={commandCenterData.ownership_type} />
          <SidebarRow label="Acquired" value={commandCenterData.acquisition_date} />
        </SidebarSection>
      )}

      <SidebarSection title="Property">
        {(commandCenterData.property_street || commandCenterData.property_city) && (
          <Box sx={{ mb: 0.75 }}>
            {commandCenterData.property_street && (
              <Typography variant="caption" fontWeight={600} display="block">
                {commandCenterData.property_street}
              </Typography>
            )}
            {(commandCenterData.property_city || commandCenterData.property_state || commandCenterData.property_zip) && (
              <Typography variant="caption" color="text.secondary" display="block">
                {[commandCenterData.property_city, commandCenterData.property_state, commandCenterData.property_zip]
                  .filter(Boolean)
                  .join(', ')}
              </Typography>
            )}
          </Box>
        )}
        <SidebarRow label="Type" value={commandCenterData.property_type} />
        <SidebarRow
          label="Beds / Baths"
          value={
            commandCenterData.bedrooms != null || commandCenterData.bathrooms != null
              ? `${commandCenterData.bedrooms ?? '?'} bd / ${commandCenterData.bathrooms ?? '?'} ba`
              : null
          }
        />
        <SidebarRow
          label="Sq Ft"
          value={
            commandCenterData.square_footage != null
              ? commandCenterData.square_footage.toLocaleString()
              : null
          }
        />
        <SidebarRow label="Year Built" value={commandCenterData.year_built} />
        <SidebarRow
          label="Lot Size"
          value={data.lot_size != null ? `${Number(data.lot_size).toLocaleString()} sqft` : null}
        />
        <SidebarRow label="Units" value={data.units} />
        <SidebarRow label="Units Allowed" value={data.units_allowed} />
        <SidebarRow label="Zoning" value={data.zoning} />
        <SidebarRow label="PIN" value={commandCenterData.county_assessor_pin} />
        <SidebarRow
          label="Tax Bill"
          value={
            data.tax_bill_2021 != null ? `$${Number(data.tax_bill_2021).toLocaleString()}` : null
          }
        />
        <SidebarRow label="Last Sale" value={data.most_recent_sale} />
        <SidebarRow
          label="Deal Source"
          value={commandCenterData.deal_source}
          alwaysShow
          testId="sidebar-deal-source"
        />
        <Box sx={{ mt: 0.5, mb: 0.75 }} data-testid="sidebar-deal-description">
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.25 }}>
            Deal Description
          </Typography>
          <Typography
            variant="body2"
            sx={{
              whiteSpace: 'pre-wrap',
              color: commandCenterData.deal_description ? 'text.primary' : 'text.disabled',
            }}
          >
            {commandCenterData.deal_description || '—'}
          </Typography>
        </Box>
        {data.address_2 && <SidebarRow label="Address 2" value={data.address_2} />}
        {data.returned_addresses && (
          <SidebarRow label="Other Addresses" value={data.returned_addresses} />
        )}
      </SidebarSection>

      {(commandCenterData.mailing_address || commandCenterData.mailing_city) && (
        <SidebarSection title="Owner Mailing Address">
          {commandCenterData.mailing_address && (
            <Typography variant="caption" display="block">{commandCenterData.mailing_address}</Typography>
          )}
          {(commandCenterData.mailing_city || commandCenterData.mailing_state || commandCenterData.mailing_zip) && (
            <Typography variant="caption" display="block">
              {[commandCenterData.mailing_city, commandCenterData.mailing_state, commandCenterData.mailing_zip]
                .filter(Boolean)
                .join(', ')}
            </Typography>
          )}
        </SidebarSection>
      )}

      {(data.needs_skip_trace != null || data.skip_tracer || data.date_skip_traced) && (
        <SidebarSection title="Skip Trace">
          <SidebarRow
            label="Needed"
            value={data.needs_skip_trace != null ? (data.needs_skip_trace ? 'Yes' : 'No') : null}
          />
          <SidebarRow label="Tracer" value={data.skip_tracer} />
          <SidebarRow label="Date" value={data.date_skip_traced} />
        </SidebarSection>
      )}

      {(data.mailer_history != null || data.up_next_to_mail) && (
        <SidebarSection title="Mailer History">
          {Boolean(data.up_next_to_mail) && (
            <Chip label="Up Next to Mail" size="small" color="primary" sx={{ mb: 0.5 }} />
          )}
          {data.mailer_history != null && (
            <Typography
              variant="caption"
              sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', display: 'block' }}
            >
              {typeof data.mailer_history === 'string'
                ? data.mailer_history
                : JSON.stringify(data.mailer_history, null, 2)}
            </Typography>
          )}
        </SidebarSection>
      )}

      {marketingMemberships && marketingMemberships.length > 0 && (
        <SidebarSection title="Marketing Lists">
          {marketingMemberships.map((m, i) => (
            <Box key={i} sx={{ mb: 0.75 }}>
              <Typography variant="caption" fontWeight={500} display="block">{m.list_name}</Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                Status: {m.outreach_status}
                {m.status_updated_at && ` · Updated ${new Date(m.status_updated_at).toLocaleDateString()}`}
                {m.added_at && ` · Added ${new Date(m.added_at).toLocaleDateString()}`}
              </Typography>
            </Box>
          ))}
        </SidebarSection>
      )}

      <SidebarSection title="Import & Sync">
        <SidebarRow label="Imported Source" value={formatImportedSource(commandCenterData)} />
        <SidebarRow label="Category" value={commandCenterData.lead_category} />
        <SidebarRow label="Data Source" value={data.data_source} />
        <SidebarRow label="Identified" value={data.date_identified} />
        <SidebarRow
          label="Added"
          value={data.created_at ? new Date(data.created_at).toLocaleDateString() : null}
        />
        <SidebarRow
          label="Last Sync"
          value={
            commandCenterData.last_hubspot_sync_at
              ? new Date(commandCenterData.last_hubspot_sync_at).toLocaleDateString()
              : null
          }
        />
        <SidebarRow
          label="Last Contact"
          value={
            commandCenterData.last_contact_date
              ? new Date(commandCenterData.last_contact_date).toLocaleDateString()
              : null
          }
        />
        <SidebarRow label="Follow-up Date" value={data.follow_up_date} />
        <SidebarRow label="Added to HS" value={commandCenterData.date_added_to_hubspot} />
      </SidebarSection>

      <SidebarSection title="Data Quality">
        <SidebarRow
          label="Completeness"
          value={
            commandCenterData.data_completeness_score != null
              ? `${Math.round(commandCenterData.data_completeness_score)}%`
              : null
          }
        />
      </SidebarSection>
    </Paper>
  )
}
