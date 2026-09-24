/**
 * Command Center unit-mix editor — wraps LeadUnitsEditor + PUT /units.
 */
import { useEffect, useState } from 'react'
import { Alert, Box, Button, CircularProgress } from '@mui/material'
import { leadService } from '@/services/leadApi'
import type { CommandCenterPayload } from '@/types'
import {
  LeadUnitsEditor,
  leadUnitDraftsFromApi,
  serializeLeadUnitDrafts,
  type LeadSubtype,
  type LeadUnitDraft,
} from '@/components/LeadUnitsEditor'

export interface LeadUnitsPanelProps {
  leadId: number
  commandCenterData: CommandCenterPayload
  onSaved?: () => void | Promise<void>
}

export function LeadUnitsPanel({
  leadId,
  commandCenterData,
  onSaved,
}: LeadUnitsPanelProps) {
  const [drafts, setDrafts] = useState<LeadUnitDraft[]>(() =>
    leadUnitDraftsFromApi(commandCenterData.lead_units),
  )
  const [subtype, setSubtype] = useState<LeadSubtype | ''>(
    (commandCenterData.lead_subtype as LeadSubtype | null | undefined) || '',
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    setDrafts(leadUnitDraftsFromApi(commandCenterData.lead_units))
    setSubtype((commandCenterData.lead_subtype as LeadSubtype | null | undefined) || '')
    setDirty(false)
    setError(null)
  }, [commandCenterData.lead_units, commandCenterData.lead_subtype, leadId])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      await leadService.replaceLeadUnits(leadId, {
        units: serializeLeadUnitDrafts(drafts),
        lead_subtype: subtype || null,
      })
      setDirty(false)
      await onSaved?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save units')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Box data-testid="lead-units-panel" sx={{ mt: 1, cursor: 'auto' }}>
      {error && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      <LeadUnitsEditor
        units={drafts}
        onChange={(next) => {
          setDrafts(next)
          setDirty(true)
        }}
        subtype={subtype}
        onSubtypeChange={(next) => {
          setSubtype(next)
          setDirty(true)
        }}
        disabled={saving}
        testIdPrefix="cc-lead-units"
      />
      {dirty && (
        <Button
          size="small"
          variant="contained"
          onClick={() => void handleSave()}
          disabled={saving}
          startIcon={saving ? <CircularProgress size={14} color="inherit" /> : undefined}
          sx={{ mt: 1, cursor: 'pointer' }}
          data-testid="cc-lead-units-save"
        >
          {saving ? 'Saving…' : 'Save unit mix'}
        </Button>
      )}
    </Box>
  )
}

export default LeadUnitsPanel
