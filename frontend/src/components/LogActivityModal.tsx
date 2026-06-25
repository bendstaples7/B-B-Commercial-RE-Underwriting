/**
 * LogActivityModal — modal wrapper for logging notes, calls, and emails on a lead.
 */
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import type { LeadTimelineEntry } from '@/types'
import { contactService } from '@/services/api'
import { LogNoteForm } from '@/components/LogNoteForm'
import { LogCallForm } from '@/components/LogCallForm'
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
  onClose: () => void
  onSaved: (entry: LeadTimelineEntry, activityType: ActivityLogType) => void
}

export function LogActivityModal({
  open,
  activityType,
  leadId,
  onClose,
  onSaved,
}: LogActivityModalProps) {
  const { data: contacts = [], isLoading: contactsLoading } = useQuery({
    queryKey: ['propertyContacts', leadId],
    queryFn: () => contactService.getPropertyContacts(leadId),
    enabled: open && activityType != null && activityType !== 'note',
  })

  if (!activityType) return null

  const handleSaved = (entry: LeadTimelineEntry) => {
    onSaved(entry, activityType)
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      aria-labelledby="log-activity-dialog-title"
      data-testid={`log-activity-modal-${activityType}`}
    >
      <DialogTitle id="log-activity-dialog-title">{TITLES[activityType]}</DialogTitle>
      <DialogContent>
        {activityType === 'note' && (
          <LogNoteForm leadId={leadId} onSaved={handleSaved} onCancel={onClose} />
        )}
        {activityType === 'call' && (
          <LogCallForm
            leadId={leadId}
            contacts={contacts}
            contactsLoading={contactsLoading}
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
