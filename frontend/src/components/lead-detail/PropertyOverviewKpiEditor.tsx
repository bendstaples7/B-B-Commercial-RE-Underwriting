/**
 * Click-to-edit popover for Command Center header KPIs (est. value / sale / units).
 * Category stays a dropdown; these fields use text/number inputs.
 */
import { useEffect, useState } from 'react'
import {
  Box,
  Button,
  ButtonBase,
  Popover,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { commandCenterService } from '@/services/api'
import { ccKpiValueSx } from '@/components/lead-detail/commandCenterChrome'
import { AppSnackbar } from '@/components/AppSnackbar'

export type PropertyOverviewEditKind = 'est-value' | 'last-sale' | 'units-details'
export type PropertyOverviewSaleDateField = 'most_recent_sale' | 'acquisition_date'

export interface PropertyOverviewKpiEditorProps {
  leadId: number
  kind: PropertyOverviewEditKind
  displayValue: string
  assessedValue?: number | null
  mostRecentSale?: string | null
  saleDateField?: PropertyOverviewSaleDateField
  mostRecentSalePrice?: number | null
  units?: number | null
  propertyType?: string | null
  allowWrap?: boolean
  onSaved?: () => void | Promise<void>
}

function saleDateInputValue(raw: string | null | undefined): string {
  if (!raw) return ''
  const s = String(raw).trim()
  const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`
  const us = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/)
  if (us) {
    const mm = us[1].padStart(2, '0')
    const dd = us[2].padStart(2, '0')
    return `${us[3]}-${mm}-${dd}`
  }
  return ''
}

export function PropertyOverviewKpiEditor({
  leadId,
  kind,
  displayValue,
  assessedValue,
  mostRecentSale,
  saleDateField = 'most_recent_sale',
  mostRecentSalePrice,
  units,
  propertyType,
  allowWrap = false,
  onSaved,
}: PropertyOverviewKpiEditorProps) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const [saving, setSaving] = useState(false)
  const [snack, setSnack] = useState<string | null>(null)
  const [valueDraft, setValueDraft] = useState('')
  const [saleDateDraft, setSaleDateDraft] = useState('')
  const [initialSaleDateDraft, setInitialSaleDateDraft] = useState('')
  const [saleDateTouched, setSaleDateTouched] = useState(false)
  const [salePriceDraft, setSalePriceDraft] = useState('')
  const [unitsDraft, setUnitsDraft] = useState('')
  const [typeDraft, setTypeDraft] = useState('')

  const open = Boolean(anchorEl)

  useEffect(() => {
    if (!open) return
    setValueDraft(assessedValue != null && Number.isFinite(Number(assessedValue)) ? String(assessedValue) : '')
    const nextSaleDateDraft = saleDateInputValue(mostRecentSale)
    setSaleDateDraft(nextSaleDateDraft)
    setInitialSaleDateDraft(nextSaleDateDraft)
    setSaleDateTouched(false)
    setSalePriceDraft(
      mostRecentSalePrice != null && Number.isFinite(Number(mostRecentSalePrice))
        ? String(mostRecentSalePrice)
        : '',
    )
    setUnitsDraft(units != null && Number.isFinite(Number(units)) ? String(units) : '')
    setTypeDraft((propertyType || '').trim())
  }, [open, assessedValue, mostRecentSale, mostRecentSalePrice, units, propertyType, leadId])

  const ariaLabel =
    kind === 'est-value'
      ? `Est. value: ${displayValue}. Click to edit.`
      : kind === 'last-sale'
        ? `Last sale: ${displayValue}. Click to edit.`
        : `Units and details: ${displayValue}. Click to edit.`

  const parseOptionalNumber = (raw: string): number | null => {
    const t = raw.trim()
    if (!t) return null
    const normalized = t.replace(/[$,\s]/g, '')
    if (!normalized) throw new Error('Enter a valid number.')
    const n = Number(normalized)
    if (!Number.isFinite(n)) {
      throw new Error('Enter a valid number.')
    }
    return n
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const body: Record<string, number | string | null> = {}
      if (kind === 'est-value') {
        body.assessed_value = parseOptionalNumber(valueDraft)
      } else if (kind === 'last-sale') {
        const nextSaleDate = saleDateDraft.trim()
        const setSaleDateBody = (value: string | null) => {
          body[saleDateField] = value
          if (saleDateField === 'acquisition_date') {
            body.most_recent_sale = value
          }
        }
        if (nextSaleDate && (saleDateTouched || saleDateDraft !== initialSaleDateDraft)) {
          setSaleDateBody(nextSaleDate)
        } else if (!nextSaleDate && saleDateTouched) {
          setSaleDateBody(null)
        }
        body.most_recent_sale_price = parseOptionalNumber(salePriceDraft)
      } else {
        const unitsVal = unitsDraft.trim()
        const unitsNumber = unitsVal === '' ? null : parseOptionalNumber(unitsDraft)
        if (unitsNumber != null && !Number.isInteger(unitsNumber)) {
          throw new Error('Units must be a whole number.')
        }
        body.units = unitsNumber
        body.property_type = typeDraft.trim() || null
      }
      await commandCenterService.updatePropertyOverview(leadId, body)
      setAnchorEl(null)
      await onSaved?.()
    } catch (err) {
      setSnack(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <ButtonBase
        data-testid={`quick-stat-${kind}-edit-trigger`}
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        aria-expanded={open ? 'true' : undefined}
        disabled={saving}
        onClick={(event) => setAnchorEl(event.currentTarget)}
        sx={{
          display: 'inline-flex',
          alignItems: 'flex-start',
          maxWidth: '100%',
          justifyContent: 'flex-start',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <Typography
          data-testid={`quick-stat-${kind}-value`}
          sx={{
            ...ccKpiValueSx,
            fontSize: '0.875rem',
            mt: 0.125,
            lineHeight: 1.25,
            minWidth: 0,
            maxWidth: '100%',
            whiteSpace: allowWrap ? 'normal' : 'nowrap',
            overflowWrap: allowWrap ? 'break-word' : undefined,
            wordBreak: allowWrap ? 'break-word' : undefined,
            textOverflow: allowWrap ? undefined : 'ellipsis',
            overflow: 'hidden',
            color: 'primary.main',
          }}
        >
          {displayValue}
        </Typography>
      </ButtonBase>
      <Popover
        open={open}
        anchorEl={anchorEl}
        onClose={() => {
          if (!saving) setAnchorEl(null)
        }}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
        transformOrigin={{ vertical: 'top', horizontal: 'left' }}
        slotProps={{
          paper: {
            sx: { p: 1.5, minWidth: 240, maxWidth: 320, cursor: 'auto' },
          },
        }}
      >
        <Stack
          spacing={1.25}
          component="form"
          data-testid={`quick-stat-${kind}-editor`}
          onSubmit={(event) => {
            event.preventDefault()
            void handleSave()
          }}
        >
          {kind === 'est-value' ? (
            <TextField
              label="Est. value"
              size="small"
              value={valueDraft}
              onChange={(e) => setValueDraft(e.target.value)}
              inputProps={{
                'data-testid': 'quick-stat-est-value-input',
                inputMode: 'decimal',
              }}
              autoFocus
              fullWidth
              sx={{ '& input': { caretColor: 'text.primary', cursor: 'text' } }}
            />
          ) : null}
          {kind === 'last-sale' ? (
            <>
              <TextField
                label="Sale date"
                type="date"
                size="small"
                value={saleDateDraft}
                onChange={(e) => {
                  setSaleDateTouched(true)
                  setSaleDateDraft(e.target.value)
                }}
                InputLabelProps={{ shrink: true }}
                inputProps={{ 'data-testid': 'quick-stat-last-sale-date-input' }}
                autoFocus
                fullWidth
                sx={{ '& input': { caretColor: 'text.primary', cursor: 'text' } }}
              />
              <TextField
                label="Sale price"
                size="small"
                value={salePriceDraft}
                onChange={(e) => setSalePriceDraft(e.target.value)}
                inputProps={{
                  'data-testid': 'quick-stat-last-sale-price-input',
                  inputMode: 'decimal',
                }}
                fullWidth
                sx={{ '& input': { caretColor: 'text.primary', cursor: 'text' } }}
              />
            </>
          ) : null}
          {kind === 'units-details' ? (
            <>
              <TextField
                label="Units"
                size="small"
                value={unitsDraft}
                onChange={(e) => setUnitsDraft(e.target.value)}
                inputProps={{
                  'data-testid': 'quick-stat-units-input',
                  inputMode: 'numeric',
                }}
                autoFocus
                fullWidth
                sx={{ '& input': { caretColor: 'text.primary', cursor: 'text' } }}
              />
              <TextField
                label="Property type"
                size="small"
                value={typeDraft}
                onChange={(e) => setTypeDraft(e.target.value)}
                placeholder="e.g. Single Family"
                inputProps={{ 'data-testid': 'quick-stat-property-type-input' }}
                fullWidth
                sx={{ '& input': { caretColor: 'text.primary', cursor: 'text' } }}
              />
            </>
          ) : null}
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
            <Button
              size="small"
              onClick={() => setAnchorEl(null)}
              disabled={saving}
              data-testid={`quick-stat-${kind}-cancel`}
              sx={{ cursor: 'pointer' }}
            >
              Cancel
            </Button>
            <Button
              size="small"
              variant="contained"
              type="submit"
              disabled={saving}
              data-testid={`quick-stat-${kind}-save`}
              sx={{ cursor: 'pointer' }}
            >
              Save
            </Button>
          </Box>
        </Stack>
      </Popover>
      <AppSnackbar
        open={Boolean(snack)}
        onClose={() => setSnack(null)}
        message={snack ?? ''}
        severity="error"
      />
    </>
  )
}

export default PropertyOverviewKpiEditor
