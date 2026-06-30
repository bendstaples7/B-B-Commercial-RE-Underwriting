import type { CommandCenterPayload, ContactMethod, OutreachContact } from '@/types'
import { formatPhoneNumber, phoneCopyText, phoneSmsHref, phoneTelHref } from '@/utils/phone'

const OUTREACH_ACTIONS_WITH_CONTACT = new Set([
  'follow_up_now',
  'ready_for_outreach',
  'mail_ready',
  'call_ready',
  'review_now',
  'nurture',
])

function firstFlatPhone(data: CommandCenterPayload): string | null {
  for (let slot = 1; slot <= 7; slot += 1) {
    const raw = data[`phone_${slot}` as keyof CommandCenterPayload]
    if (typeof raw === 'string' && raw.trim()) return raw.trim()
  }
  return null
}

function firstEmail(data: CommandCenterPayload): string | null {
  if (data.emails?.[0]) return data.emails[0]
  for (let slot = 1; slot <= 5; slot += 1) {
    const raw = data[`email_${slot}` as keyof CommandCenterPayload]
    if (typeof raw === 'string' && raw.trim()) return raw.trim()
  }
  return null
}

function formatMailLines(data: CommandCenterPayload): string[] {
  const lines: string[] = []
  if (data.mailing_address?.trim()) lines.push(data.mailing_address.trim())
  const locality = [data.mailing_city, data.mailing_state]
    .filter((p): p is string => Boolean(p?.trim()))
    .map((p) => p.trim())
    .join(', ')
  const zip = data.mailing_zip?.trim()
  const line2 = locality ? (zip ? `${locality} ${zip}` : locality) : zip ?? ''
  if (line2) lines.push(line2)
  if (lines.length > 0) return lines

  if (data.property_street?.trim()) lines.push(data.property_street.trim())
  const propLocality = [data.property_city, data.property_state]
    .filter((p): p is string => Boolean(p?.trim()))
    .map((p) => p.trim())
    .join(', ')
  const propZip = data.property_zip?.trim()
  const propLine2 = propLocality ? (propZip ? `${propLocality} ${propZip}` : propLocality) : propZip ?? ''
  if (propLine2) lines.push(propLine2)
  return lines
}

function buildPhoneContact(raw: string, channel: 'phone' | 'text'): OutreachContact {
  const display = formatPhoneNumber(raw)
  return {
    channel,
    label: channel === 'text' ? 'Text' : 'Call',
    value: raw.replace(/\D/g, '') || raw,
    display,
    href: channel === 'text' ? phoneSmsHref(raw) : phoneTelHref(raw),
  }
}

function buildEmailContact(email: string): OutreachContact {
  return {
    channel: 'email',
    label: 'Email',
    value: email,
    display: email,
    href: `mailto:${email}`,
  }
}

function buildMailContact(lines: string[]): OutreachContact | null {
  if (!lines.length) return null
  const display = lines.length === 1 ? lines[0] : lines.join(' — ')
  return {
    channel: 'direct_mail',
    label: 'Direct Mail',
    value: display,
    display,
    lines,
  }
}

function resolveFromMethod(
  data: CommandCenterPayload,
  method: ContactMethod,
): OutreachContact | null {
  if (method === 'phone' || method === 'text') {
    const raw = data.phones?.[0]?.value ?? firstFlatPhone(data)
    return raw ? buildPhoneContact(raw, method) : null
  }
  if (method === 'email') {
    const email = firstEmail(data)
    return email ? buildEmailContact(email) : null
  }
  if (method === 'direct_mail') {
    return buildMailContact(formatMailLines(data))
  }
  return null
}

/** Prefer API outreach_contact; fall back to command-center phone/email/address fields. */
export function resolveOutreachContactFromCommandCenter(
  data: CommandCenterPayload | null | undefined,
): OutreachContact | null {
  if (!data?.recommended_action) return null

  const action = data.recommended_action.value
  const method = data.recommended_action.recommended_contact_method
  if (!action || !method || !OUTREACH_ACTIONS_WITH_CONTACT.has(action)) {
    return data.recommended_action.outreach_contact ?? null
  }

  return data.recommended_action.outreach_contact ?? resolveFromMethod(data, method)
}

/** Default native task title from a resolved outreach contact. */
export function outreachContactTaskTitle(contact: OutreachContact | null | undefined): string {
  if (!contact) return 'Follow up'
  const display = contact.display || contact.value
  if (!display) return 'Follow up'
  return `${contact.label} ${display}`
}

/** Clipboard text for an outreach contact. */
export function outreachContactCopyText(contact: OutreachContact): string {
  if (contact.channel === 'phone' || contact.channel === 'text') {
    return phoneCopyText(contact.value)
  }
  if (contact.lines?.length) return contact.lines.join('\n')
  return contact.value
}
