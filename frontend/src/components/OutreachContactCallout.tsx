/**
 * Outreach contact display — inline (Command Center) and compact (queues).
 * Bordered callout is queue-only; Command Center uses OutreachContactInline.
 */
import { useState } from 'react'
import {
  Box,
  IconButton,
  Link,
  Tooltip,
  Typography,
} from '@mui/material'
import PhoneIcon from '@mui/icons-material/Phone'
import EmailIcon from '@mui/icons-material/Email'
import SmsIcon from '@mui/icons-material/Sms'
import LocalPostOfficeIcon from '@mui/icons-material/LocalPostOffice'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import type { OutreachContact } from '@/types'
import { formatPhoneNumber, phoneCopyText } from '@/utils/phone'

export interface OutreachContactInlineProps {
  contact: OutreachContact | null | undefined
}

export interface OutreachContactCalloutProps {
  contact: OutreachContact | null | undefined
  /** Compact inline style for queue table sublines */
  compact?: boolean
}

function channelIcon(channel: OutreachContact['channel'], size: number) {
  const sx = { fontSize: size }
  switch (channel) {
    case 'phone':
      return <PhoneIcon sx={sx} />
    case 'text':
      return <SmsIcon sx={sx} />
    case 'email':
      return <EmailIcon sx={sx} />
    case 'direct_mail':
      return <LocalPostOfficeIcon sx={sx} />
    default:
      return null
  }
}

function copyValue(contact: OutreachContact): string {
  if (contact.channel === 'phone' || contact.channel === 'text') {
    return phoneCopyText(contact.value)
  }
  if (contact.lines?.length) {
    return contact.lines.join('\n')
  }
  return contact.value
}

const MISSING_CONTACT_MESSAGES: Record<OutreachContact['channel'], string> = {
  phone: 'No phone number on file for this lead.',
  text: 'No phone number on file for text outreach.',
  email: 'No email address on file for this lead.',
  direct_mail: 'No mailing address on file for this lead.',
}

export interface OutreachContactMissingHintProps {
  channel: OutreachContact['channel']
}

/** Shown when outreach channel is set but no contact value could be resolved. */
export function OutreachContactMissingHint({ channel }: OutreachContactMissingHintProps) {
  const message = MISSING_CONTACT_MESSAGES[channel]
  if (!message) return null

  return (
    <Typography
      variant="caption"
      color="warning.main"
      data-testid="outreach-contact-missing"
      sx={{ display: 'block', mt: 0.25 }}
    >
      {message}
    </Typography>
  )
}

function renderLink(contact: OutreachContact, compact: boolean) {
  const display =
    contact.channel === 'phone' || contact.channel === 'text'
      ? formatPhoneNumber(contact.display || contact.value)
      : contact.display || contact.value

  if (contact.channel === 'direct_mail' && contact.lines?.length) {
    return (
      <Box component="span" sx={{ display: 'block' }}>
        {contact.lines.map((line) => (
          <Typography
            key={line}
            component="span"
            variant={compact ? 'caption' : 'body2'}
            display="block"
            sx={{ fontWeight: compact ? 500 : 600, wordBreak: 'break-word' }}
          >
            {line}
          </Typography>
        ))}
      </Box>
    )
  }

  if (contact.href && (contact.channel === 'phone' || contact.channel === 'text')) {
    return (
      <Link
        href={contact.href}
        variant={compact ? 'caption' : 'body2'}
        underline="hover"
        sx={{ fontWeight: compact ? 500 : 600, wordBreak: 'break-all' }}
        data-testid="outreach-contact-link"
      >
        {display}
      </Link>
    )
  }

  if (contact.href && contact.channel === 'email') {
    return (
      <Link
        href={contact.href}
        variant={compact ? 'caption' : 'body2'}
        underline="hover"
        sx={{ fontWeight: compact ? 500 : 600, wordBreak: 'break-all' }}
        data-testid="outreach-contact-link"
      >
        {display}
      </Link>
    )
  }

  return (
    <Typography
      component="span"
      variant={compact ? 'caption' : 'body2'}
      sx={{ fontWeight: compact ? 500 : 600, wordBreak: 'break-word' }}
      data-testid="outreach-contact-value"
    >
      {display}
    </Typography>
  )
}

/** Inline contact for task rows and Recommended Action — no bordered box. */
export function OutreachContactInline({ contact }: OutreachContactInlineProps) {
  if (!contact) return null

  return (
    <Box
      data-testid="outreach-contact-inline"
      sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.25 }}
    >
      <Box sx={{ color: 'text.secondary', display: 'flex', flexShrink: 0 }}>
        {channelIcon(contact.channel, 14)}
      </Box>
      <Typography variant="caption" color="text.secondary" component="span">
        {contact.label}
      </Typography>
      {renderLink(contact, true)}
    </Box>
  )
}

/** Queue table subline (compact) or bordered callout — not for Command Center body. */
export function OutreachContactCallout({ contact, compact = false }: OutreachContactCalloutProps) {
  const [copied, setCopied] = useState(false)

  if (!contact) return null

  const handleCopy = async () => {
    await navigator.clipboard.writeText(copyValue(contact))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (compact) {
    return (
      <Box
        data-testid="outreach-contact-callout"
        sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, mt: 0.25 }}
      >
        <Box sx={{ color: 'text.secondary', mt: 0.15, flexShrink: 0 }}>
          {channelIcon(contact.channel, 14)}
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary" display="block">
            {contact.label}
          </Typography>
          {renderLink(contact, true)}
        </Box>
      </Box>
    )
  }

  return (
    <Box
      data-testid="outreach-contact-callout"
      sx={{
        mb: 2,
        p: 1.5,
        borderRadius: 1,
        bgcolor: 'action.hover',
        border: 1,
        borderColor: 'divider',
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
        <Box sx={{ color: 'primary.main', mt: 0.25, flexShrink: 0 }}>
          {channelIcon(contact.channel, 20)}
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="caption" color="text.secondary" display="block" gutterBottom>
            {contact.label}
          </Typography>
          {renderLink(contact, false)}
        </Box>
        <Tooltip title={copied ? 'Copied' : 'Copy'}>
          <IconButton
            size="small"
            onClick={handleCopy}
            aria-label="Copy contact"
            data-testid="outreach-contact-copy"
          >
            <ContentCopyIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  )
}

export default OutreachContactCallout
