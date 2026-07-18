import { useState, useEffect, useMemo, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  IconButton,
  Paper,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import HomeWorkIcon from '@mui/icons-material/HomeWork'
import ApartmentIcon from '@mui/icons-material/Apartment'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import { multifamilyService } from '@/services/api'
import { leadService } from '@/services/leadApi'
import { formatPhoneNumber } from '@/utils/phone'
import {
  formatDate,
  formatDateTime,
  getEnrichmentStatusColor,
  getOutreachStatusColor,
  outreachStatusLabel,
} from '@/utils/formatters'
import type { CommandCenterPayload, PropertyDetail, PropertyScoreResponse } from '@/types'
import { ContactsSection } from '@/components/ContactsSection'
import { RecalculateButton } from '@/components/RecalculateButton'
import { ScoreBreakdownCard } from '@/components/ScoreBreakdownCard'
import { ScoreHistoryTimeline } from '@/components/ScoreHistoryTimeline'
import { ScoreLegend } from '@/components/ScoreLegend'
import { hasNonBlankPhones, PhoneList } from '@/components/PhoneRow'
import { MotivationSignalsPanel } from '@/components/lead-detail/MotivationSignalsPanel'
import { formatSaleDateFreshness, isSaleDateVerifiedWithinDays } from '@/utils/saleDateFreshness'
import { formatCookCountyPin } from '@/utils/cookCountyPin'
import { contactDisplayName } from '@/utils/propertyContacts'
import { formatImportNote } from './leadDetailFormatters'
import { ccSubsectionTitleSx } from '@/components/lead-detail/commandCenterChrome'
import { PriorOwnerStaleBanner } from '@/components/lead-detail/PriorOwnerStaleCallout'

const DEFAULT_TAB_INDEX = 0

const TAB_PARAM_TO_INDEX: Record<string, number> = {
  info: 0,
  score: 1,
  enrichment: 2,
  marketing: 3,
  analysis: 4,
  contacts: 5,
}

export function tabParamToIndex(param: string | null | undefined): number {
  if (!param) return DEFAULT_TAB_INDEX
  const index = TAB_PARAM_TO_INDEX[param.toLowerCase()]
  return index ?? DEFAULT_TAB_INDEX
}

function EnrichmentDetailsCell({
  status,
  retrievedData,
  errorReason,
}: {
  status: string
  retrievedData?: Record<string, unknown> | null
  errorReason?: string | null
}) {
  const [open, setOpen] = useState(false)
  const hasData = status === 'success' && retrievedData && Object.keys(retrievedData).length > 0

  if (!hasData) {
    return <>{errorReason || '—'}</>
  }

  const fieldCount = Object.keys(retrievedData).length
  const preview = useMemo(
    () => (open ? JSON.stringify(retrievedData, null, 2) : ''),
    [open, retrievedData],
  )

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Typography variant="body2" component="span">
          {fieldCount} field(s) enriched
        </Typography>
        <IconButton
          size="small"
          aria-expanded={open}
          aria-label={open ? 'Hide enrichment JSON' : 'Show enrichment JSON'}
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
      </Box>
      <Collapse in={open}>
        <Box
          component="pre"
          sx={{
            mt: 1,
            p: 1,
            maxHeight: 240,
            overflow: 'auto',
            fontSize: '0.75rem',
            bgcolor: 'action.hover',
            borderRadius: 1,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {preview}
        </Box>
      </Collapse>
    </Box>
  )
}

export interface LeadDetailTabPanelProps {
  leadId: number
  leadData: PropertyDetail
  commandCenterData: CommandCenterPayload
  scoreData?: PropertyScoreResponse
  scoreLoading?: boolean
}

export function LeadDetailTabPanel({
  leadId,
  leadData,
  commandCenterData,
  scoreData,
  scoreLoading,
}: LeadDetailTabPanelProps) {
  const [searchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const [activeTab, setActiveTab] = useState(() => tabParamToIndex(tabParam))

  useEffect(() => {
    if (activeTab !== 0) return
    if (typeof window === 'undefined') return
    if (window.location.hash !== '#info-sale-history') return
    const timer = window.setTimeout(() => {
      document.getElementById('info-sale-history')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    }, 80)
    return () => window.clearTimeout(timer)
  }, [activeTab, commandCenterData.id, commandCenterData.sale_history])

  useEffect(() => {
    setActiveTab(tabParamToIndex(tabParam))
  }, [tabParam])

  const navigate = useNavigate()
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  const handleStartSingleFamily = async () => {
    setAnalysisLoading(true)
    setAnalysisError(null)
    try {
      const result = await leadService.analyzeLead(leadId)
      navigate(`/analysis/${result.session_id}`)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to start analysis.'
      setAnalysisError(message)
    } finally {
      setAnalysisLoading(false)
    }
  }

  const handleStartMultifamily = async () => {
    setAnalysisLoading(true)
    setAnalysisError(null)
    try {
      const deal = await multifamilyService.createDeal({
        property_address: leadData.property_street,
        unit_count: leadData.units ?? 5,
        purchase_price: 0,
        close_date: new Date().toISOString().split('T')[0],
      })
      await multifamilyService.linkDealToLead(deal.id, leadData.id)
      navigate(`/multifamily/deals/${deal.id}`)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to start multifamily analysis.'
      setAnalysisError(message)
    } finally {
      setAnalysisLoading(false)
    }
  }

  const fieldGroup = (title: string, fields: [string, ReactNode][], testId?: string) => (
    <Box sx={{ mb: 3 }} data-testid={testId}>
      <Typography sx={ccSubsectionTitleSx}>
        {title}
      </Typography>
      <TableContainer>
        <Table size="small" aria-label={`${title} fields`}>
          <TableBody>
            {fields.map(([label, value]) => (
              <TableRow key={label}>
                <TableCell sx={{ width: '40%', color: 'text.secondary' }}>{label}</TableCell>
                <TableCell>{value ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  )

  const session = leadData.analysis_session
  const units = leadData.units
  const showMultifamily = units !== null && units >= 5
  const showSingleFamily = units === null || units < 5
  const showBoth = units === null
  const infoContacts =
    (commandCenterData.contacts?.length ? commandCenterData.contacts : null) ??
    (leadData.contacts?.length ? leadData.contacts : null)
  const contactsLikelyPriorOwner = Boolean(commandCenterData.contacts_likely_prior_owner)
  const staleSince = commandCenterData.contacts_stale_since ?? null
  const pastOwners = (commandCenterData.past_owners ?? []).filter((snap) => {
    // When live contacts are already labeled Past owner, hide the lazy
    // recent_sale snapshot for the same sale so Info does not duplicate.
    if (
      contactsLikelyPriorOwner
      && snap.reason === 'recent_sale'
      && staleSince
      && snap.sale_date === staleSince
    ) {
      return false
    }
    return true
  })
  const mailingFields: [string, ReactNode][] = [
    ['Mailing Address', leadData.mailing_address],
    ['City', leadData.mailing_city],
    ['State', leadData.mailing_state],
    ['Zip Code', leadData.mailing_zip],
  ]

  return (
    <Box data-testid="tab-panel">
      <Tabs
        value={activeTab}
        onChange={(_, newValue) => setActiveTab(newValue)}
        aria-label="Lead detail tabs"
        variant="scrollable"
        scrollButtons="auto"
      >
        <Tab label="Info" />
        <Tab label="Score" />
        <Tab label="Enrichment" />
        <Tab label="Marketing" />
        <Tab label="Analysis" />
        <Tab label="Contacts" />
      </Tabs>
      <Divider />

      {activeTab === 0 && (
        <Box sx={{ p: 2 }}>
          {contactsLikelyPriorOwner && (
            <PriorOwnerStaleBanner
              testId="info-likely-prior-owner-banner"
              staleSince={staleSince}
            />
          )}
          {infoContacts ? (
            <>
              {infoContacts.map((contact, idx) => {
                const name = contactDisplayName(contact)
                const emailRows = (contact.emails ?? []).map((e, i) => [
                  `Email${(contact.emails?.length ?? 0) > 1 ? ` ${i + 1}` : ''}`,
                  e.value,
                ] as [string, ReactNode])
                const roleLabel =
                  contact.role === 'former_owner'
                    ? 'Past owner'
                    : contact.role && contact.role !== 'owner'
                      ? contact.role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
                      : contactsLikelyPriorOwner
                        ? 'Past owner'
                        : 'Owner'
                const title = `${roleLabel} ${idx + 1}${contact.is_primary ? ' (Primary)' : ''}`
                return (
                  <Box key={contact.id}>
                    {fieldGroup(
                      title,
                      [
                        ['Name', name || null],
                        ...(contact.phones && hasNonBlankPhones(contact.phones)
                          ? [[
                              'Phone',
                              <PhoneList
                                key={`phones-${contact.id}`}
                                phones={contact.phones}
                                showLabel
                                dense={false}
                              />,
                            ] as [string, ReactNode]]
                          : []),
                        ...emailRows,
                        // Lead-level mailing attaches to the primary / first contact block
                        ...(idx === 0 ? mailingFields : []),
                      ],
                      idx === 0
                        ? (contactsLikelyPriorOwner
                          ? 'info-past-owner-contact'
                          : 'info-owner-contact')
                        : undefined,
                    )}
                  </Box>
                )
              })}
              {fieldGroup('Ownership', [
                ['Ownership Type', leadData.ownership_type],
              ])}
            </>
          ) : (
            <>
              {fieldGroup(
                contactsLikelyPriorOwner ? 'Past owner' : 'Owner',
                [
                  ['First Name', leadData.owner_first_name],
                  ['Last Name', leadData.owner_last_name],
                  ['Owner 2', [leadData.owner_2_first_name, leadData.owner_2_last_name].filter(Boolean).join(' ') || null],
                  ['Ownership Type', leadData.ownership_type],
                ],
                contactsLikelyPriorOwner ? 'info-past-owner-contact' : 'info-owner-contact',
              )}
              {fieldGroup(
                contactsLikelyPriorOwner ? 'Past owner contact' : 'Contact Information',
                [
                  ['Phone 1', leadData.phone_1 ? formatPhoneNumber(leadData.phone_1) : null],
                  ['Phone 2', leadData.phone_2 ? formatPhoneNumber(leadData.phone_2) : null],
                  ['Phone 3', leadData.phone_3 ? formatPhoneNumber(leadData.phone_3) : null],
                  ['Email 1', leadData.email_1],
                  ['Email 2', leadData.email_2],
                  ...mailingFields,
                ],
              )}
            </>
          )}
          {fieldGroup('Property Details', [
            ['Street', leadData.property_street],
            ['City', leadData.property_city],
            ['State', leadData.property_state],
            ['Zip Code', leadData.property_zip],
            ['Property Type', leadData.property_type],
            ['Bedrooms', leadData.bedrooms],
            ['Bathrooms', leadData.bathrooms],
            ['Square Footage', leadData.square_footage?.toLocaleString()],
            ['Lot Size', leadData.lot_size?.toLocaleString()],
            ['Year Built', leadData.year_built],
            ['Units', leadData.units],
            ['Units Allowed', leadData.units_allowed],
            ['Zoning', leadData.zoning],
            [
              'County Assessor PIN',
              formatCookCountyPin(leadData.county_assessor_pin) || 'None',
            ],
            ['Tax Bill 2021', leadData.tax_bill_2021 != null ? `$${leadData.tax_bill_2021.toLocaleString()}` : null],
            [
              'Most Recent Sale',
              (() => {
                const saleText =
                  (commandCenterData.most_recent_sale_display ?? leadData.most_recent_sale) ||
                  'None'
                const hasDisplayedSale = saleText !== 'None' && Boolean(String(saleText).trim())
                const freshness = formatSaleDateFreshness(commandCenterData.sale_date_meta, {
                  hasDisplayedSale,
                })
                const verified =
                  hasDisplayedSale
                  && isSaleDateVerifiedWithinDays(
                    commandCenterData.sale_date_meta,
                    undefined,
                    undefined,
                    { hasDisplayedSale },
                  )
                return (
                  <Box
                    component="span"
                    sx={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 0.75,
                      flexWrap: 'wrap',
                    }}
                    data-testid="info-most-recent-sale-value"
                  >
                    <Box
                      component="span"
                      sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
                    >
                      {saleText}
                      {verified ? (
                        <Tooltip title="Verified within the last month">
                          <CheckCircleIcon
                            sx={{ fontSize: 14, color: 'success.main' }}
                            aria-label="Verified within the last month"
                            data-testid="info-sale-verified-check"
                          />
                        </Tooltip>
                      ) : null}
                    </Box>
                    {freshness ? (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        component="span"
                        noWrap
                        sx={{ whiteSpace: 'nowrap' }}
                        data-testid="info-most-recent-sale-freshness"
                      >
                        {freshness}
                      </Typography>
                    ) : null}
                  </Box>
                )
              })(),
            ],
          ])}
          <Box
            id="info-sale-history"
            sx={{ mb: 3, scrollMarginTop: 96 }}
            data-testid="info-sale-history"
          >
            <Typography sx={ccSubsectionTitleSx}>Sale history</Typography>
            {(() => {
              const history =
                commandCenterData.sale_history && commandCenterData.sale_history.length > 0
                  ? commandCenterData.sale_history
                  : (() => {
                      const saleText =
                        (commandCenterData.most_recent_sale_display ?? leadData.most_recent_sale) ||
                        ''
                      if (!saleText || saleText === 'None') return []
                      const price = commandCenterData.most_recent_sale_price ?? null
                      return [{
                        sale_date: saleText,
                        sale_price: price != null ? Number(price) : null,
                        sale_type: null,
                      }]
                    })()
              if (history.length === 0) {
                return (
                  <Typography variant="body2" color="text.secondary" data-testid="info-sale-history-empty">
                    {commandCenterData.county_assessor_pin || leadData.county_assessor_pin
                      ? 'No parcel sales found for this PIN.'
                      : 'Add a PIN to load Cook County sale history.'}
                  </Typography>
                )
              }
              return (
                <TableContainer>
                  <Table size="small" aria-label="Parcel sale history">
                    <TableBody>
                      {history.map((sale, index) => {
                        const dateLabel = sale.sale_date
                          ? (/^\d{4}-\d{2}-\d{2}/.test(sale.sale_date)
                            ? formatDate(sale.sale_date)
                            : sale.sale_date)
                          : '—'
                        const amountLabel =
                          sale.sale_price != null
                            ? `$${Number(sale.sale_price).toLocaleString()}`
                            : '—'
                        const typeLabel = sale.sale_type?.trim()
                        return (
                          <TableRow
                            key={`${sale.sale_date ?? 'x'}-${sale.sale_price ?? 'x'}-${index}`}
                            data-testid={`info-sale-history-row-${index}`}
                          >
                            <TableCell sx={{ width: '40%', color: 'text.secondary' }}>
                              {dateLabel}
                            </TableCell>
                            <TableCell>
                              {amountLabel}
                              {typeLabel ? (
                                <Typography
                                  component="span"
                                  variant="body2"
                                  color="text.secondary"
                                  sx={{ ml: 1 }}
                                >
                                  ({typeLabel})
                                </Typography>
                              ) : null}
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </TableContainer>
              )
            })()}
          </Box>
          {pastOwners.length > 0 && (
            <Box sx={{ mb: 3 }} data-testid="info-past-owners">
              <Typography sx={ccSubsectionTitleSx}>Past owners</Typography>
              {pastOwners.map((snap) => {
                const nameLine = (snap.owner_names || [])
                  .map((n) =>
                    [n.first_name, n.last_name].filter(Boolean).join(' ').trim(),
                  )
                  .filter(Boolean)
                  .join(' · ')
                const phoneLine = (snap.phones || [])
                  .map((p) => p.value)
                  .filter(Boolean)
                  .join(', ')
                const emailLine = (snap.emails || [])
                  .map((e) => e.value)
                  .filter(Boolean)
                  .join(', ')
                const mailingLine = [
                  snap.mailing_address,
                  [snap.mailing_city, snap.mailing_state, snap.mailing_zip]
                    .filter(Boolean)
                    .join(', '),
                ]
                  .filter(Boolean)
                  .join(', ')
                const captured = snap.captured_at
                  ? new Date(snap.captured_at).toLocaleDateString()
                  : null
                return (
                  <Box
                    key={snap.id}
                    data-testid={`info-past-owner-${snap.id}`}
                    sx={{
                      mb: 2,
                      pb: 2,
                      borderBottom: '1px solid',
                      borderColor: 'divider',
                      '&:last-child': { borderBottom: 'none', mb: 0, pb: 0 },
                    }}
                  >
                    <TableContainer>
                      <Table size="small" aria-label={`Past owner ${snap.id}`}>
                        <TableBody>
                          <TableRow>
                            <TableCell sx={{ width: '40%', color: 'text.secondary' }}>Name</TableCell>
                            <TableCell>{nameLine || '—'}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell sx={{ color: 'text.secondary' }}>Phone</TableCell>
                            <TableCell>{phoneLine || '—'}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell sx={{ color: 'text.secondary' }}>Email</TableCell>
                            <TableCell>{emailLine || '—'}</TableCell>
                          </TableRow>
                          <TableRow>
                            <TableCell sx={{ color: 'text.secondary' }}>Mailing</TableCell>
                            <TableCell>{mailingLine || '—'}</TableCell>
                          </TableRow>
                          {captured ? (
                            <TableRow>
                              <TableCell sx={{ color: 'text.secondary' }}>Captured</TableCell>
                              <TableCell>
                                {captured}
                                {snap.reason === 'recent_sale'
                                  ? ' (after sale)'
                                  : snap.reason === 'contact_replaced'
                                    ? ' (replaced)'
                                    : ''}
                              </TableCell>
                            </TableRow>
                          ) : null}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Box>
                )
              })}
            </Box>
          )}
          {fieldGroup('Research & Tracking', [
            ['Deal Source', commandCenterData.deal_source ?? '—'],
            ['Deal Description', commandCenterData.deal_description ?? '—'],
            ...(formatImportNote(commandCenterData)
              ? [['Import note', formatImportNote(commandCenterData)] as [string, string]]
              : []),
            ['Date Identified', formatDate(leadData.date_identified)],
            ['Notes', leadData.notes],
            ['Needs Skip Trace', leadData.needs_skip_trace != null ? (leadData.needs_skip_trace ? 'Yes' : 'No') : null],
            ['Skip Tracer', leadData.skip_tracer],
            ['Date Skip Traced', formatDate(leadData.date_skip_traced)],
          ])}
          {fieldGroup('Metadata', [
            ['Import channel', leadData.data_source],
            ['Created', formatDateTime(leadData.created_at)],
            ['Updated', formatDateTime(leadData.updated_at)],
          ])}
        </Box>
      )}

      {activeTab === 1 && (
        <Box sx={{ p: 2 }}>
          <Box sx={{ mb: 2, display: 'flex', justifyContent: 'flex-end' }}>
            <RecalculateButton mode="single" leadId={leadId} />
          </Box>
          <Box sx={{ mb: 2 }}>
            <ScoreLegend />
          </Box>
          {!scoreData && scoreLoading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress size={32} aria-label="Loading score" />
            </Box>
          )}
          {scoreData && !scoreData.latest && (
            <Alert severity="info" sx={{ mb: 2 }}>
              No score yet. Use the Recalculate button above to generate the first score.
            </Alert>
          )}
          {scoreData?.latest && (
            <>
              <Box sx={{ mb: 2 }}>
                <ScoreBreakdownCard score={scoreData.latest} />
              </Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Motivation signals
              </Typography>
              <Box sx={{ mb: 2 }}>
                <MotivationSignalsPanel lead={leadData} score={scoreData.latest} />
              </Box>
              <ScoreHistoryTimeline history={scoreData.history} />
            </>
          )}
        </Box>
      )}

      {activeTab === 2 && (
        <Box sx={{ p: 2 }}>
          {(leadData.enrichment_records ?? []).length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No enrichment records yet. Use the Enrich action to pull data from external sources.
            </Typography>
          ) : (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small" aria-label="Enrichment records">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 'bold' }}>Source</TableCell>
                    <TableCell sx={{ fontWeight: 'bold' }}>Status</TableCell>
                    <TableCell sx={{ fontWeight: 'bold' }}>Date</TableCell>
                    <TableCell sx={{ fontWeight: 'bold' }}>Details</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(leadData.enrichment_records ?? []).map((rec) => (
                    <TableRow key={rec.id}>
                      <TableCell>{rec.data_source_name || `Source #${rec.data_source_id}`}</TableCell>
                      <TableCell>
                        <Chip label={rec.status} size="small" color={getEnrichmentStatusColor(rec.status)} />
                      </TableCell>
                      <TableCell>{formatDateTime(rec.created_at)}</TableCell>
                      <TableCell>
                        <EnrichmentDetailsCell
                          status={rec.status}
                          retrievedData={rec.retrieved_data}
                          errorReason={rec.error_reason}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>
      )}

      {activeTab === 3 && (
        <Box sx={{ p: 2 }}>
          {(leadData.marketing_lists ?? []).length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              This property is not a member of any marketing lists.
            </Typography>
          ) : (
            <TableContainer component={Paper} variant="outlined">
              <Table size="small" aria-label="Marketing list memberships">
                <TableHead>
                  <TableRow>
                    <TableCell sx={{ fontWeight: 'bold' }}>List</TableCell>
                    <TableCell sx={{ fontWeight: 'bold' }}>Outreach Status</TableCell>
                    <TableCell sx={{ fontWeight: 'bold' }}>Added</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(leadData.marketing_lists ?? []).map((m) => (
                    <TableRow key={m.marketing_list_id}>
                      <TableCell>{m.marketing_list_name || `List #${m.marketing_list_id}`}</TableCell>
                      <TableCell>
                        <Chip
                          label={outreachStatusLabel(m.outreach_status)}
                          size="small"
                          color={getOutreachStatusColor(m.outreach_status)}
                        />
                      </TableCell>
                      <TableCell>{formatDateTime(m.added_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>
      )}

      {activeTab === 4 && (
        <Box sx={{ p: 2 }}>
          {analysisError && <Alert severity="error" sx={{ mb: 2 }}>{analysisError}</Alert>}
          {!session ? (
            <Box sx={{ textAlign: 'center', py: 4 }}>
              <Typography variant="body1" gutterBottom>
                No analysis has been started for this property yet.
              </Typography>
              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', mt: 2, flexWrap: 'wrap' }}>
                {(showSingleFamily || showBoth) && (
                  <Button
                    variant="outlined"
                    startIcon={analysisLoading ? <CircularProgress size={18} /> : <HomeWorkIcon />}
                    onClick={handleStartSingleFamily}
                    disabled={analysisLoading}
                    aria-label="Start single-family analysis"
                  >
                    Start Single-Family Analysis
                  </Button>
                )}
                {(showMultifamily || showBoth) && (
                  <Button
                    variant="contained"
                    startIcon={analysisLoading ? <CircularProgress size={18} /> : <ApartmentIcon />}
                    onClick={handleStartMultifamily}
                    disabled={analysisLoading}
                    aria-label="Start multifamily analysis"
                  >
                    Start Multifamily Analysis
                  </Button>
                )}
              </Box>
            </Box>
          ) : (
            <Box>
              <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                Linked Analysis Session
              </Typography>
              <TableContainer component={Paper} variant="outlined">
                <Table size="small" aria-label="Analysis session details">
                  <TableBody>
                    <TableRow>
                      <TableCell sx={{ width: '40%', color: 'text.secondary' }}>Session ID</TableCell>
                      <TableCell>{session.session_id}</TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary' }}>Current Step</TableCell>
                      <TableCell>{session.current_step}</TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary' }}>Created</TableCell>
                      <TableCell>{formatDateTime(session.created_at)}</TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell sx={{ color: 'text.secondary' }}>Updated</TableCell>
                      <TableCell>{formatDateTime(session.updated_at)}</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}
        </Box>
      )}

      {activeTab === 5 && (
        <Box sx={{ p: 2 }}>
          <ContactsSection propertyId={leadId} commandCenterData={commandCenterData} />
        </Box>
      )}
    </Box>
  )
}
