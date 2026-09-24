/**
 * Command Center unit-mix editor — wraps LeadUnitsEditor + PUT /units.
 */
import { useEffect, useRef, useState } from 'react'
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
  const dirtyRef = useRef(false)
  const lastLeadIdRef = useRef(leadId)

  // Remount-safe sync from server: skip while the user has unsaved edits so
  // other Command Center mutations (which invalidate the same query) do not
  // wipe in-progress unit mix drafts.
  useEffect(() => {
    if (dirty) return
    setDrafts(leadUnitDraftsFromApi(commandCenterData.lead_units))
    setSubtype((commandCenterData.lead_subtype as LeadSubtype | null | undefined) || '')
    setError(null)
  }, [commandCenterData.lead_units, commandCenterData.lead_subtype, leadId, dirty])

  // Lead switch always resets drafts even if the prior lead was dirty.
  useEffect(() => {
    if (leadId !== lastLeadIdRef.current) {
      lastLeadIdRef.current = leadId
      dirtyRef.current = false
    } else if (dirtyRef.current) {
      return
    }
    setDrafts(leadUnitDraftsFromApi(commandCenterData.lead_units))
    setSubtype((commandCenterData.lead_subtype as LeadSubtype | null | undefined) || '')
    setDirty(false)
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- leadId boundary only
  }, [leadId])

  const handleSave = async () => {
    const saveLeadId = leadId
    const payload = {
      units: serializeLeadUnitDrafts(drafts),
      lead_subtype: subtype || null,
    }
    setSaving(true)
    setError(null)
    try {
      const result = await leadService.replaceLeadUnits(saveLeadId, payload)
      // Stale response after queue navigation must not overwrite the new lead.
      if (lastLeadIdRef.current !== saveLeadId) {
        return
      }
      setDrafts(leadUnitDraftsFromApi(result.lead_units))
      setSubtype((result.lead_subtype as LeadSubtype | null | undefined) || '')
      dirtyRef.current = false
      setDirty(false)
      await onSaved?.()
    } catch (err) {
      if (lastLeadIdRef.current !== saveLeadId) {
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to save units')
    } finally {
      if (lastLeadIdRef.current === saveLeadId) {
        setSaving(false)
      }
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
          dirtyRef.current = true
          setDirty(true)
        }}
        subtype={subtype}
        onSubtypeChange={(next) => {
          setSubtype(next)
          dirtyRef.current = true
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
