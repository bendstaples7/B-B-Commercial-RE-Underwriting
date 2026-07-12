import { useState } from 'react'
import { Box, Chip, IconButton, Link, Tooltip, Typography } from '@mui/material'
import PhoneIcon from '@mui/icons-material/Phone'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { formatPhoneNumber, phoneCopyText, phoneTelHref } from '@/utils/phone'
import { formatPhoneConfidence } from '@/utils/helpers'
import type { ContactPhone, LeadPhone } from '@/types'

export type PhoneRowPhone = LeadPhone | ContactPhone | string

export interface PhoneRowProps {
  phone: PhoneRowPhone
  /** Show label next to the number when not `other`. */
  showLabel?: boolean
  /** Dense caption sizing for sidebar; body for drawers/lists. */
  dense?: boolean
}

export function PhoneRow({ phone, showLabel = false, dense = true }: PhoneRowProps) {
  const [copied, setCopied] = useState(false)
  const value = typeof phone === 'string' ? phone : phone.value
  if (!value?.trim()) return null
  const label = typeof phone === 'string' ? undefined : phone.label
  const confidenceLabel =
    typeof phone === 'string' ? null : formatPhoneConfidence(phone.confidence_score, phone.notes)
  const displayPhone = formatPhoneNumber(value)
  const handleCopy = () => {
    void navigator.clipboard.writeText(phoneCopyText(value))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 0.5, flexWrap: 'wrap' }}>
      <PhoneIcon sx={{ fontSize: dense ? 13 : 16, color: 'text.secondary' }} />
      <Link
        href={phoneTelHref(value)}
        variant={dense ? 'caption' : 'body2'}
        underline="hover"
        onClick={(e) => e.stopPropagation()}
      >
        {displayPhone}
      </Link>
      {showLabel && label && label !== 'other' && (
        <Typography component="span" variant="caption" color="text.secondary">
          ({label})
        </Typography>
      )}
      {confidenceLabel && (
        <Tooltip title={confidenceLabel}>
          <Chip
            label={confidenceLabel}
            size="small"
            variant="outlined"
            sx={{ height: 18, fontSize: '0.65rem', maxWidth: 160 }}
            data-testid={`phone-confidence-${value}`}
          />
        </Tooltip>
      )}
      <Tooltip title={copied ? 'Copied!' : 'Copy'}>
        <IconButton
          size="small"
          onClick={(e) => {
            e.stopPropagation()
            handleCopy()
          }}
          sx={{ p: 0.25 }}
        >
          <ContentCopyIcon sx={{ fontSize: dense ? 11 : 14 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}
