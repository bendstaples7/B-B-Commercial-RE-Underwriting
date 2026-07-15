import { useId, useState } from 'react'
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Chip,
  IconButton,
  Link,
  Tooltip,
  Typography,
} from '@mui/material'
import PhoneIcon from '@mui/icons-material/Phone'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { formatPhoneNumber, phoneCopyText, phoneTelHref } from '@/utils/phone'
import { formatPhoneConfidence } from '@/utils/helpers'
import type { ContactPhone, LeadPhone } from '@/types'

export type PhoneRowPhone = LeadPhone | ContactPhone | string
export const HIGH_PHONE_CONFIDENCE = 80

export function isHighConfidencePhone(phone: PhoneRowPhone): boolean {
  return typeof phone !== 'string' && (phone.confidence_score ?? 50) >= HIGH_PHONE_CONFIDENCE
}

export function hasNonBlankPhones(phones: PhoneRowPhone[]): boolean {
  return phones.some((phone) => {
    const value = typeof phone === 'string' ? phone : phone.value
    return Boolean(value?.trim())
  })
}

export interface PhoneRowProps {
  phone: PhoneRowPhone
  /** Show label next to the number when not `other`. */
  showLabel?: boolean
  /** Dense caption sizing for sidebar; body for drawers/lists. */
  dense?: boolean
}

export interface PhoneListProps {
  phones: PhoneRowPhone[]
  showLabel?: boolean
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
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: dense ? 'flex-end' : 'flex-start',
        gap: 0.5,
        minWidth: 0,
        maxWidth: '100%',
        flexWrap: dense ? 'nowrap' : 'wrap',
      }}
    >
      <PhoneIcon
        sx={{ fontSize: dense ? 13 : 16, color: 'text.secondary', flexShrink: 0 }}
      />
      <Link
        href={phoneTelHref(value)}
        variant={dense ? 'caption' : 'body2'}
        underline="hover"
        onClick={(e) => e.stopPropagation()}
        noWrap
        sx={{ flexShrink: 0 }}
      >
        {displayPhone}
      </Link>
      {showLabel && label && label !== 'other' && (
        <Typography component="span" variant="caption" color="text.secondary" noWrap>
          ({label})
        </Typography>
      )}
      {confidenceLabel && (
        <Tooltip title={confidenceLabel}>
          <Chip
            label={confidenceLabel}
            size="small"
            variant="outlined"
            sx={{
              height: 18,
              fontSize: '0.65rem',
              maxWidth: dense ? 96 : 160,
              flexShrink: 1,
              minWidth: 0,
              '& .MuiChip-label': {
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                px: 0.75,
              },
            }}
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
          sx={{ p: 0.25, flexShrink: 0 }}
        >
          <ContentCopyIcon sx={{ fontSize: dense ? 11 : 14 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

export function PhoneList({ phones, showLabel = false, dense = true }: PhoneListProps) {
  const accordionId = useId()
  const nonBlankPhones = phones.filter((phone) => {
    const value = typeof phone === 'string' ? phone : phone.value
    return Boolean(value?.trim())
  })
  const highConfidence = nonBlankPhones.filter(isHighConfidencePhone)
  const lowerConfidence = nonBlankPhones.filter((phone) => !isHighConfidencePhone(phone))
  const shouldCollapseLower = highConfidence.length > 0 && lowerConfidence.length > 0
  const visiblePhones = shouldCollapseLower ? highConfidence : nonBlankPhones
  const keyFor = (phone: PhoneRowPhone, index: number) =>
    typeof phone === 'string' ? `${phone}-${index}` : phone.id ?? `${phone.value}-${index}`

  if (nonBlankPhones.length === 0) return null

  return (
    <Box data-testid="phone-list">
      {visiblePhones.map((phone, index) => (
        <PhoneRow
          key={keyFor(phone, index)}
          phone={phone}
          showLabel={showLabel}
          dense={dense}
        />
      ))}
      {shouldCollapseLower && (
        <Accordion
          disableGutters
          elevation={0}
          square
          data-testid="lower-confidence-phones"
          sx={{
            bgcolor: 'transparent',
            '&::before': { display: 'none' },
          }}
        >
          <AccordionSummary
            expandIcon={<ExpandMoreIcon fontSize="small" />}
            aria-controls={`${accordionId}-content`}
            id={`${accordionId}-header`}
            sx={{
              minHeight: 28,
              px: 0,
              justifyContent: dense ? 'flex-end' : 'flex-start',
              '& .MuiAccordionSummary-content': {
                my: 0.25,
                flexGrow: dense ? 0 : 1,
              },
              '&.Mui-expanded': { minHeight: 28 },
              '& .MuiAccordionSummary-content.Mui-expanded': { my: 0.25 },
            }}
          >
            <Typography variant="caption" color="text.secondary">
              Other phone numbers ({lowerConfidence.length})
            </Typography>
          </AccordionSummary>
          <AccordionDetails id={`${accordionId}-content`} sx={{ p: 0 }}>
            {lowerConfidence.map((phone, index) => (
              <PhoneRow
                key={keyFor(phone, index)}
                phone={phone}
                showLabel={showLabel}
                dense={dense}
              />
            ))}
          </AccordionDetails>
        </Accordion>
      )}
    </Box>
  )
}
