/**
 * Prep-time mailing-address duplicate detection for staged mail batches.
 * Uses backend `mailing_dedupe_key` when present (same as submit-time dedupe).
 */
import type { MailQueueItem } from '@/services/openLetterApi'

export type MailBatchDuplicateInfo = {
  duplicateItemIds: Set<number>
  duplicateExtraCount: number
  duplicateGroupCount: number
  keeperItemIds: Set<number>
  groupSizeByItemId: Map<number, number>
}

function mailingKey(item: MailQueueItem): string | null {
  const fromApi = item.mailing_dedupe_key?.trim()
  if (fromApi) return fromApi
  const street = (item.mailing_address || '').trim().toLowerCase()
  const city = (item.mailing_city || '').trim().toLowerCase()
  const state = (item.mailing_state || '').trim().toLowerCase()
  const zip = (item.mailing_zip || '').replace(/\D/g, '').slice(0, 5)
  if (!street || !city || !state || !zip) return null
  return `${street}|${city}|${state}|${zip}`
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
