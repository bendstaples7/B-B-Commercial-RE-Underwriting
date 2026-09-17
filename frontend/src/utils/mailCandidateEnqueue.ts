/**
 * Ready-to-mail candidate enqueue helpers.
 * Keep in sync with backend MAX_MAIL_ENQUEUE_LEADS (mail_queue_service).
 */
export const MAIL_CANDIDATE_ENQUEUE_MAX = 1000

export const MAIL_ADD_COUNT_PRESETS = [25, 50, 100, 250, 500] as const

export function maxMailCandidateAddCount(candidateTotal: number): number {
  return Math.max(0, Math.min(candidateTotal, MAIL_CANDIDATE_ENQUEUE_MAX))
}

export function clampMailAddCount(raw: unknown, maxAddable: number): number {
  const parsed = typeof raw === 'number' ? raw : Number.parseInt(String(raw ?? ''), 10)
  if (!Number.isFinite(parsed) || maxAddable <= 0) return 0
  return Math.min(maxAddable, Math.max(1, Math.trunc(parsed)))
}

export function defaultMailAddCount(
  candidateTotal: number,
  neededForMinimum: number,
): number {
  const maxAddable = maxMailCandidateAddCount(candidateTotal)
  if (maxAddable <= 0) return 0
  if (neededForMinimum > 0) {
    return Math.min(neededForMinimum, maxAddable)
  }
  return Math.min(50, maxAddable)
}

/** Preset chip values under the enqueue cap, plus optional "to minimum". */
export function mailAddCountPresets(
  maxAddable: number,
  neededForMinimum: number,
): number[] {
  const capped = Math.min(Math.max(0, maxAddable), MAIL_CANDIDATE_ENQUEUE_MAX)
  if (capped <= 0) return []
  const values = new Set<number>()
  for (const preset of MAIL_ADD_COUNT_PRESETS) {
    if (preset <= capped) values.add(preset)
  }
  if (neededForMinimum > 0 && neededForMinimum <= capped) {
    values.add(neededForMinimum)
  }
  values.add(capped)
  return Array.from(values).sort((a, b) => a - b)
}
