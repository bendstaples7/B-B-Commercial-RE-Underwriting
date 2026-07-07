import type { ProspectCandidate, ProspectCandidateSignal } from '@/types'
import { formatDate } from '@/utils/formatters'

export const PROSPECT_MOTIVATION_CAP = 25
export const PROSPECT_MIN_MOTIVATION_PCT = 60

/** Recency decay for violations, 311 complaints, and vacant-building signals. */
export const RECENCY_DECAY_BUCKETS = [
  { maxDays: 90, pct: 100 },
  { maxDays: 365, pct: 75 },
  { maxDays: 730, pct: 50 },
  { maxDays: Infinity, pct: 25 },
] as const

export const PROSPECT_SIGNAL_LABELS: Record<string, string> = {
  TAX_SCAVENGER_SALE: 'Scavenger tax sale',
  TAX_ANNUAL_SALE: 'Annual tax sale',
  CHICAGO_SCOFFLAW: 'Chicago scofflaw',
  BUILDING_VIOLATION: 'Building violation',
  BUILDING_VIOLATION_SEVERE: 'Severe building violation',
  VACANT_BUILDING: 'Vacant / abandoned building',
  FORECLOSURE_AUCTION: 'Sheriff foreclosure auction',
  BUILDING_COMPLAINT: '311 building complaint',
}

/** Date fields from Socrata / feed rows, in display priority order. */
const EVIDENCE_DATE_FIELDS: { key: string; label: string }[] = [
  { key: 'violation_date', label: 'Issued' },
  { key: 'date_issued', label: 'Issued' },
  { key: 'created_date', label: 'Opened' },
  { key: 'auction_date', label: 'Auction' },
  { key: 'tax_sale_year', label: 'Tax sale year' },
]

export function prospectSignalLabel(signal: ProspectCandidateSignal): string {
  return signal.label ?? PROSPECT_SIGNAL_LABELS[signal.signal_type] ?? signal.signal_type
}

export function formatProspectMotivationPct(candidate: ProspectCandidate): string {
  let pct = candidate.motivation_pct
  if ((pct == null || Number.isNaN(pct)) && candidate.motivation_score != null) {
    pct = Math.round((candidate.motivation_score / PROSPECT_MOTIVATION_CAP) * 1000) / 10
  }
  if (pct == null || Number.isNaN(pct)) return '—'
  return `${pct.toFixed(pct % 1 === 0 ? 0 : 1)}%`
}

function evidenceText(evidence: Record<string, unknown>, key: string): string | null {
  const value = evidence[key]
  if (typeof value === 'string' && value.trim()) return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return null
}

export function formatEvidenceDate(evidence?: Record<string, unknown>): string | null {
  if (!evidence) return null
  const skipKeys = new Set<string>()
  if (evidenceText(evidence, 'case_number') && evidenceText(evidence, 'auction_date')) {
    skipKeys.add('auction_date')
  }
  for (const { key, label } of EVIDENCE_DATE_FIELDS) {
    if (skipKeys.has(key)) continue
    const raw = evidenceText(evidence, key)
    if (!raw) continue
    if (key === 'tax_sale_year') return `${label} ${raw}`
    const formatted = formatDate(raw)
    if (formatted === '—') continue
    return `${label} ${formatted}`
  }
  return null
}

/** Human-readable evidence lines for the motivation detail drawer. */
export function formatEvidenceLines(evidence?: Record<string, unknown>): string[] {
  if (!evidence) return []
  const lines: string[] = []

  const violationCode = evidenceText(evidence, 'violation_code')
  const violationDesc = evidenceText(evidence, 'violation_description')
  if (violationCode && violationDesc) {
    lines.push(`${violationCode}: ${violationDesc}`)
  } else if (violationDesc ?? violationCode) {
    lines.push(violationDesc ?? violationCode!)
  }

  const srType = evidenceText(evidence, 'sr_type')
  if (srType) lines.push(srType)

  const caseNumber = evidenceText(evidence, 'case_number')
  const auctionDate = evidenceText(evidence, 'auction_date')
  if (caseNumber) {
    lines.push(
      auctionDate
        ? `Case ${caseNumber} · auction ${formatDate(auctionDate)}`
        : `Case ${caseNumber}`,
    )
  }

  const address = evidenceText(evidence, 'address') ?? evidenceText(evidence, 'property_street')
  if (address && !violationCode && !violationDesc && !srType && !caseNumber) {
    lines.push(address)
  }

  const status = evidenceText(evidence, 'status')
  if (status && !violationCode && !violationDesc) lines.push(status)

  const issued = formatEvidenceDate(evidence)
  if (issued) lines.push(issued)

  return lines
}

/** @deprecated Prefer formatEvidenceLines — returns first line only. */
export function formatEvidenceSnippet(evidence?: Record<string, unknown>): string | null {
  const lines = formatEvidenceLines(evidence)
  return lines.length ? lines[0] : null
}

export function formatRecencyNote(signal: ProspectCandidateSignal): string | null {
  const multiplier = signal.recency_multiplier
  if (multiplier == null || multiplier >= 1) return null
  const pct = Math.round(multiplier * 100)
  const base = signal.base_points
  if (base != null) {
    return `${pct}% recency weight (${base} base pts)`
  }
  return `${pct}% recency weight`
}

export function formatSignalPoints(signal: ProspectCandidateSignal): string {
  const pts = signal.points
  if (pts % 1 === 0) return `+${pts}`
  return `+${pts.toFixed(1)}`
}

export function sortedProspectSignals(candidate: ProspectCandidate): ProspectCandidateSignal[] {
  return [...(candidate.signals ?? [])].sort((a, b) => b.points - a.points)
}

export function motivationSeverityColor(severity: string): 'error' | 'warning' | 'default' {
  if (severity === 'high') return 'error'
  if (severity === 'medium') return 'warning'
  return 'default'
}

type ProspectAddressFields = Pick<
  ProspectCandidate,
  'property_street' | 'property_city' | 'property_state'
>

export function formatProspectAddressLines(
  row: ProspectAddressFields,
): { primary: string; secondary: string | null } {
  const secondary = [row.property_city, row.property_state].filter(Boolean).join(', ')
  return {
    primary: row.property_street || '—',
    secondary: secondary || null,
  }
}

export function formatProspectAddress(row: ProspectAddressFields): string {
  const street = row.property_street?.trim()
  const cityState = [row.property_city, row.property_state].filter(Boolean).join(', ')
  if (street && cityState) return `${street}, ${cityState}`
  return street || cityState || '—'
}
