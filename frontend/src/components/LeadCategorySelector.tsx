/**
 * Header Category control — Residential / Commercial menu that saves immediately.
 */
import { useEffect, useState } from 'react'
import { ButtonBase, Menu, MenuItem, Typography } from '@mui/material'
import ArrowDropDownIcon from '@mui/icons-material/ArrowDropDown'
import { commandCenterService } from '@/services/api'
import { formatLeadCategoryLabel } from '@/utils/formatters'
import { ccKpiValueSx } from '@/components/lead-detail/commandCenterChrome'
import { AppSnackbar } from '@/components/AppSnackbar'

const OPTIONS: Array<'residential' | 'commercial'> = ['residential', 'commercial']

export interface LeadCategorySelectorProps {
  leadId: number
  category: string | null | undefined
  onChanged?: (next: 'residential' | 'commercial') => void | Promise<void>
}

export function LeadCategorySelector({
  leadId,
  category,
  onChanged,
}: LeadCategorySelectorProps) {
  const [display, setDisplay] = useState(category ?? '')
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)
  const [saving, setSaving] = useState(false)
  const [snack, setSnack] = useState<string | null>(null)

  useEffect(() => {
    setDisplay(category ?? '')
  }, [category, leadId])

  const label = formatLeadCategoryLabel(display) || '—'
  const current = String(display || '').trim().toLowerCase()
  const menuOpen = Boolean(anchorEl)

  const handlePick = async (next: 'residential' | 'commercial') => {
    setAnchorEl(null)
    if (next === current) return
    setSaving(true)
    try {
      const result = await commandCenterService.updateCategory(leadId, next)
      const saved = (result.lead_category || next) as 'residential' | 'commercial'
      setDisplay(saved)
      await onChanged?.(saved)
    } catch (err) {
      setSnack(err instanceof Error ? err.message : 'Could not save category.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <ButtonBase
        data-testid="lead-category-selector"
        aria-label={`Category: ${label}. Click to change.`}
        aria-haspopup="menu"
        aria-expanded={menuOpen ? 'true' : undefined}
        aria-controls={menuOpen ? 'lead-category-menu' : undefined}
        disabled={saving}
        onClick={(event) => setAnchorEl(event.currentTarget)}
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 0.25,
          maxWidth: '100%',
          justifyContent: 'flex-start',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <Typography
          data-testid="quick-stat-category-value"
          sx={{
            ...ccKpiValueSx,
            fontSize: '0.875rem',
            mt: 0.125,
            lineHeight: 1.25,
            minWidth: 0,
            overflowWrap: 'break-word',
            wordBreak: 'break-word',
          }}
        >
          {label}
        </Typography>
        <ArrowDropDownIcon sx={{ fontSize: '1.1rem', color: 'text.secondary', flexShrink: 0 }} />
      </ButtonBase>
      <Menu
        id="lead-category-menu"
        anchorEl={anchorEl}
        open={menuOpen}
        onClose={() => setAnchorEl(null)}
        data-testid="lead-category-menu"
        MenuListProps={{ sx: { cursor: 'auto' } }}
      >
        {OPTIONS.map((opt) => (
          <MenuItem
            key={opt}
            selected={opt === current}
            disabled={opt === current}
            onClick={() => {
              void handlePick(opt)
            }}
            data-testid={`lead-category-option-${opt}`}
            sx={{ cursor: 'pointer' }}
          >
            {formatLeadCategoryLabel(opt)}
          </MenuItem>
        ))}
      </Menu>
      <AppSnackbar
        open={Boolean(snack)}
        onClose={() => setSnack(null)}
        message={snack ?? ''}
        severity="error"
      />
    </>
  )
}

export default LeadCategorySelector
