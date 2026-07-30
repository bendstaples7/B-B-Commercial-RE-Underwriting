/**
 * Shared score-breakdown formatting: signed modifiers, How we got to N, helps vs adjustments.
 */
import { getDimensionMeta } from '@/utils/scoreDimensionMeta'

/** Attribution-only keys — already counted elsewhere; exclude from additive story. */
export const ATTRIBUTION_ONLY_KEYS = new Set(['notes_keywords'])

/** Meta keys stored in score_details for UI math — not factor rows. */
export const META_SCORE_KEYS = new Set(['weighted_base'])

/** Lead-score modifiers applied after weighted base (not rubric factor dims). */
export const ADJUSTMENT_KEYS = new Set([
  'pipeline_stage_bonus',
  'hubspot_engagement',
  'timeline_engagement',
])

/** Short labels for the How-we-got-to-N arithmetic strip. */
const ADJUSTMENT_SHORT_LABELS: Record<string, string> = {
  pipeline_stage_bonus: 'pipeline',
  hubspot_engagement: 'CRM',
  timeline_engagement: 'outreach',
}

export function formatSignedPoints(points: number): string {
  const rounded = Math.round(points * 10) / 10
  const body = Number.isInteger(rounded) ? String(Math.abs(rounded)) : Math.abs(rounded).toFixed(1)
  if (rounded < 0) return `−${body}`
  if (rounded > 0) return `+${body}`
  return '0'
}

export function formatPointsPlain(points: number): string {
  const rounded = Math.round(points * 10) / 10
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1)
}

export type ScoreDetailPartition = {
  helps: Array<[string, number]>
  adjustments: Array<[string, number]>
  attribution: Array<[string, number]>
}

export function partitionScoreDetails(
  scoreDetails: Record<string, number>,
): ScoreDetailPartition {
  const helps: Array<[string, number]> = []
  const adjustments: Array<[string, number]> = []
  const attribution: Array<[string, number]> = []

  for (const [key, points] of Object.entries(scoreDetails ?? {})) {
    if (META_SCORE_KEYS.has(key)) continue
    if (ATTRIBUTION_ONLY_KEYS.has(key)) {
      attribution.push([key, points])
      continue
    }
    if (ADJUSTMENT_KEYS.has(key)) {
      adjustments.push([key, points])
      continue
    }
    helps.push([key, points])
  }

  helps.sort(([, a], [, b]) => b - a)
  adjustments.sort(([, a], [, b]) => a - b) // most negative first
  attribution.sort(([, a], [, b]) => b - a)

  return { helps, adjustments, attribution }
}

export type ScorePathSummary = {
  /** e.g. "How we got to 0" */
  title: string
  /** e.g. "Base ~48 − pipeline 15 − CRM 40 → 0 (floored at 0)" */
  equation: string
  caption: string
  baseApprox: number | null
  total: number
  floored: boolean
  capped: boolean
}

/**
 * Build "How we got to N" from score_details + total.
 * Prefers server `weighted_base` in score_details (single source with the engine).
 */
export function buildScorePathSummary(
  scoreDetails: Record<string, number>,
  totalScore: number,
): ScorePathSummary {
  const details = scoreDetails ?? {}
  const adjSum = [...ADJUSTMENT_KEYS].reduce((sum, key) => {
    const v = details[key]
    return sum + (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  }, 0)

  const total = Number.isFinite(totalScore) ? totalScore : 0
  const storedBase = details.weighted_base
  let baseApprox: number | null =
    typeof storedBase === 'number' && Number.isFinite(storedBase)
      ? Math.round(storedBase * 10) / 10
      : null

  if (baseApprox == null) {
    // Fallback when older score rows lack weighted_base — only when unclamped.
    const inferred = Math.round((total - adjSum) * 10) / 10
    const unclampedProbe = inferred + adjSum
    if (Math.abs(unclampedProbe - total) < 0.05) {
      baseApprox = inferred
    }
  }

  const unclamped =
    baseApprox != null ? Math.round((baseApprox + adjSum) * 100) / 100 : null
  const floored =
    (unclamped != null && unclamped < 0 && total <= 0)
    || (baseApprox == null && adjSum < 0 && total <= 0)
  const capped =
    (unclamped != null && unclamped > 100 && total >= 100)
    || (baseApprox == null && adjSum > 0 && total >= 100)

  const parts: string[] = []
  if (baseApprox != null) {
    parts.push(`Base ~${formatPointsPlain(baseApprox)}`)
  } else {
    parts.push('Base')
  }
  for (const key of ADJUSTMENT_KEYS) {
    const v = details[key]
    if (typeof v !== 'number' || !Number.isFinite(v) || v === 0) continue
    const short = ADJUSTMENT_SHORT_LABELS[key] ?? key
    const abs = formatPointsPlain(Math.abs(v))
    if (v < 0) {
      parts.push(`− ${short} ${abs}`)
    } else {
      parts.push(`+ ${short} ${abs}`)
    }
  }

  let arrow = `→ ${formatPointsPlain(Math.round(total))}`
  if (floored) arrow += ' (floored at 0)'
  else if (capped) arrow += ' (capped at 100)'

  return {
    title: `How we got to ${Math.round(total)}`,
    equation: `${parts.join(' ')} ${arrow}`,
    caption: 'Total = weighted factors + adjustments, then 0–100 clamp. Chips are evidence.',
    baseApprox,
    total,
    floored,
    capped,
  }
}

export function dimensionDisplayLabel(dimension: string, scoreVersion: string): string {
  return getDimensionMeta(dimension, scoreVersion).label
}
