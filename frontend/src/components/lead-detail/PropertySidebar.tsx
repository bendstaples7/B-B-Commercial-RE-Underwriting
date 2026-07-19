import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Link,
  Paper,
  Snackbar,
  Tooltip,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import EmailIcon from '@mui/icons-material/Email'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useQueryClient } from '@tanstack/react-query'
import type {
  CommandCenterPayload,
  LeadPhone,
  PropertyContactSummary,
  RelatedPropertySummary,
} from '@/types'
import { RelatedPropertyRow } from '@/components/RelatedPropertyRow'
import {
  formatSaleDateFreshness,
  isSaleDateVerifiedWithinDays,
} from '@/utils/saleDateFreshness'
import { formatCookCountyPin } from '@/utils/cookCountyPin'
import { commandCenterService, leadTaskService } from '@/services/api'
import { propertyMatchService } from '@/services/propertyMatchApi'
import {
  isEntityContactName,
  ownerDisplayEntries,
} from '@/utils/propertyContacts'
import { formatImportNote } from './leadDetailFormatters'
import { hasNonBlankPhones, PhoneList } from '@/components/PhoneRow'
import { ccCardSx } from '@/components/lead-detail/commandCenterChrome'
import { PriorOwnerStaleOverlay } from '@/components/lead-detail/PriorOwnerStaleCallout'

/** Poll delays after queued sale-date verify (overridable in tests). */
export let saleVerifyPollDelaysMs = [2000, 3000, 5000, 8000, 13000]

const SidebarStackedContext = createContext(false)

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
  emptyLabel = '—',
  testId,
  valueFontWeight,
}: {
  label: string
  value: ReactNode
  alwaysShow?: boolean
  /** Shown when value is empty and alwaysShow is true (default em dash). */
  emptyLabel?: string
  testId?: string
  valueFontWeight?: number
}) {
  const stacked = useContext(SidebarStackedContext)
  const isEmpty = value == null || value === ''
  if (isEmpty && !alwaysShow) return null
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: stacked ? 'column' : 'row',
        alignItems: stacked ? 'stretch' : 'flex-start',
        justifyContent: 'space-between',
        gap: stacked ? 0.25 : 1,
        mb: stacked ? 1 : 0.5,
      }}
      data-testid={testId}
    >
      <Typography
        variant="caption"
        color="text.secondary"
        sx={stacked ? { width: 'auto', textAlign: 'left' } : SIDEBAR_LABEL_SX}
      >
        {label}
      </Typography>
      <Typography
        variant="caption"
        fontWeight={valueFontWeight}
        sx={{
          ...(stacked
            ? { flex: 1, minWidth: 0, textAlign: 'left', wordBreak: 'break-word' }
            : SIDEBAR_VALUE_SX),
          whiteSpace: 'pre-line',
          color: isEmpty ? 'text.disabled' : 'text.primary',
        }}
      >
        {isEmpty ? emptyLabel : value}
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
  const stacked = useContext(SidebarStackedContext)
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: stacked ? 'column' : 'row',
        alignItems: stacked ? 'stretch' : 'flex-start',
        justifyContent: 'space-between',
        gap: stacked ? 0.35 : 1,
        mb: 0.75,
      }}
      data-testid={testId}
    >
      <Typography
        variant="caption"
        color="text.secondary"
        sx={stacked ? { width: 'auto', textAlign: 'left' } : { ...SIDEBAR_LABEL_SX, pt: 0.15 }}
      >
        {label}
      </Typography>
      <Box
        sx={{
          ...(stacked
            ? { flex: 1, minWidth: 0, textAlign: 'left' }
            : SIDEBAR_VALUE_SX),
          display: 'flex',
          flexDirection: 'column',
          alignItems: stacked ? 'stretch' : 'flex-end',
          gap: 0.35,
        }}
      >
        {children}
      </Box>
    </Box>
  )
}

function CopyableEmail({
  email,
  actionable = true,
}: {
  email: string
  actionable?: boolean
}) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(email)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 0.5, minWidth: 0 }}>
      <EmailIcon sx={{ fontSize: 13, color: 'text.secondary', flexShrink: 0 }} />
      {actionable ? (
        <Link href={`mailto:${email}`} variant="caption" underline="hover" noWrap>
          {email}
        </Link>
      ) : (
        <Typography variant="caption" noWrap>
          {email}
        </Typography>
      )}
      {actionable && (
        <Tooltip title={copied ? 'Copied!' : 'Copy'}>
          <IconButton size="small" onClick={handleCopy} sx={{ p: 0.25, flexShrink: 0 }}>
            <ContentCopyIcon sx={{ fontSize: 11 }} />
          </IconButton>
        </Tooltip>
      )}
    </Box>
  )
}

function CopyablePin({
  pin,
  valueTestId,
}: {
  pin: string
  valueTestId?: string
}) {
  const [copied, setCopied] = useState(false)
  const displayPin = formatCookCountyPin(pin)
  if (!displayPin) return null
  const handleCopy = () => {
    void navigator.clipboard.writeText(displayPin)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-end',
        gap: 0.5,
        minWidth: 0,
      }}
    >
      <Typography
        variant="caption"
        component="span"
        noWrap
        data-testid={valueTestId}
      >
        {displayPin}
      </Typography>
      <Tooltip title={copied ? 'Copied!' : 'Copy'}>
        <IconButton
          size="small"
          onClick={handleCopy}
          aria-label="Copy PIN"
          data-testid="sidebar-pin-copy"
          sx={{ p: 0.25, flexShrink: 0 }}
        >
          <ContentCopyIcon sx={{ fontSize: 11 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

export interface PropertySidebarProps {
  commandCenterData: CommandCenterPayload
  /** `sidebar` sticky lg+ panel; `inline` accordion for viewports below lg. */
  variant?: 'sidebar' | 'inline'
  /** Jump to Info tab sale-history table. */
  onViewSaleHistory?: () => void
}

export function PropertySidebar({
  commandCenterData,
  variant = 'sidebar',
  onViewSaleHistory,
}: PropertySidebarProps) {
  const queryClient = useQueryClient()
  const [saleVerifyPending, setSaleVerifyPending] = useState(false)
  const [saleVerifyMessage, setSaleVerifyMessage] = useState<string | null>(null)
  const [pinLookupPending, setPinLookupPending] = useState(false)
  const [pinCandidate, setPinCandidate] = useState<string | null>(null)
  const [pinApplyPending, setPinApplyPending] = useState(false)
  const [sidebarSnack, setSidebarSnack] = useState<string | null>(null)
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
    ? contacts.flatMap((c) => c.phones ?? [])
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
    ? contacts.flatMap((c) => (c.emails ?? []).map((e) => e.value).filter(Boolean))
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

  const mailingStreet = commandCenterData.mailing_address?.trim() || ''
  const mailingCityLine = [
    commandCenterData.mailing_city,
    commandCenterData.mailing_state,
    commandCenterData.mailing_zip,
  ]
    .map((part) => part?.trim() || '')
    .filter(Boolean)
    .join(', ')
  const hasOwnerMailing = Boolean(mailingStreet || mailingCityLine)
  const contactMethod = commandCenterData.recommended_action?.recommended_contact_method
  const actionValue = commandCenterData.recommended_action?.value
  const mailRecommended =
    contactMethod === 'direct_mail' || actionValue === 'mail_ready'
  const saleDateDisplay =
    commandCenterData.most_recent_sale_display ?? data.most_recent_sale ?? null
  const hasDisplayedSale = Boolean(
    saleDateDisplay && String(saleDateDisplay).trim() && String(saleDateDisplay).trim() !== 'None',
  )
  const saleFreshness = formatSaleDateFreshness(commandCenterData.sale_date_meta, {
    hasDisplayedSale,
  })
  const saleRecentlyVerified = isSaleDateVerifiedWithinDays(
    commandCenterData.sale_date_meta,
    undefined,
    undefined,
    { hasDisplayedSale },
  )
  const isCookCountyEligible = Boolean(commandCenterData.is_cook_county_eligible)
  const canReverifySaleDate = Boolean(
    isCookCountyEligible
    && commandCenterData.sale_date_meta?.last_checked_at
    && commandCenterData.sale_date_meta?.status !== 'failed',
  )
  const canVerifySaleDate = Boolean(
    isCookCountyEligible
    && !canReverifySaleDate
    && (
      !commandCenterData.sale_date_meta?.last_checked_at
      || commandCenterData.sale_date_meta?.status === 'failed'
    ),
  )
  const pinMissing = !commandCenterData.county_assessor_pin?.trim()
  const contactsLikelyPriorOwner = Boolean(commandCenterData.contacts_likely_prior_owner)

  useEffect(() => {
    setSaleVerifyPending(false)
    setSaleVerifyMessage(null)
    setPinLookupPending(false)
    setPinCandidate(null)
    setPinApplyPending(false)
  }, [commandCenterData.id])

  const pollQueuedSaleVerification = async (
    leadId: number,
    previousCheckedAt: string | null | undefined,
  ) => {
    const delaysMs = saleVerifyPollDelaysMs
    for (const delayMs of delaysMs) {
      await new Promise((resolve) => {
        window.setTimeout(resolve, delayMs)
      })
      try {
        const fresh = await commandCenterService.getCommandCenter(leadId)
        const checkedAt = fresh.sale_date_meta?.last_checked_at
        // Wait for a new check stamp — retries keep the prior failed timestamp.
        if (checkedAt && checkedAt !== previousCheckedAt) {
          queryClient.setQueryData(['commandCenter', leadId], fresh)
          return 'checked' as const
        }
      } catch {
        // Keep polling until delays are exhausted.
      }
    }
    await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    return 'timed_out' as const
  }

  const handleVerifySaleDate = async () => {
    setSaleVerifyPending(true)
    setSaleVerifyMessage(null)
    const previousCheckedAt = commandCenterData.sale_date_meta?.last_checked_at
    try {
      const result = await commandCenterService.verifySaleDate(commandCenterData.id)
      if (result.queued) {
        const pollResult = await pollQueuedSaleVerification(
          commandCenterData.id,
          previousCheckedAt,
        )
        if (pollResult === 'timed_out') {
          setSaleVerifyMessage('Verification timed out. Refresh to check status.')
        }
        return
      }
      if (result.summary?.skipped) {
        const reason = result.summary.skip_reason || 'unknown'
        setSaleVerifyMessage(
          reason === 'not_eligible'
            ? 'Not eligible for Cook County enrichment.'
            : `Verification skipped (${reason}).`,
        )
      } else if (
        result.message
        && result.message !== 'Verification queued.'
        && !result.ran_sync
      ) {
        setSaleVerifyMessage(result.message)
      }
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', commandCenterData.id] })
    } catch (error) {
      setSaleVerifyMessage(error instanceof Error ? error.message : 'Verification failed.')
    } finally {
      setSaleVerifyPending(false)
    }
  }

  const handleLookUpPin = async () => {
    setPinLookupPending(true)
    setPinCandidate(null)
    try {
      const preview = await propertyMatchService.preview(commandCenterData.id)
      const pin = formatCookCountyPin(
        preview.pin || preview.recommended_address?.county_assessor_pin || '',
      )
      if (preview.found && pin) {
        setPinCandidate(pin)
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', commandCenterData.id] })
        return
      }
      if (preview.reason === 'incomplete_address' || preview.address_complete === false) {
        setSidebarSnack(
          preview.message
          || 'Add city, state, and ZIP — then look up PIN',
        )
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', commandCenterData.id] })
        return
      }
      await leadTaskService.createTask(commandCenterData.id, {
        title: 'Research missing PIN',
        task_type: 'research_missing_pin',
      })
      setSidebarSnack('No PIN found — research task created')
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', commandCenterData.id] })
    } catch (error) {
      setSidebarSnack(error instanceof Error ? error.message : 'PIN lookup failed')
    } finally {
      setPinLookupPending(false)
    }
  }

  const handleApplyPinCandidate = async () => {
    if (!pinCandidate) return
    setPinApplyPending(true)
    try {
      const result = await propertyMatchService.approve(commandCenterData.id, {
        pin: pinCandidate,
      })
      setPinCandidate(null)
      const appliedPin = formatCookCountyPin(
        (result as { county_assessor_pin?: string | null })?.county_assessor_pin,
      )
      setSidebarSnack(
        appliedPin
          ? `PIN applied: ${appliedPin}`
          : 'PIN applied from property match',
      )
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', commandCenterData.id] })
    } catch (error) {
      setSidebarSnack(error instanceof Error ? error.message : 'Could not apply PIN')
    } finally {
      setPinApplyPending(false)
    }
  }

  const stacked = variant === 'inline'
  const contactInfoBody = (
    <>
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
      {hasNonBlankPhones(phones) && (
        <SidebarLabeledContent label="Phone" testId="sidebar-phones">
          <PhoneList
            phones={phones}
            dense={!stacked}
            actionable={!contactsLikelyPriorOwner}
          />
        </SidebarLabeledContent>
      )}
      {emails.length > 0 && (
        <SidebarLabeledContent label="Email" testId="sidebar-emails">
          {emails.map((e, i) => (
            <CopyableEmail
              key={`${e}-${i}`}
              email={e}
              actionable={!contactsLikelyPriorOwner}
            />
          ))}
        </SidebarLabeledContent>
      )}
      <SidebarRow
        label="Mailing"
        alwaysShow
        emptyLabel="Not on file"
        testId="sidebar-owner-mailing"
        value={
          hasOwnerMailing ? (
            <>
              {mailingStreet}
              {mailingCityLine && (
                <>
                  {mailingStreet ? '\n' : ''}
                  {mailingCityLine}
                </>
              )}
            </>
          ) : null
        }
      />
      {data.socials && <SidebarRow label="Socials" value={data.socials} />}
    </>
  )
  const sections = (
    <SidebarStackedContext.Provider value={stacked}>
      <SidebarSection title="Contact Info">
        {contactsLikelyPriorOwner ? (
          <PriorOwnerStaleOverlay
            testId="sidebar-contact-info"
            bannerTestId="sidebar-likely-prior-owner"
          >
            {contactInfoBody}
          </PriorOwnerStaleOverlay>
        ) : (
          <Box data-testid="sidebar-contact-info">{contactInfoBody}</Box>
        )}
        {!hasOwnerMailing && mailRecommended && (
          <Typography
            variant="caption"
            color="warning.main"
            data-testid="owner-mailing-missing-for-mail"
            sx={{ display: 'block', mt: 0.5 }}
          >
            No mailing address on file for this lead. Skip trace or add an owner mailing
            address before sending mail.
          </Typography>
        )}
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
        <SidebarRow
          label="PIN"
          value={
            pinMissing ? (
              <Box
                sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-end',
                  gap: 0.5,
                }}
                data-testid="sidebar-pin-lookup"
              >
                <Typography variant="caption" color="text.disabled" component="span">
                  None
                </Typography>
                {pinCandidate ? (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    <CopyablePin pin={pinCandidate} valueTestId="sidebar-pin-candidate" />
                    <Button
                      size="small"
                      variant="text"
                      onClick={handleApplyPinCandidate}
                      disabled={pinApplyPending}
                      data-testid="sidebar-apply-pin"
                      startIcon={
                        pinApplyPending ? (
                          <CircularProgress size={12} color="inherit" aria-hidden />
                        ) : undefined
                      }
                      sx={{ minWidth: 0, px: 0.5, py: 0, fontSize: '0.7rem' }}
                    >
                      {pinApplyPending ? 'Applying…' : 'Apply'}
                    </Button>
                  </Box>
                ) : (
                  <Button
                    size="small"
                    variant="text"
                    onClick={handleLookUpPin}
                    disabled={pinLookupPending}
                    data-testid="sidebar-look-up-pin"
                    startIcon={
                      pinLookupPending ? (
                        <CircularProgress size={12} color="inherit" aria-hidden />
                      ) : undefined
                    }
                    sx={{ minWidth: 0, px: 0.5, py: 0, fontSize: '0.7rem' }}
                  >
                    {pinLookupPending ? 'Looking up…' : 'Look up PIN'}
                  </Button>
                )}
              </Box>
            ) : (
              <CopyablePin pin={commandCenterData.county_assessor_pin || ''} />
            )
          }
          alwaysShow
          emptyLabel="None"
          testId="sidebar-county-assessor-pin"
        />
        <SidebarRow
          label="Tax Bill"
          value={
            data.tax_bill_2021 != null ? `$${Number(data.tax_bill_2021).toLocaleString()}` : null
          }
        />
        <Box data-testid="sidebar-most-recent-sale">
          <SidebarLabeledContent label="Most Recent Sale">
            {(() => {
              const dateDisplay = saleDateDisplay
              const price = commandCenterData.most_recent_sale_price
              const text =
                dateDisplay
                  ? price != null
                    ? `${dateDisplay} · $${Number(price).toLocaleString()}`
                    : dateDisplay
                  : null
              const displayText = text ?? 'None'
              return (
                <Box
                  sx={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    gap: 0.5,
                    textAlign: 'right',
                  }}
                >
                  <Typography
                    variant="caption"
                    component="span"
                    sx={{
                      color: text ? 'text.primary' : 'text.disabled',
                      wordBreak: 'break-word',
                    }}
                  >
                    {displayText}
                  </Typography>
                  {saleVerifyPending ? (
                    <CircularProgress
                      size={12}
                      thickness={5}
                      aria-label="Verifying sale date"
                      data-testid="sidebar-sale-verify-spinner"
                    />
                  ) : saleRecentlyVerified ? (
                    <Tooltip title="Verified within the last month">
                      <CheckCircleIcon
                        sx={{ fontSize: 14, color: 'success.main' }}
                        aria-label="Verified within the last month"
                        data-testid="sidebar-sale-verified-check"
                      />
                    </Tooltip>
                  ) : null}
                </Box>
              )
            })()}
          </SidebarLabeledContent>
          {(saleFreshness || canReverifySaleDate || onViewSaleHistory) ? (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: 0.75,
                flexWrap: 'nowrap',
                mb: 0.5,
                mt: -0.35,
              }}
              data-testid="sidebar-sale-meta-row"
            >
              {saleFreshness ? (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  component="span"
                  sx={{ whiteSpace: 'nowrap', flexShrink: 0 }}
                  data-testid="sidebar-sale-last-checked"
                >
                  {saleFreshness}
                </Typography>
              ) : null}
              {canReverifySaleDate && !saleVerifyPending ? (
                <Tooltip title="Check sale date again">
                  <IconButton
                    size="small"
                    onClick={handleVerifySaleDate}
                    aria-label="Re-verify sale date"
                    data-testid="sidebar-reverify-sale-date"
                    sx={{ p: 0.25, flexShrink: 0 }}
                  >
                    <RefreshIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                </Tooltip>
              ) : null}
              {onViewSaleHistory ? (
                <Box
                  component="button"
                  type="button"
                  onClick={onViewSaleHistory}
                  data-testid="sidebar-sale-history-link"
                  aria-label="View sale history in Info tab"
                  sx={{
                    appearance: 'none',
                    border: 0,
                    background: 'none',
                    p: 0,
                    m: 0,
                    cursor: 'pointer',
                    font: 'inherit',
                    color: 'primary.main',
                    textDecoration: 'underline',
                    textUnderlineOffset: '2px',
                    fontSize: '0.75rem',
                    lineHeight: 1.66,
                    flexShrink: 0,
                    whiteSpace: 'nowrap',
                  }}
                >
                  Sale history
                </Box>
              ) : null}
            </Box>
          ) : null}
          {(canVerifySaleDate || saleVerifyMessage) ? (
            <Box sx={{ textAlign: 'right', mt: -0.25, mb: 0.5 }}>
              <Typography
                variant="caption"
                color="text.disabled"
                component="span"
                sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap', justifyContent: 'flex-end' }}
              >
                {canVerifySaleDate && !saleVerifyPending && !commandCenterData.sale_date_meta?.last_checked_at ? (
                  <Box component="span">Sale date not verified yet</Box>
                ) : null}
                {canVerifySaleDate && !saleVerifyPending ? (
                  <Box
                    component="button"
                    type="button"
                    onClick={handleVerifySaleDate}
                    data-testid="sidebar-verify-sale-date"
                    aria-label="Verify sale date"
                    sx={{
                      appearance: 'none',
                      border: 0,
                      background: 'none',
                      p: 0,
                      m: 0,
                      cursor: 'pointer',
                      font: 'inherit',
                      color: 'primary.main',
                      textDecoration: 'underline',
                      textUnderlineOffset: '2px',
                    }}
                  >
                    Verify
                  </Box>
                ) : null}
              </Typography>
              {saleVerifyMessage ? (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block' }}
                >
                  {saleVerifyMessage}
                </Typography>
              ) : null}
            </Box>
          ) : null}
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

      {(commandCenterData.related_properties?.length ?? 0) > 0 && (
        <SidebarSection title="Other properties">
          <Box
            data-testid="sidebar-related-properties"
            sx={{ display: 'flex', flexDirection: 'column', gap: 0.75 }}
          >
            {(commandCenterData.related_properties as RelatedPropertySummary[]).map((prop) => (
              <RelatedPropertyRow
                key={prop.id}
                prop={prop}
                testIdPrefix="sidebar-related-property"
                fontSize="0.8125rem"
                fontWeight={500}
              />
            ))}
          </Box>
        </SidebarSection>
      )}

      {(data.needs_skip_trace != null || data.skip_tracer || data.date_skip_traced) && (
        <SidebarSection title="Skip Trace">
          <SidebarRow
            label="Needed (phone/email)"
            value={data.needs_skip_trace != null ? (data.needs_skip_trace ? 'Yes' : 'No') : null}
          />
          <Typography
            variant="caption"
            color="text.secondary"
            data-testid="skip-trace-needed-caption"
            sx={{ display: 'block', mb: 0.5 }}
          >
            Based on phone/email at ingest — not owner mailing address.
          </Typography>
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

      <SidebarSection title="Work Queues">
        {(commandCenterData.work_queues?.length ?? 0) > 0 ? (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }} data-testid="work-queues">
            {commandCenterData.work_queues!.map((q) => (
              <Chip
                key={q.key}
                component={RouterLink}
                to={q.path}
                clickable
                size="small"
                label={q.label}
                data-testid={`work-queue-${q.key}`}
              />
            ))}
          </Box>
        ) : (
          <Typography variant="caption" color="text.secondary" data-testid="work-queues-empty">
            Not in an active work queue.
          </Typography>
        )}
      </SidebarSection>

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
        <Typography
          variant="caption"
          color="text.secondary"
          display="block"
          sx={{ mb: 1 }}
          data-testid="data-quality-caption"
        >
          Property identity + contact reachability (not activity history).
        </Typography>
        <SidebarRow
          label="Completeness"
          value={
            commandCenterData.data_completeness_score != null
              ? `${Math.round(commandCenterData.data_completeness_score)}%`
              : null
          }
        />
        {commandCenterData.data_quality_breakdown && (
          <>
            <SidebarRow
              label="Property fields"
              value={`${Math.round(commandCenterData.data_quality_breakdown.property)} / 50`}
            />
            <SidebarRow
              label="Contact reach"
              value={`${Math.round(commandCenterData.data_quality_breakdown.contact)} / 50`}
            />
            <SidebarRow
              label="Best phone"
              value={
                commandCenterData.data_quality_breakdown.best_phone_confidence != null
                  ? `${commandCenterData.data_quality_breakdown.best_phone_confidence}%`
                  : 'None'
              }
            />
            <SidebarRow
              label="Email"
              value={commandCenterData.data_quality_breakdown.has_email ? 'Present' : 'Missing'}
            />
            {(commandCenterData.data_quality_breakdown.missing?.length ?? 0) > 0 && (
              <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }} data-testid="data-quality-missing">
                {commandCenterData.data_quality_breakdown.missing.slice(0, 6).map((field) => (
                  <Chip key={field} size="small" variant="outlined" label={field.replace(/_/g, ' ')} />
                ))}
              </Box>
            )}
          </>
        )}
      </SidebarSection>
    </SidebarStackedContext.Provider>
  )

  const snackbar = (
    <Snackbar
      open={Boolean(sidebarSnack)}
      autoHideDuration={4000}
      onClose={() => setSidebarSnack(null)}
      message={sidebarSnack ?? ''}
      data-testid="sidebar-snackbar"
    />
  )

  if (variant === 'inline') {
    const ownerSummary = ownerEntries[0]?.name
    return (
      <>
        <Accordion
          defaultExpanded={false}
          disableGutters
          data-testid="property-sidebar-mobile"
          sx={{
            ...ccCardSx,
            mb: 2,
            display: { xs: 'block', lg: 'none' },
            '&:before': { display: 'none' },
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon />}
            aria-controls="property-contacts-content"
            id="property-contacts-header"
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography fontWeight={600}>Property & contacts</Typography>
              {ownerSummary ? (
                <Typography variant="caption" color="text.secondary" noWrap display="block">
                  {ownerSummary}
                </Typography>
              ) : null}
            </Box>
          </AccordionSummary>
          <AccordionDetails id="property-contacts-content" sx={{ pt: 0 }}>{sections}</AccordionDetails>
        </Accordion>
        {snackbar}
      </>
    )
  }

  return (
    <>
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
          minWidth: 340,
          maxWidth: 400,
          flexShrink: 0,
        }}
      >
        {sections}
      </Paper>
      {snackbar}
    </>
  )
}
