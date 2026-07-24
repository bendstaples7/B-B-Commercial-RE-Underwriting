import { Box, Link, Paper, Stack, Typography } from '@mui/material'
import PhoneOutlinedIcon from '@mui/icons-material/PhoneOutlined'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import LocalPostOfficeOutlinedIcon from '@mui/icons-material/LocalPostOfficeOutlined'
import type { CommandCenterPayload } from '@/types'
import {
  ccCardSx,
  ccMetaSx,
  ccRowTitleSx,
  ccSectionTitleSx,
} from '@/components/lead-detail/commandCenterChrome'
import { formatPhoneNumber, looksLikePhoneNumber, phoneTelHref } from '@/utils/phone'

export interface KeyContactCardProps {
  name: string | null
  commandCenterData: CommandCenterPayload
  sticky?: boolean
}

export type KeyContactChannel =
  | { kind: 'phone'; value: string }
  | { kind: 'email'; value: string }

/** Owner mailing only (no property-address fallback) — used for mail / skip-trace confidence. */
export function formatKeyContactMailing(data: CommandCenterPayload): string | null {
  const street = data.mailing_address?.trim() || ''
  const cityLine = [data.mailing_city, data.mailing_state, data.mailing_zip]
    .map((part) => part?.trim() || '')
    .filter(Boolean)
    .join(', ')
  if (!street && !cityLine) return null
  return [street, cityLine].filter(Boolean).join('\n')
}

function phoneKey(value: string): string {
  return value.replace(/\D/g, '')
}

function collectEmailSlotValues(data: CommandCenterPayload): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  const push = (raw: string) => {
    const trimmed = raw.trim()
    if (!trimmed) return
    const key = trimmed.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    out.push(trimmed)
  }
  if (data.emails?.length) {
    for (const e of data.emails) {
      if (typeof e === 'string') push(e)
    }
  }
  for (let slot = 1; slot <= 5; slot += 1) {
    const raw = data[`email_${slot}` as keyof CommandCenterPayload]
    if (typeof raw === 'string') push(raw)
  }
  return out
}

function primaryPhoneValue(data: CommandCenterPayload): string | null {
  if (data.phones?.[0]?.value?.trim()) {
    const v = data.phones[0].value.trim()
    if (looksLikePhoneNumber(v)) return v
  }
  for (let slot = 1; slot <= 7; slot += 1) {
    const raw = data[`phone_${slot}` as keyof CommandCenterPayload]
    if (typeof raw === 'string' && raw.trim() && looksLikePhoneNumber(raw)) {
      return raw.trim()
    }
  }
  return null
}

/**
 * Resolve Key Contact display channels.
 * Phone-shaped values misfiled in email_* render as phones (e.g. lead 634
 * email_1 = "(708) 222-6620"), then the first real email follows.
 */
export function resolveKeyContactChannels(data: CommandCenterPayload): KeyContactChannel[] {
  const channels: KeyContactChannel[] = []
  const seenPhones = new Set<string>()

  const primary = primaryPhoneValue(data)
  if (primary) {
    channels.push({ kind: 'phone', value: primary })
    seenPhones.add(phoneKey(primary))
  }

  let foundEmail = false
  for (const value of collectEmailSlotValues(data)) {
    if (looksLikePhoneNumber(value)) {
      const key = phoneKey(value)
      if (!seenPhones.has(key)) {
        seenPhones.add(key)
        channels.push({ kind: 'phone', value })
      }
      continue
    }
    if (!foundEmail) {
      foundEmail = true
      channels.push({ kind: 'email', value })
    }
  }

  return channels
}

/**
 * Persistent Key Contact card — name / phone / email / mailing (no avatar).
 * On lg+ this is the single outreach contact surface.
 */
export function KeyContactCard({ name, commandCenterData, sticky = false }: KeyContactCardProps) {
  const channels = resolveKeyContactChannels(commandCenterData)
  const mailing = formatKeyContactMailing(commandCenterData)
  const displayName = name?.trim() || 'No contact on file'
  const phoneChannels = channels.filter((c) => c.kind === 'phone')
  const emailChannels = channels.filter((c) => c.kind === 'email')

  return (
    <Paper
      data-testid="key-contact-card"
      elevation={0}
      sx={{
        ...ccCardSx,
        ...(sticky
          ? {
              position: 'sticky',
              top: 16,
              zIndex: 2,
            }
          : {}),
      }}
    >
      <Typography sx={ccSectionTitleSx} component="h2">
        Key Contact
      </Typography>
      <Typography sx={{ ...ccRowTitleSx, fontWeight: 600, mb: 1.5 }} data-testid="key-contact-name">
        {displayName}
      </Typography>
      <Stack spacing={1}>
        {phoneChannels.length === 0 ? (
          <Typography sx={ccMetaSx} data-testid="key-contact-phone-empty">
            No phone on file
          </Typography>
        ) : (
          phoneChannels.map((ch, idx) => (
            <Box
              key={`phone-${phoneKey(ch.value)}`}
              sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}
            >
              <PhoneOutlinedIcon sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0 }} />
              <Link
                href={phoneTelHref(ch.value)}
                underline="hover"
                sx={{ ...ccMetaSx, color: 'primary.main', fontSize: '0.9rem' }}
                data-testid={idx === 0 ? 'key-contact-phone' : `key-contact-phone-${idx + 1}`}
              >
                {formatPhoneNumber(ch.value)}
              </Link>
            </Box>
          ))
        )}
        {emailChannels.length === 0 ? (
          <Typography sx={ccMetaSx} data-testid="key-contact-email-empty">
            No email on file
          </Typography>
        ) : (
          emailChannels.map((ch, idx) => (
            <Box
              key={`email-${ch.value.toLowerCase()}`}
              sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}
            >
              <EmailOutlinedIcon sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0 }} />
              <Link
                href={`mailto:${ch.value}`}
                underline="hover"
                sx={{
                  ...ccMetaSx,
                  color: 'primary.main',
                  fontSize: '0.9rem',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
                data-testid={idx === 0 ? 'key-contact-email' : `key-contact-email-${idx + 1}`}
              >
                {ch.value}
              </Link>
            </Box>
          ))
        )}
        <Box
          sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, minWidth: 0 }}
          data-testid="key-contact-mailing-row"
        >
          <LocalPostOfficeOutlinedIcon
            sx={{ fontSize: 18, color: 'text.secondary', flexShrink: 0, mt: 0.15 }}
          />
          {mailing ? (
            <Typography
              sx={{
                ...ccMetaSx,
                fontSize: '0.9rem',
                color: 'text.primary',
                whiteSpace: 'pre-line',
              }}
              data-testid="key-contact-mailing"
            >
              {mailing}
            </Typography>
          ) : (
            <Typography sx={ccMetaSx} data-testid="key-contact-mailing-empty">
              No mailing address on file
            </Typography>
          )}
        </Box>
      </Stack>
    </Paper>
  )
}
