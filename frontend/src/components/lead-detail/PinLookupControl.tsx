/**
 * Shared PIN lookup / apply — used by Property Overview header and PropertySidebar.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Box,
  Button,
  CircularProgress,
  IconButton,
  Popover,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { useQueryClient } from '@tanstack/react-query'
import type { CommandCenterPayload, CondoRiskStatus, BuildingSalePossible } from '@/types'
import { formatCookCountyPin } from '@/utils/cookCountyPin'
import { leadTaskService, commandCenterService } from '@/services/api'
import {
  buildingOwnershipService,
  propertyMatchService,
} from '@/services/propertyMatchApi'

export type PinCandidate = {
  pin: string
  property_street?: string | null
  property_city?: string | null
  property_state?: string | null
  property_zip?: string | null
  source?: string | null
}

export type PinPreviewMeta = {
  tax_situs_street?: string | null
  tax_situs_pin_count?: number | null
  require_explicit_apply?: boolean
  assessor_aka?: { property_street?: string | null } | null
}

export function CopyablePin({
  pin,
  valueTestId,
  copyTestId = 'pin-copy',
  align = 'end',
}: {
  pin: string
  valueTestId?: string
  copyTestId?: string
  /** Popover rows use start; header metadata may keep end. */
  align?: 'start' | 'end'
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
        justifyContent: align === 'end' ? 'flex-end' : 'flex-start',
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
          data-testid={copyTestId}
          sx={{ p: 0.25, flexShrink: 0 }}
        >
          <ContentCopyIcon sx={{ fontSize: 11 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

function normalizeCandidates(preview: {
  candidates?: PinCandidate[] | null
  pins?: string[] | null
  pin?: string | null
  recommended_address?: { county_assessor_pin?: string | null } | null
}): PinCandidate[] {
  const fromRows = (preview.candidates || [])
    .map((row) => ({
      ...row,
      pin: formatCookCountyPin(row.pin || '') || '',
    }))
    .filter((row) => Boolean(row.pin))
  if (fromRows.length) return fromRows.slice(0, 5)

  const pins = (preview.pins || [])
    .map((p) => formatCookCountyPin(p) || '')
    .filter(Boolean)
  if (pins.length) {
    return pins.slice(0, 5).map((pin) => ({ pin }))
  }
  const single = formatCookCountyPin(
    preview.pin || preview.recommended_address?.county_assessor_pin || '',
  )
  return single ? [{ pin: single }] : []
}

const CONDO_MULTI_PIN_DEPRIORITIZE_REASON =
  'Likely condoized / multi-PIN tax situs — confirm deprioritize.'

function titleCaseStreet(street: string): string {
  return street
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export function usePinLookup(
  leadId: number,
  currentPin: string | null | undefined,
  onSnack: (message: string) => void,
  options?: {
    autoPreview?: boolean
    isCookCounty?: boolean
  },
) {
  const queryClient = useQueryClient()
  const [pinLookupPending, setPinLookupPending] = useState(false)
  const [pinCandidate, setPinCandidate] = useState<string | null>(null)
  const [pinCandidates, setPinCandidates] = useState<PinCandidate[]>([])
  const [previewMeta, setPreviewMeta] = useState<PinPreviewMeta>({})
  const [pinApplyPending, setPinApplyPending] = useState(false)
  const [analyzePending, setAnalyzePending] = useState(false)
  const [showPinEntry, setShowPinEntry] = useState(false)
  const [manualPin, setManualPin] = useState('')
  const autoPreviewDone = useRef<number | null>(null)

  useEffect(() => {
    setPinLookupPending(false)
    setPinCandidate(null)
    setPinCandidates([])
    setPreviewMeta({})
    setPinApplyPending(false)
    setAnalyzePending(false)
    setShowPinEntry(false)
    setManualPin('')
    autoPreviewDone.current = null
  }, [leadId])

  const applyPin = useCallback(async (pin: string, contextMessage?: string | null) => {
    setPinApplyPending(true)
    try {
      const result = await propertyMatchService.approve(leadId, { pin })
      const appliedPin = formatCookCountyPin(
        (result as { county_assessor_pin?: string | null })?.county_assessor_pin,
      ) || pin
      const akaStreet = (result as { assessor_aka_street?: string | null })
        ?.assessor_aka_street ?? null
      queryClient.setQueryData<CommandCenterPayload>(
        ['commandCenter', leadId],
        (current) => (current
          ? {
              ...current,
              county_assessor_pin: appliedPin,
              assessor_aka_street: akaStreet ?? current.assessor_aka_street,
              assessor_aka_city: (result as { assessor_aka_city?: string | null })
                ?.assessor_aka_city ?? current.assessor_aka_city,
              assessor_aka_state: (result as { assessor_aka_state?: string | null })
                ?.assessor_aka_state ?? current.assessor_aka_state,
              assessor_aka_zip: (result as { assessor_aka_zip?: string | null })
                ?.assessor_aka_zip ?? current.assessor_aka_zip,
            }
          : current),
      )
      setPinCandidate(null)
      setPinCandidates([])
      setPreviewMeta({})
      setShowPinEntry(false)
      setManualPin('')
      onSnack(
        contextMessage
          ? `${contextMessage}; PIN applied: ${appliedPin}`
          : `PIN applied: ${appliedPin}`,
      )
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    } catch (error) {
      onSnack(error instanceof Error ? error.message : 'Could not apply PIN')
    } finally {
      setPinApplyPending(false)
    }
  }, [leadId, onSnack, queryClient])

  const lookUpPin = useCallback(async (
    pinHint?: string,
    opts?: { quiet?: boolean; createResearchTask?: boolean },
  ) => {
    const quiet = Boolean(opts?.quiet)
    const createResearchTask = opts?.createResearchTask !== false
    setPinLookupPending(true)
    setPinCandidate(null)
    setPinCandidates([])
    setPreviewMeta({})
    try {
      const preview = await propertyMatchService.preview(
        leadId,
        pinHint ? { pin: pinHint } : undefined,
      )
      const candidates = normalizeCandidates(preview)
      const pin = candidates[0]?.pin || null
      setPreviewMeta({
        tax_situs_street: preview.tax_situs_street ?? null,
        tax_situs_pin_count: preview.tax_situs_pin_count ?? null,
        require_explicit_apply: Boolean(preview.require_explicit_apply),
        assessor_aka: preview.assessor_aka ?? null,
      })
      if (preview.reason === 'incomplete_address' || preview.address_complete === false) {
        if (!quiet) {
          onSnack(
            preview.message
            || 'Add city, state, and ZIP — then look up PIN',
          )
        }
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
        return
      }
      if (preview.found && candidates.length) {
        setPinCandidates(candidates)
        setPinCandidate(pin)
        const autoApply = (
          candidates.length === 1
          && preview.pin_count === 1
          && !preview.require_explicit_apply
        )
        if (autoApply && pin) {
          await applyPin(pin, preview.message)
          return
        }
        const taxCount = Number(preview.tax_situs_pin_count) || 0
        const multiTaxSitus = Boolean(
          (taxCount > 1 || candidates.length > 1)
          && (preview.tax_situs_street || preview.require_explicit_apply),
        )
        if (multiTaxSitus) {
          const isCommercial = (
            (queryClient.getQueryData<CommandCenterPayload>(['commandCenter', leadId])
              ?.lead_category ?? '').toLowerCase() === 'commercial'
          )
          // Immediately demote LLC research in the header while condo check runs.
          if (isCommercial) {
            queryClient.setQueryData<CommandCenterPayload>(
              ['commandCenter', leadId],
              (current) => {
                if (!current) return current
                return {
                  ...current,
                  needs_entity_research: false,
                  condo_risk_status: current.condo_risk_status === 'likely_condo'
                    ? current.condo_risk_status
                    : 'likely_condo',
                  recommended_action: {
                    ...(current.recommended_action || {}),
                    value: 'needs_manual_review',
                    label: 'Confirm deprioritize?',
                    explanation:
                      'Likely condoized / multi-PIN tax situs — confirm deprioritize.',
                    winning_rule: 'likely_condo',
                    winning_rule_label: 'Commercial lead flagged as likely condo',
                  },
                }
              },
            )
          }
          try {
            const taxStreet = (
              preview.tax_situs_street
              || preview.assessor_aka?.property_street
              || candidates[0]?.property_street
              || null
            )
            await buildingOwnershipService.analyze(leadId, {
              force: true,
              tax_situs_street: taxStreet || undefined,
              candidate_pins: candidates.map((c) => c.pin),
              apply_closest_pin: false,
              // Quiet auto-preview must not persist AKA without user consent.
              persist_aka: !quiet,
            })
            await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
          } catch (error) {
            // Analyze failed — drop optimistic Confirm deprioritize rather than
            // leaving a status/action the server never produced.
            await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
            if (!quiet) {
              onSnack(error instanceof Error ? error.message : 'Condo check failed')
            }
          }
        }
        return
      }
      // Keep Look up / Enter PIN — do not force manual entry; user opts in via Enter PIN.
      if (createResearchTask && !quiet) {
        await leadTaskService.createTask(leadId, {
          title: 'Research missing PIN',
          task_type: 'research_missing_pin',
        })
        onSnack(preview.message || 'No PIN found — enter PIN or research task created')
        await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      } else if (!quiet) {
        onSnack(preview.message || 'No PIN found')
      }
    } catch (error) {
      if (!quiet) {
        onSnack(error instanceof Error ? error.message : 'PIN lookup failed')
      }
    } finally {
      setPinLookupPending(false)
    }
  }, [applyPin, leadId, onSnack, queryClient])

  const verifyManualPin = useCallback(async () => {
    const formatted = formatCookCountyPin(manualPin)
    if (!formatted) {
      onSnack('Enter a valid 14-digit Cook County PIN')
      return
    }
    await lookUpPin(formatted)
  }, [lookUpPin, manualPin, onSnack])

  const analyzeTaxSitus = useCallback(async (opts?: { applyClosest?: boolean }) => {
    if (!pinCandidates.length) return
    setAnalyzePending(true)
    try {
      const taxStreet = (
        previewMeta.tax_situs_street
        || previewMeta.assessor_aka?.property_street
        || pinCandidates[0]?.property_street
        || null
      )
      const result = await buildingOwnershipService.analyze(leadId, {
        force: true,
        tax_situs_street: taxStreet || undefined,
        candidate_pins: pinCandidates.map((c) => c.pin),
        apply_closest_pin: Boolean(opts?.applyClosest),
      })
      const condoStatus = (
        (result as { condo_risk_status?: CondoRiskStatus | null }).condo_risk_status
        ?? null
      )
      const buildingSale = (
        (result as { building_sale_possible?: BuildingSalePossible | null })
          .building_sale_possible
        ?? null
      )
      const condoLikely = condoStatus === 'likely_condo'
      queryClient.setQueryData<CommandCenterPayload>(
        ['commandCenter', leadId],
        (current) => {
          if (!current) return current
          return {
            ...current,
            county_assessor_pin: (
              (result as { county_assessor_pin?: string | null }).county_assessor_pin
              ?? current.county_assessor_pin
            ),
            assessor_aka_street: (
              (result as { assessor_aka_street?: string | null }).assessor_aka_street
              ?? taxStreet
              ?? current.assessor_aka_street
            ),
            condo_risk_status: condoStatus ?? current.condo_risk_status,
            building_sale_possible: buildingSale ?? current.building_sale_possible,
            ...(condoLikely
              ? {
                  needs_entity_research: false,
                  recommended_action: {
                    ...(current.recommended_action || {}),
                    value: 'needs_manual_review',
                    label: 'Confirm deprioritize?',
                    explanation:
                      'Likely condoized / multi-PIN tax situs — confirm deprioritize.',
                    winning_rule: 'likely_condo',
                    winning_rule_label: 'Commercial lead flagged as likely condo',
                  },
                }
              : {}),
          }
        },
      )
      if (opts?.applyClosest) {
        setPinCandidate(null)
        setPinCandidates([])
        setPreviewMeta({})
      }
      onSnack('Condo check updated from tax situs PINs')
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
    } catch (error) {
      onSnack(error instanceof Error ? error.message : 'Condo check failed')
    } finally {
      setAnalyzePending(false)
    }
  }, [leadId, onSnack, pinCandidates, previewMeta, queryClient])

  const optimisticPin = pinApplyPending ? pinCandidate : null
  const displayedPin = optimisticPin || currentPin || ''
  const pinMissing = !String(displayedPin).trim()

  // Auto-preview once per lead when Cook PIN is blank.
  // Quiet preview may classify (persist_aka=false) but must not write AKA.
  useEffect(() => {
    if (!options?.autoPreview || !options?.isCookCounty) return
    if (!pinMissing) return
    if (autoPreviewDone.current === leadId) return
    if (pinLookupPending || pinCandidates.length > 0) return
    autoPreviewDone.current = leadId
    void lookUpPin(undefined, { quiet: true, createResearchTask: false })
  }, [
    leadId,
    lookUpPin,
    options?.autoPreview,
    options?.isCookCounty,
    pinCandidates.length,
    pinLookupPending,
    pinMissing,
  ])

  return {
    pinLookupPending,
    pinCandidate,
    pinCandidates,
    previewMeta,
    pinApplyPending,
    analyzePending,
    displayedPin,
    pinMissing,
    showPinEntry,
    manualPin,
    setManualPin,
    setShowPinEntry,
    lookUpPin,
    verifyManualPin,
    applyPin,
    analyzeTaxSitus,
    applyPinCandidate: async () => {
      if (pinCandidate) await applyPin(pinCandidate)
    },
  }
}

export interface MissingPinActionsProps {
  leadId: number
  currentPin: string | null | undefined
  onSnack: (message: string) => void
  /** Prefix for data-testid (e.g. sidebar → sidebar-look-up-pin). */
  testIdPrefix: string
  /** Layout alignment for the action cluster. */
  align?: 'start' | 'end'
  /** When true, omit the "None" / "—" caption (parent already shows it). */
  hideEmptyCaption?: boolean
  emptyCaption?: string
  /** stack = sidebar column; inline = header metadata row. */
  layout?: 'stack' | 'inline'
  /** Auto-run preview when Cook-eligible and PIN blank. */
  autoPreview?: boolean
  isCookCounty?: boolean
  /** Snapshot queue neighbour before deprioritize PATCH (parent). */
  onBeforeDeprioritize?: () => void
  /** After multi-PIN deprioritize succeeds (queue hold / refresh). */
  onAfterDeprioritize?: () => void | Promise<void>
}

/**
 * Look up / Apply controls when the lead PIN is blank.
 * Returns null once a PIN is present (parent should render the value).
 */
export function MissingPinActions({
  leadId,
  currentPin,
  onSnack,
  testIdPrefix,
  align = 'end',
  hideEmptyCaption = false,
  emptyCaption = 'None',
  layout = 'stack',
  autoPreview = false,
  isCookCounty = false,
  onBeforeDeprioritize,
  onAfterDeprioritize,
}: MissingPinActionsProps) {
  const {
    pinMissing,
    pinLookupPending,
    pinCandidate,
    pinCandidates,
    previewMeta,
    pinApplyPending,
    analyzePending,
    showPinEntry,
    manualPin,
    setManualPin,
    setShowPinEntry,
    lookUpPin,
    verifyManualPin,
    applyPin,
    analyzeTaxSitus,
    applyPinCandidate,
  } = usePinLookup(leadId, currentPin, onSnack, { autoPreview, isCookCounty })

  const anchorRef = useRef<HTMLDivElement | null>(null)
  const [resultsOpen, setResultsOpen] = useState(false)
  const [deprioritizePending, setDeprioritizePending] = useState(false)
  const queryClient = useQueryClient()

  const taxStreet = (
    previewMeta.tax_situs_street
    || previewMeta.assessor_aka?.property_street
    || null
  )
  const hasOverlayResults = pinCandidates.length > 0 || Boolean(pinCandidate)

  // Open overlay near PIN when GIS settle produces candidates (keep header compact).
  useEffect(() => {
    if (!pinMissing) {
      setResultsOpen(false)
      return
    }
    if (hasOverlayResults && !pinLookupPending) {
      setResultsOpen(true)
    }
    if (!hasOverlayResults) {
      setResultsOpen(false)
    }
  }, [hasOverlayResults, pinLookupPending, leadId, pinMissing])

  if (!pinMissing && !pinApplyPending) return null

  const taxCount = previewMeta.tax_situs_pin_count || pinCandidates.length
  const showAkaBanner = Boolean(taxStreet && pinCandidates.length > 0)

  const primaryTaxCandidates = taxStreet
    ? pinCandidates.filter((c) => {
        const s = (c.property_street || '').trim().toUpperCase()
        const taxName = taxStreet.trim().toUpperCase().replace(/^\d+(?:-\d+)?\s+/, '')
        const candName = s.replace(/^\d+(?:-\d+)?\s+/, '')
        return candName && taxName && candName === taxName
      })
    : []
  const otherCandidates = taxStreet
    ? pinCandidates.filter((c) => {
        const s = (c.property_street || '').trim().toUpperCase()
        const taxName = taxStreet.trim().toUpperCase().replace(/^\d+(?:-\d+)?\s+/, '')
        const candName = s.replace(/^\d+(?:-\d+)?\s+/, '')
        return !candName || candName !== taxName
      })
    : pinCandidates
  const listRows = primaryTaxCandidates.length
    ? [...primaryTaxCandidates, ...otherCandidates]
    : pinCandidates.length
      ? pinCandidates
      : (pinCandidate ? [{ pin: pinCandidate }] : [])

  const multiPinTaxSitus = Boolean(
    showAkaBanner
    && ((typeof taxCount === 'number' && taxCount > 1) || listRows.length > 1),
  )

  const handleDeprioritizeMultiPin = async () => {
    setDeprioritizePending(true)
    let updated = false
    try {
      onBeforeDeprioritize?.()
      await commandCenterService.updateStatus(
        leadId,
        'deprioritize',
        CONDO_MULTI_PIN_DEPRIORITIZE_REASON,
      )
      updated = true
      setResultsOpen(false)
      onSnack('Lead deprioritized — commercial split into condos')
    } catch (error) {
      onSnack(error instanceof Error ? error.message : 'Could not deprioritize lead')
    } finally {
      setDeprioritizePending(false)
    }
    if (!updated) return
    try {
      await queryClient.invalidateQueries({ queryKey: ['commandCenter', leadId] })
      await queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
      await onAfterDeprioritize?.()
    } catch (error) {
      console.warn('post-deprioritize refresh failed', error)
    }
  }

  const akaBanner = showAkaBanner ? (
    <Box
      data-testid={`${testIdPrefix}-pin-lookup-aka-banner`}
      sx={{
        width: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        alignItems: 'flex-start',
        textAlign: 'left',
      }}
    >
      <Typography
        variant="caption"
        component="div"
        sx={{ fontSize: '0.75rem', lineHeight: 1.35, color: 'text.primary' }}
      >
        Also known as (tax situs):{' '}
        <Box component="span" sx={{ fontWeight: 600 }}>
          {titleCaseStreet(taxStreet || '')}
        </Box>
        {taxCount ? ` — ${taxCount} parcel PIN${taxCount === 1 ? '' : 's'} nearby` : ''}
      </Typography>
      <Typography
        variant="caption"
        color="text.secondary"
        component="div"
        sx={{ fontSize: '0.7rem', lineHeight: 1.3 }}
      >
        Marketing address kept. Review matches before applying.
      </Typography>
      <Box
        sx={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 0.75,
          width: '100%',
        }}
      >
        <Button
          size="small"
          variant="outlined"
          onClick={() => { void analyzeTaxSitus({ applyClosest: true }) }}
          disabled={pinApplyPending || analyzePending || !(listRows[0]?.pin || pinCandidate)}
          data-testid={`${testIdPrefix}-apply-closest-pin`}
        >
          {pinApplyPending || analyzePending ? 'Applying…' : 'Apply closest PIN'}
        </Button>
        <Button
          size="small"
          variant="text"
          onClick={() => { void analyzeTaxSitus({ applyClosest: false }) }}
          disabled={analyzePending || pinApplyPending}
          data-testid={`${testIdPrefix}-analyze-tax-situs`}
          startIcon={
            analyzePending ? (
              <CircularProgress size={12} color="inherit" aria-hidden />
            ) : undefined
          }
        >
          {analyzePending ? 'Analyzing…' : 'Analyze building at tax address'}
        </Button>
      </Box>
    </Box>
  ) : null

  const deprioritizeFooter = multiPinTaxSitus ? (
    <Box
      sx={{
        flexShrink: 0,
        px: 1.5,
        py: 1.25,
        borderTop: 1,
        borderColor: 'divider',
        bgcolor: 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        gap: 0.75,
        width: '100%',
      }}
      data-testid={`${testIdPrefix}-pin-deprioritize-cta`}
    >
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ fontSize: '0.7rem', lineHeight: 1.35 }}
      >
        Multiple PINs at the same tax situs usually means the building was split into
        condos — picking one PIN won&apos;t change outreach value.
      </Typography>
      <Button
        size="small"
        variant="contained"
        color="primary"
        fullWidth
        disabled={deprioritizePending || pinApplyPending || analyzePending}
        onClick={() => { void handleDeprioritizeMultiPin() }}
        data-testid={`${testIdPrefix}-deprioritize-multi-pin`}
        startIcon={
          deprioritizePending ? (
            <CircularProgress size={14} color="inherit" aria-hidden />
          ) : undefined
        }
      >
        {deprioritizePending ? 'Deprioritizing…' : 'Deprioritize — likely condos'}
      </Button>
    </Box>
  ) : null

  const resultsBody = (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        minWidth: 280,
        maxWidth: 420,
        maxHeight: 360,
        cursor: 'auto',
        overflow: 'hidden',
      }}
      data-testid={`${testIdPrefix}-pin-candidates`}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          gap: 1,
          p: 1.5,
          pb: multiPinTaxSitus ? 1 : 1.5,
          minHeight: 0,
          flex: '1 1 auto',
          overflowY: 'auto',
        }}
      >
        {akaBanner}
        {listRows.map((row) => (
          <Box
            key={row.pin}
            sx={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              gap: 1.25,
              flexWrap: 'nowrap',
              justifyContent: 'space-between',
              width: '100%',
              minHeight: 40,
            }}
          >
            <Box
              sx={{
                minWidth: 0,
                flex: '1 1 auto',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                gap: 0.15,
              }}
            >
              <CopyablePin
                pin={row.pin}
                align="start"
                valueTestId={`${testIdPrefix}-pin-candidate-${row.pin}`}
                copyTestId={`${testIdPrefix}-pin-copy-${row.pin}`}
              />
              {'property_street' in row && row.property_street ? (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  component="div"
                  sx={{
                    fontSize: '0.7rem',
                    lineHeight: 1.25,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                  title={row.property_street}
                >
                  {row.property_street}
                </Typography>
              ) : null}
            </Box>
            <Button
              size="small"
              variant="text"
              onClick={() => { void applyPin(row.pin) }}
              disabled={pinApplyPending || analyzePending}
              data-testid={`${testIdPrefix}-apply-pin-${row.pin}`}
              sx={{
                flexShrink: 0,
                alignSelf: 'center',
                minHeight: 32,
              }}
            >
              {pinApplyPending ? 'Applying…' : 'Apply'}
            </Button>
          </Box>
        ))}
        {!showAkaBanner && pinCandidate && listRows.length === 1 ? (
          <Button
            size="small"
            variant="contained"
            onClick={() => { void applyPinCandidate() }}
            disabled={pinApplyPending}
            data-testid={`${testIdPrefix}-apply-pin`}
          >
            {pinApplyPending ? 'Applying…' : 'Apply PIN'}
          </Button>
        ) : null}
      </Box>
      {deprioritizeFooter}
    </Box>
  )

  let compactTrigger: ReactNode
  if (pinLookupPending && (autoPreview || !hasOverlayResults)) {
    compactTrigger = (
      <Box
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.75,
        }}
        aria-busy
        aria-live="polite"
        data-testid={`${testIdPrefix}-pin-lookup-loading`}
      >
        <CircularProgress size={14} aria-hidden />
        <Typography variant="caption" fontWeight={600} sx={{ fontSize: '0.75rem' }}>
          Looking up PIN…
        </Typography>
      </Box>
    )
  } else if (hasOverlayResults) {
    const countLabel = listRows.length > 1
      ? `${listRows.length} PIN matches`
      : 'PIN match'
    compactTrigger = (
      <Button
        size="small"
        variant="text"
        onClick={() => setResultsOpen(true)}
        data-testid={`${testIdPrefix}-pin-results-open`}
        sx={{ minWidth: 0, px: 0.5, py: 0, fontSize: '0.7rem' }}
      >
        {countLabel}
      </Button>
    )
  } else if (showPinEntry) {
    // Manual mode replaces Look up PIN entirely until the user cancels.
    compactTrigger = (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.5,
          flexWrap: 'wrap',
        }}
        data-testid={`${testIdPrefix}-pin-entry`}
      >
        <TextField
          size="small"
          value={manualPin}
          onChange={(e) => setManualPin(e.target.value)}
          placeholder="14-digit PIN"
          autoFocus
          inputProps={{
            'data-testid': `${testIdPrefix}-pin-input`,
            'aria-label': 'Cook County PIN',
          }}
          sx={{
            width: 160,
            '& .MuiInputBase-input': { fontSize: '0.7rem', py: 0.5, cursor: 'text' },
            '& .MuiInputBase-root': { cursor: 'text' },
          }}
        />
        <Button
          size="small"
          variant="text"
          onClick={() => { void verifyManualPin() }}
          disabled={pinLookupPending || pinApplyPending}
          data-testid={`${testIdPrefix}-verify-pin`}
          sx={{ minWidth: 0, px: 0.5, py: 0, fontSize: '0.7rem' }}
        >
          {pinLookupPending || pinApplyPending ? 'Verifying…' : 'Verify'}
        </Button>
        <Button
          size="small"
          variant="text"
          onClick={() => {
            setShowPinEntry(false)
            setManualPin('')
          }}
          disabled={pinLookupPending || pinApplyPending}
          data-testid={`${testIdPrefix}-cancel-pin-entry`}
          sx={{ minWidth: 0, px: 0.5, py: 0, fontSize: '0.7rem' }}
        >
          Cancel
        </Button>
      </Box>
    )
  } else {
    compactTrigger = (
      <Box
        sx={{
          display: 'flex',
          flexDirection: layout === 'inline' ? 'row' : 'column',
          alignItems: layout === 'inline' ? 'center' : (align === 'end' ? 'flex-end' : 'flex-start'),
          gap: 0.5,
          flexWrap: 'wrap',
        }}
      >
        <Button
          size="small"
          variant="text"
          onClick={() => { void lookUpPin() }}
          disabled={pinLookupPending}
          data-testid={`${testIdPrefix}-look-up-pin`}
          startIcon={
            pinLookupPending ? (
              <CircularProgress size={12} color="inherit" aria-hidden />
            ) : undefined
          }
          sx={{ minWidth: 0, px: 0.5, py: 0, fontSize: '0.7rem' }}
        >
          {pinLookupPending ? 'Looking up…' : 'Look up PIN'}
        </Button>
        <Button
          size="small"
          variant="text"
          onClick={() => setShowPinEntry(true)}
          disabled={pinLookupPending}
          data-testid={`${testIdPrefix}-enter-pin`}
          sx={{ minWidth: 0, px: 0.5, py: 0, fontSize: '0.7rem' }}
        >
          Enter PIN
        </Button>
      </Box>
    )
  }

  return (
    <Box
      ref={anchorRef}
      sx={{
        display: layout === 'inline' ? 'inline-flex' : 'flex',
        flexDirection: layout === 'inline' ? 'row' : 'column',
        alignItems: layout === 'inline'
          ? 'center'
          : (align === 'end' ? 'flex-end' : 'flex-start'),
        gap: 0.5,
        verticalAlign: 'baseline',
        position: 'relative',
      }}
      data-testid={`${testIdPrefix}-pin-lookup`}
    >
      {!hideEmptyCaption && (
        <Typography variant="caption" color="text.disabled" component="span">
          {emptyCaption}
        </Typography>
      )}
      {compactTrigger}
      <Popover
        open={resultsOpen && hasOverlayResults}
        anchorEl={anchorRef.current}
        onClose={() => setResultsOpen(false)}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: align === 'end' ? 'right' : 'left',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: align === 'end' ? 'right' : 'left',
        }}
        disableScrollLock
        slotProps={{
          paper: {
            sx: {
              mt: 0.5,
              border: 1,
              borderColor: 'divider',
              boxShadow: '0 8px 24px rgba(16, 24, 40, 0.12)',
              cursor: 'auto',
            },
          },
        }}
      >
        <Box data-testid={`${testIdPrefix}-pin-results-popover`}>
          {resultsBody}
        </Box>
      </Popover>
    </Box>
  )
}
