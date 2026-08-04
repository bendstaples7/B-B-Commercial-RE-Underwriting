/**
 * LogActivityModal — floating non-modal panel for logging notes, calls, and emails.
 *
 * Command Center stays visible and interactive (no backdrop / scroll lock).
 * Desktop docks lower-right; mobile bottom-anchors ~65–70vh. Title bar is
 * draggable; Escape / Close / Cancel / Save dismiss.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Box,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  useMediaQuery,
  useTheme,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import DragIndicatorIcon from '@mui/icons-material/DragIndicator'
import type { SxProps, Theme } from '@mui/material/styles'
import { useQuery } from '@tanstack/react-query'
import type { LeadTask, LeadTimelineEntry } from '@/types'
import { contactService } from '@/services/api'
import { LogActivityForm, type LogCallSavedMeta } from '@/components/LogActivityForm'

export type ActivityLogType = 'note' | 'call' | 'email'

const TITLES: Record<ActivityLogType, string> = {
  note: 'Log Note',
  call: 'Log Call',
  email: 'Log Email',
}

export interface LogActivityModalProps {
  open: boolean
  activityType: ActivityLogType | null
  leadId: number
  openTasks?: LeadTask[]
  onClose: () => void
  onSaved: (
    entry: LeadTimelineEntry,
    activityType: ActivityLogType,
    meta?: LogCallSavedMeta,
  ) => void
}

interface PanelOffset {
  x: number
  y: number
}

function clampOffset(
  next: PanelOffset,
  currentOffset: PanelOffset,
  paper: HTMLElement | null,
): PanelOffset {
  if (!paper || typeof window === 'undefined') return next
  const rect = paper.getBoundingClientRect()
  const pad = 8
  // `rect` reflects `currentOffset` already applied via the paper's transform —
  // recover the un-offset base position so the *tentative* `next` offset is
  // clamped against the viewport, not against wherever the panel already sits.
  const baseLeft = rect.left - currentOffset.x
  const baseRight = rect.right - currentOffset.x
  const baseTop = rect.top - currentOffset.y
  const baseBottom = rect.bottom - currentOffset.y
  const minX = pad - baseLeft
  const maxX = window.innerWidth - pad - baseRight
  const minY = pad - baseTop
  const maxY = window.innerHeight - pad - baseBottom
  return {
    x: Math.min(Math.max(next.x, minX), maxX),
    y: Math.min(Math.max(next.y, minY), maxY),
  }
}

export function LogActivityModal({
  open,
  activityType,
  leadId,
  openTasks = [],
  onClose,
  onSaved,
}: LogActivityModalProps) {
  const theme = useTheme()
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'))
  const paperRef = useRef<HTMLDivElement | null>(null)
  const dragStart = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const [offset, setOffset] = useState<PanelOffset>({ x: 0, y: 0 })

  const { data: contacts = [], isLoading: contactsLoading } = useQuery({
    queryKey: ['propertyContacts', leadId],
    queryFn: () => contactService.getPropertyContacts(leadId),
    enabled: open && activityType != null && activityType !== 'note',
  })

  // Reset dock when panel closes or switches activity / lead.
  useEffect(() => {
    if (!open) {
      setOffset({ x: 0, y: 0 })
      return
    }
    setOffset({ x: 0, y: 0 })
  }, [open, activityType, leadId])

  // Capture opener focus on open; restore on close or unmount while open.
  useEffect(() => {
    if (!open) {
      const el = previouslyFocused.current
      previouslyFocused.current = null
      if (el && typeof el.focus === 'function') {
        el.focus()
      }
      return
    }
    previouslyFocused.current = document.activeElement as HTMLElement | null
    return () => {
      const el = previouslyFocused.current
      previouslyFocused.current = null
      if (el && typeof el.focus === 'function') {
        el.focus()
      }
    }
  }, [open])

  const onPointerMove = useCallback((e: PointerEvent) => {
    const start = dragStart.current
    if (!start) return
    const next = {
      x: start.ox + (e.clientX - start.x),
      y: start.oy + (e.clientY - start.y),
    }
    setOffset((current) => clampOffset(next, current, paperRef.current))
  }, [])

  const endDrag = useCallback(() => {
    dragStart.current = null
    document.documentElement.style.removeProperty('cursor')
    document.body.style.removeProperty('cursor')
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', endDrag)
    window.removeEventListener('pointercancel', endDrag)
  }, [onPointerMove])

  const startDrag = (e: React.PointerEvent) => {
    // Only primary button / touch; ignore interactive children (Close).
    if (e.button !== 0) return
    const target = e.target as HTMLElement
    if (target.closest('[data-testid="log-activity-close"]')) return
    e.preventDefault()
    dragStart.current = {
      x: e.clientX,
      y: e.clientY,
      ox: offset.x,
      oy: offset.y,
    }
    // Prefer `move` over `grab`/`grabbing` — on Windows those cursors often
    // render blank over light surfaces. Pin on document while dragging so the
    // pointer stays visible when it leaves the title bar.
    document.documentElement.style.cursor = 'move'
    document.body.style.cursor = 'move'
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', endDrag)
    window.addEventListener('pointercancel', endDrag)
  }

  useEffect(() => () => endDrag(), [endDrag])

  if (!activityType) return null

  const handleSaved = (entry: LeadTimelineEntry, meta?: LogCallSavedMeta) => {
    onSaved(entry, activityType, meta)
  }

  // Ignore backdrop / outside clicks — only Escape via onClose reason.
  const handleDialogClose = (
    _event: object,
    reason: 'backdropClick' | 'escapeKeyDown',
  ) => {
    if (reason === 'escapeKeyDown') onClose()
  }

  // Wide modal for all activity types — note/email now share the same
  // "next step" cadence layout as call, so all three need the wider frame.
  const contentSx: SxProps<Theme> = {
    // Explicit visible cursor — never inherit drag chrome from the title bar.
    cursor: 'auto',
    overflowY: 'auto',
    overflowX: 'hidden',
    pt: 1.5,
    pb: 1.5,
    maxHeight: isMobile ? 'calc(70vh - 56px)' : 'min(70vh, 640px)',
    '& .MuiFormControl-root': { overflow: 'visible' },
    '& input, & textarea, & [contenteditable="true"]': {
      cursor: 'text',
      caretColor: 'currentColor',
    },
  }

  const paperSx: SxProps<Theme> = {
    position: 'fixed',
    m: 0,
    cursor: 'auto',
    ...(isMobile
      ? {
          left: 8,
          right: 8,
          bottom: 8,
          top: 'auto',
          width: 'auto',
          maxWidth: '100%',
          maxHeight: '70vh',
        }
      : {
          right: 24,
          bottom: 24,
          left: 'auto',
          top: 'auto',
          width: 'min(980px, calc(100vw - 48px))',
          maxWidth: 980,
          maxHeight: 'min(80vh, 720px)',
        }),
    transform: `translate(${offset.x}px, ${offset.y}px)`,
    boxShadow: 8,
  }

  return (
    <Dialog
      open={open}
      onClose={handleDialogClose}
      hideBackdrop
      disableScrollLock
      disableEnforceFocus
      fullScreen={false}
      maxWidth={false}
      scroll="paper"
      aria-labelledby="log-activity-dialog-title"
      aria-modal={false}
      data-testid={`log-activity-modal-${activityType}`}
      sx={{
        pointerEvents: 'none',
        '& .MuiDialog-container': {
          pointerEvents: 'none',
          alignItems: 'flex-end',
          justifyContent: isMobile ? 'center' : 'flex-end',
        },
      }}
      PaperProps={{
        ref: paperRef,
        sx: { ...paperSx, pointerEvents: 'auto' },
        'data-testid': 'log-activity-panel-paper',
        role: 'dialog',
        'aria-modal': false,
      } as React.ComponentProps<typeof Dialog>['PaperProps']}
    >
      <DialogTitle
        id="log-activity-dialog-title"
        data-testid="log-activity-drag-handle"
        onPointerDown={isMobile ? undefined : startDrag}
        sx={{
          py: 1.25,
          px: 2,
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          // `move` stays visible on Windows; `grab`/`grabbing` often blank out.
          cursor: isMobile ? 'default' : 'move',
          userSelect: 'none',
          touchAction: isMobile ? 'auto' : 'none',
        }}
      >
        {!isMobile && (
          <DragIndicatorIcon fontSize="small" color="action" aria-hidden />
        )}
        <Box component="span" sx={{ flex: 1, minWidth: 0 }}>
          {TITLES[activityType]}
        </Box>
        {!isMobile && (offset.x !== 0 || offset.y !== 0) && (
          <IconButton
            aria-label="Reset panel position"
            onClick={() => setOffset({ x: 0, y: 0 })}
            size="small"
            data-testid="log-activity-reset-position"
          >
            <Box component="span" sx={{ typography: 'caption', px: 0.5 }}>
              Reset
            </Box>
          </IconButton>
        )}
        <IconButton
          aria-label="Close"
          onClick={onClose}
          size="small"
          data-testid="log-activity-close"
          sx={{ ml: 0.5 }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers sx={contentSx}>
        <LogActivityForm
          key={activityType}
          mode={activityType}
          leadId={leadId}
          contacts={contacts}
          contactsLoading={contactsLoading}
          openTasks={openTasks}
          onSaved={handleSaved}
          onCancel={onClose}
        />
      </DialogContent>
    </Dialog>
  )
}

export default LogActivityModal
