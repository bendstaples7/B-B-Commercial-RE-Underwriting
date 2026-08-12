/**
 * Normalize leads.mailer_history (legacy string | JSON array | mixed) for UI.
 *
 * Prefer `mailer_history_summary` from the command-center API when present
 * (backend is the canonical normalizer). This module is the FE fallback for
 * raw `mailer_history` only.
 */

export type MailerHistorySource = 'olc' | 'imported' | 'timeline'

export interface MailerHistoryRow {
  id: string
  sent_at: string | null
  label: string
  creative: string | null
  template_name: string | null
  campaign_id: number | null
  olc_order_id: string | null
  address_feedback: string | null
  cancelled: boolean
  source: MailerHistorySource
}

export interface MailerHistorySummary {
  count: number
  last_sent_at: string | null
  healed_count?: number
  rows: MailerHistoryRow[]
}

const LEGACY_DATE_RE = /^(?<label>.*?),\s*(?<date>\d{1,2}\/\d{1,2}\/\d{2,4})\s*$/

function asEntries(raw: unknown): unknown[] {
  if (raw == null || raw === '' || (Array.isArray(raw) && raw.length === 0)) {
    return []
  }
  if (Array.isArray(raw)) return [...raw]
  return [raw]
}

/** Parse ISO or US slash dates for last-sent ordering. */
export function parseMailerSentAt(value: unknown): Date | null {
  if (value == null) return null
  const text = String(value).trim()
  if (!text) return null
  const iso = Date.parse(text)
  if (!Number.isNaN(iso)) return new Date(iso)
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec(text)
  if (m) {
    const month = Number(m[1])
    const day = Number(m[2])
    let year = Number(m[3])
    if (year < 100) year += 2000
    const d = new Date(year, month - 1, day)
    return Number.isNaN(d.getTime()) ? null : d
  }
  return null
}

/** Coerce API creative (string | preset dict | null) to a display string. */
export function creativeDisplayLabel(creative: unknown): string | null {
  if (creative == null) return null
  if (typeof creative === 'string') {
    const trimmed = creative.trim()
    return trimmed || null
  }
  if (typeof creative === 'object' && !Array.isArray(creative)) {
    const obj = creative as Record<string, unknown>
    for (const key of ['sender_display_name', 'label', 'olc_template_name'] as const) {
      const v = obj[key]
      if (typeof v === 'string' && v.trim()) return v.trim()
    }
    const name = [obj.first_name, obj.last_name]
      .filter((p): p is string => typeof p === 'string' && Boolean(p.trim()))
      .join(' ')
      .trim()
    return name || null
  }
  const text = String(creative).trim()
  return text || null
}

function normalizeOne(entry: unknown, idx: number): MailerHistoryRow | null {
  if (entry == null || entry === '') return null

  if (typeof entry === 'object' && !Array.isArray(entry)) {
    const obj = entry as Record<string, unknown>
    const templateName = obj.template_name != null ? String(obj.template_name) : null
    const creative = creativeDisplayLabel(obj.creative)
    const labelParts = [templateName, creative]
      .map((p) => (typeof p === 'string' ? p.trim() : p))
      .filter(Boolean)
    let label = labelParts.length ? labelParts.join(', ') : null
    if (!label && obj.olc_order_id) label = `OLC order ${obj.olc_order_id}`
    if (!label && obj.campaign_id != null) label = `Campaign ${obj.campaign_id}`
    if (!label && obj.address_feedback) label = `Address feedback: ${obj.address_feedback}`
    if (!label) label = 'Mailer'
    const rawSource = obj.source
    const source: MailerHistorySource =
      rawSource === 'timeline' || rawSource === 'olc' || rawSource === 'imported'
        ? rawSource
        : obj.campaign_id != null || obj.olc_order_id
          ? 'olc'
          : 'imported'
    return {
      id: `mail-${idx}`,
      sent_at: obj.sent_at != null ? String(obj.sent_at) : null,
      label,
      creative,
      template_name: templateName,
      campaign_id: typeof obj.campaign_id === 'number' ? obj.campaign_id : null,
      olc_order_id: obj.olc_order_id != null ? String(obj.olc_order_id) : null,
      address_feedback: obj.address_feedback != null ? String(obj.address_feedback) : null,
      cancelled: Boolean(obj.cancelled),
      source,
    }
  }

  const text = String(entry).trim()
  if (!text) return null
  const match = LEGACY_DATE_RE.exec(text)
  if (match?.groups) {
    return {
      id: `mail-${idx}`,
      sent_at: match.groups.date,
      label: match.groups.label.trim().replace(/,\s*$/, ''),
      creative: null,
      template_name: null,
      campaign_id: null,
      olc_order_id: null,
      address_feedback: null,
      cancelled: false,
      source: 'imported',
    }
  }
  return {
    id: `mail-${idx}`,
    sent_at: null,
    label: text,
    creative: null,
    template_name: null,
    campaign_id: null,
    olc_order_id: null,
    address_feedback: null,
    cancelled: false,
    source: 'imported',
  }
}

export function normalizeMailerHistory(raw: unknown): MailerHistoryRow[] {
  const rows: MailerHistoryRow[] = []
  asEntries(raw).forEach((entry, idx) => {
    const row = normalizeOne(entry, idx)
    if (row) rows.push(row)
  })
  return rows
}

export function mailerHistorySummary(raw: unknown): MailerHistorySummary {
  const rows = normalizeMailerHistory(raw)
  let lastSent: string | null = null
  let lastMs: number | null = null
  for (const row of rows) {
    if (!row.sent_at) continue
    const parsed = parseMailerSentAt(row.sent_at)
    if (parsed) {
      const ms = parsed.getTime()
      if (lastMs == null || ms > lastMs) {
        lastMs = ms
        lastSent = row.sent_at
      }
    } else if (lastSent == null) {
      lastSent = row.sent_at
    }
  }
  return { count: rows.length, last_sent_at: lastSent, rows }
}

/** Prefer API summary; fall back to client normalize of raw history. */
export function resolveMailerHistorySummary(
  summary: MailerHistorySummary | null | undefined,
  raw: unknown,
): MailerHistorySummary {
  if (summary && typeof summary.count === 'number' && Array.isArray(summary.rows)) {
    // API rows may still carry dict `creative` — coerce so React never gets an object child.
    return {
      ...summary,
      rows: summary.rows.map((row, idx) => {
        const creative = creativeDisplayLabel(row.creative)
        const templateName = row.template_name
        const labelFromParts = [templateName, creative].filter(Boolean).join(', ')
        const creativeWasNonString =
          row.creative != null && typeof row.creative !== 'string'
        const labelLooksLikeDict =
          typeof row.label === 'string'
          && /\{\s*['"]/.test(row.label)
        const preferRebuilt =
          (creativeWasNonString || labelLooksLikeDict) && Boolean(labelFromParts)
        return {
          ...row,
          id: row.id || `mail-${idx}`,
          creative,
          label: preferRebuilt ? labelFromParts : (row.label || labelFromParts || 'Mailer'),
        }
      }),
    }
  }
  return mailerHistorySummary(raw)
}
