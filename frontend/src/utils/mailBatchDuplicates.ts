/**
 * Prep-time mailing-address duplicate detection for staged mail batches.
 * Uses backend `mailing_dedupe_key` when present; otherwise mirrors
 * `owner_mailing_dedupe_key` street/city/state/zip normalization.
 */
import type { MailQueueItem } from '@/services/openLetterApi'

export type MailBatchDuplicateInfo = {
  duplicateItemIds: Set<number>
  duplicateExtraCount: number
  duplicateGroupCount: number
  keeperItemIds: Set<number>
  groupSizeByItemId: Map<number, number>
}

/** Keep in sync with backend `_STREET_ABBREV` / `_STREET_TYPE_SUFFIXES`. */
const STREET_ABBREV: Array<[RegExp, string]> = [
  [/\bnorth\b/g, 'n'],
  [/\bsouth\b/g, 's'],
  [/\beast\b/g, 'e'],
  [/\bwest\b/g, 'w'],
  [/\bstreet\b/g, 'st'],
  [/\bavenue\b/g, 'ave'],
  [/\bboulevard\b/g, 'blvd'],
  [/\bdrive\b/g, 'dr'],
  [/\broad\b/g, 'rd'],
  [/\blane\b/g, 'ln'],
  [/\bcourt\b/g, 'ct'],
  [/\bcircle\b/g, 'cir'],
  [/\bplace\b/g, 'pl'],
  [/\bterrace\b/g, 'ter'],
  [/\bparkway\b/g, 'pkwy'],
  [/\bapartment\b/g, 'apt'],
  [/\bsuite\b/g, 'ste'],
  [/\bunit\b/g, 'unit'],
  [/\bav\b/g, 'ave'],
  [/\bstr\b/g, 'st'],
]

const STREET_TYPE_SUFFIXES = new Set([
  'ave', 'st', 'blvd', 'dr', 'rd', 'ln', 'ct', 'cir', 'pl', 'ter', 'pkwy', 'way',
])

function normalizeAddressPart(value: string): string {
  let text = value.trim().toLowerCase()
  if (!text) return ''
  text = text.replace(/#\s*/g, 'apt ')
  text = text.replace(/[.,;:/\\]+/g, ' ')
  for (const [pattern, repl] of STREET_ABBREV) {
    text = text.replace(pattern, repl)
  }
  return text.replace(/\s+/g, ' ').trim()
}

function streetCoreForDedupe(streetNorm: string): string {
  const parts = streetNorm.split(' ').filter(Boolean)
  if (parts.length >= 2 && STREET_TYPE_SUFFIXES.has(parts[parts.length - 1])) {
    return parts.slice(0, -1).join(' ')
  }
  return streetNorm
}

function normalizeZip(value: string): string {
  return value.replace(/\D/g, '').slice(0, 5)
}

/** Fallback key matching backend `owner_mailing_dedupe_key` shape. */
export function fallbackMailingDedupeKey(item: MailQueueItem): string | null {
  const street = streetCoreForDedupe(normalizeAddressPart(item.mailing_address || ''))
  const city = normalizeAddressPart(item.mailing_city || '')
  const state = normalizeAddressPart(item.mailing_state || '')
  const zip = normalizeZip(item.mailing_zip || '')
  if (!street || !city || !state || !zip) return null
  return `${street}|${city}|${state}|${zip}`
}

function mailingKey(item: MailQueueItem): string | null {
  const fromApi = item.mailing_dedupe_key?.trim()
  if (fromApi) return fromApi
  return fallbackMailingDedupeKey(item)
}

/** Summarize duplicate mailing addresses in the staged batch. */
export function analyzeMailBatchDuplicates(items: MailQueueItem[]): MailBatchDuplicateInfo {
  const byKey = new Map<string, MailQueueItem[]>()
  for (const item of items) {
    const key = mailingKey(item)
    if (!key) continue
    const list = byKey.get(key)
    if (list) list.push(item)
    else byKey.set(key, [item])
  }

  const duplicateItemIds = new Set<number>()
  const keeperItemIds = new Set<number>()
  const groupSizeByItemId = new Map<number, number>()
  let duplicateExtraCount = 0
  let duplicateGroupCount = 0

  for (const group of byKey.values()) {
    if (group.length < 2) continue
    duplicateGroupCount += 1
    duplicateExtraCount += group.length - 1
    const sorted = [...group].sort((a, b) => a.id - b.id)
    keeperItemIds.add(sorted[0].id)
    for (const item of sorted) {
      duplicateItemIds.add(item.id)
      groupSizeByItemId.set(item.id, group.length)
    }
  }

  return {
    duplicateItemIds,
    duplicateExtraCount,
    duplicateGroupCount,
    keeperItemIds,
    groupSizeByItemId,
  }
}

/** Sort staged rows so duplicate mailboxes are adjacent (keeper first in group). */
export function sortStagedItemsByMailingDedupe(items: MailQueueItem[]): MailQueueItem[] {
  const keyOf = (item: MailQueueItem) => mailingKey(item) || `\0${item.id}`
  return [...items].sort((a, b) => {
    const ka = keyOf(a)
    const kb = keyOf(b)
    if (ka !== kb) return ka < kb ? -1 : 1
    return a.id - b.id
  })
}
