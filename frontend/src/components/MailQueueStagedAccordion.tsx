import React, { useEffect, useState } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { MailQueueItem } from '@/services/openLetterApi'
import { MailQueueStagedTable } from './MailQueueStagedTable'

export interface MailQueueStagedAccordionProps {
  items: MailQueueItem[]
  emptyMessage?: string
}

function formatAddressPreview(item: MailQueueItem): string {
  const parts = [item.mailing_address, item.mailing_city, item.mailing_state, item.mailing_zip]
    .filter(Boolean)
  if (parts.length > 0) return parts.join(', ')
  return item.property_street || `Lead #${item.lead_id}`
}

export const MailQueueStagedAccordion: React.FC<MailQueueStagedAccordionProps> = ({
  items,
  emptyMessage,
}) => {
  const [expanded, setExpanded] = useState(items.length === 0)

  useEffect(() => {
    if (items.length === 0) {
      setExpanded(true)
    }
  }, [items.length])

  const preview = items.length > 0 ? formatAddressPreview(items[0]) : null

  return (
    <Accordion
      expanded={expanded}
      onChange={(_event, isExpanded) => setExpanded(isExpanded)}
      disableGutters
      slotProps={{ transition: { unmountOnExit: true } }}
      data-testid="mail-queue-staged-accordion"
      sx={{ mb: 2 }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="h6" component="span" sx={{ fontSize: '1.125rem' }}>
          Staged for next batch ({items.length})
        </Typography>
        {!expanded && preview && items.length > 0 && (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ ml: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          >
            {preview}
            {items.length > 1 ? ` · +${items.length - 1} more` : ''}
          </Typography>
        )}
      </AccordionSummary>
      <AccordionDetails sx={{ p: 0 }}>
        <MailQueueStagedTable items={items} emptyMessage={emptyMessage} />
      </AccordionDetails>
    </Accordion>
  )
}
