/**
 * LeadBriefingPanel — on-demand five-bullet keep-in-mind briefing for Command Center.
 * Hydrates from persisted quick_briefing; Generate/Refresh revises instead of blank-slate.
 */
import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord'
import { commandCenterService } from '@/services/api'
import { ccCardSx, ccSectionTitleSx, ccMetaSx } from '@/components/lead-detail/commandCenterChrome'
import type { QuickBriefing } from '@/types'

export interface LeadBriefingPanelProps {
  leadId: number
  initialBriefing?: QuickBriefing | null
}

interface LeadBriefingState {
  lead_id?: number
  bullets: string[]
  generated_at: string
  updated_at?: string
  timeline_entries_used?: number
  open_tasks_used?: number
  mode?: 'create' | 'revise'
}

function formatTimestamp(iso: string | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function toState(briefing: QuickBriefing | LeadBriefingState | null | undefined, leadId: number): LeadBriefingState | null {
  if (!briefing?.bullets?.length) return null
  return {
    lead_id: leadId,
    bullets: briefing.bullets,
    generated_at: briefing.generated_at,
    updated_at: briefing.updated_at,
    timeline_entries_used: briefing.timeline_entries_used,
    open_tasks_used: briefing.open_tasks_used,
    mode: briefing.mode,
  }
}

export function LeadBriefingPanel({ leadId, initialBriefing = null }: LeadBriefingPanelProps) {
  const [briefing, setBriefing] = useState<LeadBriefingState | null>(
    () => toState(initialBriefing, leadId),
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const leadIdRef = useRef(leadId)
  leadIdRef.current = leadId

  useEffect(() => {
    // Reset request UI when navigating between leads so a stale Generate cannot
    // leave the new lead's CTA permanently disabled.
    setLoading(false)
    setError(null)
    setBriefing((prev) => {
      const next = toState(initialBriefing, leadId)
      if (!next) {
        return prev?.lead_id === leadId ? prev : null
      }
      if (!prev || prev.lead_id !== leadId) {
        return next
      }
      // Keep a fresher local Generate/Refresh result over a stale CC snapshot
      const prevTs = Date.parse(prev.updated_at || prev.generated_at || '')
      const nextTs = Date.parse(next.updated_at || next.generated_at || '')
      if (Number.isFinite(prevTs) && Number.isFinite(nextTs) && prevTs > nextTs) {
        return prev
      }
      return next
    })
  }, [leadId, initialBriefing])

  const handleGenerate = async () => {
    const requestLeadId = leadId
    setLoading(true)
    setError(null)
    try {
      const result = await commandCenterService.generateBriefing(requestLeadId)
      if (requestLeadId !== leadIdRef.current) return
      setBriefing(toState(result, requestLeadId))
    } catch (err: unknown) {
      if (requestLeadId !== leadIdRef.current) return
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message
        || (err instanceof Error ? err.message : null)
        || 'Could not generate briefing'
      setError(message)
    } finally {
      if (requestLeadId === leadIdRef.current) {
        setLoading(false)
      }
    }
  }

  const stamp = formatTimestamp(briefing?.updated_at || briefing?.generated_at)
  const hasSaved = Boolean(briefing?.bullets?.length)
  const modeLabel = briefing?.mode === 'revise' ? 'Updated' : 'Generated'

  return (
    <Paper sx={{ ...ccCardSx, mb: 2 }} data-testid="lead-briefing-panel">
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        spacing={1}
        sx={{ mb: briefing || error ? 1 : 0 }}
      >
        <Box>
          <Typography sx={{ ...ccSectionTitleSx, mb: 0.25 }}>
            Quick briefing
          </Typography>
          <Typography sx={ccMetaSx}>
            {stamp
              ? `${modeLabel} ${stamp}`
              : 'Five keep-in-mind bullets from tasks and activity'}
          </Typography>
        </Box>
        <Button
          size="small"
          variant={hasSaved ? 'outlined' : 'contained'}
          onClick={() => { void handleGenerate() }}
          disabled={loading}
          startIcon={
            loading
              ? <CircularProgress size={14} color="inherit" />
              : <AutoAwesomeIcon fontSize="small" />
          }
          data-testid="lead-briefing-generate"
          sx={{ flexShrink: 0, textTransform: 'none' }}
        >
          {loading ? (hasSaved ? 'Updating…' : 'Generating…') : hasSaved ? 'Refresh' : 'Generate'}
        </Button>
      </Stack>

      {error && (
        <Alert severity="warning" sx={{ mt: 1 }} data-testid="lead-briefing-error">
          {error}
        </Alert>
      )}

      {briefing?.bullets?.length ? (
        <List dense disablePadding sx={{ mt: 0.5 }} data-testid="lead-briefing-bullets">
          {briefing.bullets.map((bullet, idx) => (
            <ListItem
              key={`${idx}-${bullet.slice(0, 24)}`}
              alignItems="flex-start"
              disableGutters
              sx={{ py: 0.35 }}
              data-testid={`lead-briefing-bullet-${idx}`}
            >
              <ListItemIcon sx={{ minWidth: 22, mt: 0.55 }}>
                <FiberManualRecordIcon sx={{ fontSize: 8, color: 'text.secondary' }} />
              </ListItemIcon>
              <ListItemText
                primary={bullet}
                primaryTypographyProps={{
                  variant: 'body2',
                  sx: { lineHeight: 1.35, color: 'text.primary' },
                }}
              />
            </ListItem>
          ))}
        </List>
      ) : null}
    </Paper>
  )
}

export default LeadBriefingPanel
