/**
 * LogActivityModal — modal wrapper for logging notes, calls, and emails on a lead.
 */
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import type { LeadTask, LeadTimelineEntry } from '@/types'
import { contactService } from '@/services/api'
import { LogNoteForm } from '@/components/LogNoteForm'
import { LogCallForm, type LogCallSavedMeta } from '@/components/LogCallForm'
import { LogEmailForm } from '@/components/LogEmailForm'

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

export function LogActivityModal({
  open,
  activityType,
  leadId,
  openTasks = [],
  onClose,
  onSaved,
}: LogActivityModalProps) {
  const { data: contacts = [], isLoading: contactsLoading } = useQuery({
    queryKey: ['propertyContacts', leadId],
    queryFn: () => contactService.getPropertyContacts(leadId),
    enabled: open && activityType != null && activityType !== 'note',
  })

  if (!activityType) return null

  const handleSaved = (entry: LeadTimelineEntry, meta?: LogCallSavedMeta) => {
    onSaved(entry, activityType, meta)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      scroll="paper"
      aria-labelledby="log-activity-dialog-title"
      data-testid={`log-activity-modal-${activityType}`}
    >
      <DialogTitle id="log-activity-dialog-title">{TITLES[activityType]}</DialogTitle>
      <DialogContent
        dividers
        sx={{
          overflowY: 'auto',
          maxHeight: 'min(80vh, 720px)',
          pt: 2,
          '& .MuiFormControl-root': { overflow: 'visible' },
        }}
      >
        {activityType === 'note' && (
          <LogNoteForm leadId={leadId} onSaved={handleSaved} onCancel={onClose} />
        )}
        {activityType === 'call' && (
          <LogCallForm
            leadId={leadId}
            contacts={contacts}
            contactsLoading={contactsLoading}
            openTasks={openTasks}
            onSaved={handleSaved}
            onCancel={onClose}
          />
        )}
        {activityType === 'email' && (
          <LogEmailForm
            leadId={leadId}
            contacts={contacts}
            contactsLoading={contactsLoading}
            onSaved={handleSaved}
            onCancel={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

export default LogActivityModal
