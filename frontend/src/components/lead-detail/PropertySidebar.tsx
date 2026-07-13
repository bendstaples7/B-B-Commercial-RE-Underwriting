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
import EmailIcon from '@mui/icons-material/Email'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import type { CommandCenterPayload, LeadPhone, PropertyContactSummary } from '@/types'
import { formatSaleDateFreshness } from '@/utils/saleDateFreshness'
import {
  isEntityContactName,
  ownerDisplayEntries,
} from '@/utils/propertyContacts'
import { formatImportNote } from './leadDetailFormatters'
import { PhoneRow } from '@/components/PhoneRow'
import { ccCardSx } from '@/components/lead-detail/commandCenterChrome'

const SIDEBAR_LABEL_SX = {
  flexShrink: 0,
  width: 108,
  textAlign: 'left' as const,
}

const SIDEBAR_VALUE_SX = {
  flex: 1,
  minWidth: 0,
  textAlign: 'right' as const,
  wordBreak: 'break-word' as const,
}

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
  valueFontWeight,
}: {
  label: string
  value: ReactNode
  alwaysShow?: boolean
  testId?: string
  valueFontWeight?: number
}) {
  const isEmpty = value == null || value === ''
  if (isEmpty && !alwaysShow) return null
  return (
    <Box
      sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 1, mb: 0.5 }}
      data-testid={testId}
    >
      <Typography variant="caption" color="text.secondary" sx={SIDEBAR_LABEL_SX}>
        {label}
      </Typography>
      <Typography
        variant="caption"
        fontWeight={valueFontWeight}
        sx={{
          ...SIDEBAR_VALUE_SX,
          whiteSpace: 'pre-line',
          color: isEmpty ? 'text.disabled' : 'text.primary',
        }}
      >
        {isEmpty ? '—' : value}
      </Typography>
    </Box>
  )
}

/** Label left / content right for non-text values (phones, emails, chips). */
function SidebarLabeledContent({
  label,
  children,
  testId,
}: {
  label: string
  children: ReactNode
  testId?: string
}) {
  return (
    <Box
      sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 1, mb: 0.5 }}
      data-testid={testId}
    >
      <Typography variant="caption" color="text.secondary" sx={SIDEBAR_LABEL_SX}>
        {label}
      </Typography>
      <Box
        sx={{
          ...SIDEBAR_VALUE_SX,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
        }}
      >
        {children}
      </Box>
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
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.5, mb: 0.5 }}>
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
    mail_queue_status?: string | null
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
  const contacts: PropertyContactSummary[] = commandCenterData.contacts ?? []
  const useContacts = contacts.length > 0

  const ownerEntries = ownerDisplayEntries(
    contacts,
    commandCenterData.owner_first_name,
    commandCenterData.owner_last_name,
    commandCenterData.owner_2_first_name,
    commandCenterData.owner_2_last_name,
    commandCenterData.organizations,
  )

  const phones: LeadPhone[] = useContacts
    ? []
    : data.phones?.length
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

  const emails: string[] = useContacts
    ? []
    : data.emails?.length
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
      data-testid="property-sidebar"
      sx={{
        ...ccCardSx,
        mb: 0,
        position: 'sticky',
        top: 80,
        maxHeight: 'calc(100vh - 100px)',
        overflowY: 'auto',
        display: { xs: 'none', sm: 'none', md: 'none', lg: 'block' },
        minWidth: 280,
        maxWidth: 320,
        flexShrink: 0,
      }}
    >
      <SidebarSection title="Contact Info">
        {ownerEntries.map((entry, idx) => (
          <SidebarRow
            key={`${entry.label}-${entry.name}`}
            label={entry.label}
            value={
              <>
                {entry.name}
                {entry.contact?.is_primary && isEntityContactName(entry.contact) ? (
                  <Chip
                    size="small"
                    label="LLC — resolve entity"
                    variant="outlined"
                    sx={{ ml: 0.75, height: 18, fontSize: '0.65rem' }}
                  />
                ) : null}
              </>
            }
            valueFontWeight={idx === 0 ? 600 : 500}
            testId={
              idx === 0
                ? 'sidebar-owner-name'
                : entry.label === 'Company'
                  ? 'sidebar-company-name'
                  : entry.label === 'Also listed'
                    ? 'sidebar-also-listed-name'
                    : entry.label === 'Owner 2'
                      ? 'sidebar-owner-2-name'
                      : undefined
            }
          />
        ))}
        {useContacts ? (
          contacts.map((contact) => {
            const phonesList = contact.phones ?? []
            const emailsList = contact.emails ?? []
            if (!phonesList.length && !emailsList.length) return null
            return (
              <Box key={`contact-methods-${contact.id}`} sx={{ mb: 0.5 }}>
                {phonesList.map((p) => (
                  <SidebarLabeledContent key={p.id ?? p.value} label="Phone">
                    <PhoneRow phone={p} />
                  </SidebarLabeledContent>
                ))}
                {emailsList.map((e) => (
                  <SidebarLabeledContent key={e.id} label="Email">
                    <CopyableEmail email={e.value} />
                  </SidebarLabeledContent>
                ))}
              </Box>
            )
          })
        ) : (
          <>
            {phones.map((p, i) => (
              <SidebarLabeledContent key={p.id ?? `${p.value}-${i}`} label="Phone">
                <PhoneRow phone={p} />
              </SidebarLabeledContent>
            ))}
            {emails.map((e, i) => (
              <SidebarLabeledContent key={i} label="Email">
                <CopyableEmail email={e} />
              </SidebarLabeledContent>
            ))}
          </>
        )}
        {data.socials && <SidebarRow label="Socials" value={data.socials} />}
      </SidebarSection>

      {commandCenterData.ownership_type && (
        <SidebarSection title="Owner">
          <SidebarRow label="Type" value={commandCenterData.ownership_type} />
        </SidebarSection>
      )}

      <SidebarSection title="Property">
        {(commandCenterData.property_street || commandCenterData.property_city) && (
          <SidebarRow
            label="Address"
            value={
              <>
                {commandCenterData.property_street}
                {(commandCenterData.property_city ||
                  commandCenterData.property_state ||
                  commandCenterData.property_zip) && (
                  <>
                    {commandCenterData.property_street ? '\n' : ''}
                    {[
                      commandCenterData.property_city,
                      commandCenterData.property_state,
                      commandCenterData.property_zip,
                    ]
                      .filter(Boolean)
                      .join(', ')}
                  </>
                )}
              </>
            }
            valueFontWeight={600}
            testId="sidebar-property-address"
          />
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
        <Box sx={{ mb: 0.5 }} data-testid="sidebar-most-recent-sale">
          <SidebarRow
            label="Most Recent Sale"
            value={commandCenterData.most_recent_sale_display ?? data.most_recent_sale}
          />
          {formatSaleDateFreshness(commandCenterData.sale_date_meta) && (
            <Typography
              variant="caption"
              color="text.disabled"
              sx={{ display: 'block', textAlign: 'right', pl: '108px' }}
            >
              {formatSaleDateFreshness(commandCenterData.sale_date_meta)}
            </Typography>
          )}
        </Box>
        <SidebarRow
          label="Deal Source"
          value={commandCenterData.deal_source}
          alwaysShow
          testId="sidebar-deal-source"
        />
        <SidebarLabeledContent label="Deal Description" testId="sidebar-deal-description">
          <Typography
            variant="caption"
            component="div"
            sx={{
              whiteSpace: 'pre-wrap',
              textAlign: 'right',
              color: commandCenterData.deal_description ? 'text.primary' : 'text.disabled',
            }}
          >
            {commandCenterData.deal_description || '—'}
          </Typography>
        </SidebarLabeledContent>
        {data.address_2 && <SidebarRow label="Address 2" value={data.address_2} />}
        {data.returned_addresses && (
          <SidebarRow label="Other Addresses" value={data.returned_addresses} />
        )}
      </SidebarSection>

      {(commandCenterData.mailing_address || commandCenterData.mailing_city) && (
        <SidebarSection title="Owner Mailing Address">
          <SidebarRow
            label="Mailing"
            value={
              <>
                {commandCenterData.mailing_address}
                {(commandCenterData.mailing_city ||
                  commandCenterData.mailing_state ||
                  commandCenterData.mailing_zip) && (
                  <>
                    {commandCenterData.mailing_address ? '\n' : ''}
                    {[
                      commandCenterData.mailing_city,
                      commandCenterData.mailing_state,
                      commandCenterData.mailing_zip,
                    ]
                      .filter(Boolean)
                      .join(', ')}
                  </>
                )}
              </>
            }
          />
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

      {(data.mailer_history != null || data.up_next_to_mail || data.mail_queue_status === 'queued') && (
        <SidebarSection title="Mailer History">
          {data.mail_queue_status === 'queued' && (
            <Chip label="In mail queue" size="small" color="primary" sx={{ mb: 0.5 }} />
          )}
          {Boolean(data.up_next_to_mail) && data.mail_queue_status !== 'queued' && (
            <Chip
              label="Up Next to Mail (legacy)"
              size="small"
              color="default"
              sx={{ mb: 0.5 }}
              title="Legacy flag — prefer mail_ready + mail queue membership"
            />
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
        <SidebarRow label="Import note" value={formatImportNote(commandCenterData)} />
        <SidebarRow label="Category" value={commandCenterData.lead_category} />
        <SidebarRow label="Import channel" value={data.data_source} />
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
