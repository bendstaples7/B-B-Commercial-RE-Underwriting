/**
 * Shared React Query options for work-queue list fetches.
 *
 * `queueListQueryDefaults` uses `keepPreviousData` so page/filter key changes
 * keep the prior page visible. Consumers MUST gate mutations, selection, and
 * totals on `isPlaceholderData` (or disable interaction) while placeholder
 * data is shown — otherwise users act on stale rows.
 *
 * Card / mutation-heavy queues (e.g. Missing Property Match) should use
 * `queueListRefetchDefaults` only — do not keep previous page data.
 */
import { keepPreviousData } from '@tanstack/react-query'
import type { SxProps, Theme } from '@mui/material'

export const queueListRefetchDefaults = {
  refetchInterval: 60_000,
  refetchIntervalInBackground: false,
} as const

export const queueListQueryDefaults = {
  ...queueListRefetchDefaults,
  placeholderData: keepPreviousData,
} as const

/** Dim + block interaction while showing placeholder rows from a prior query key. */
export function queuePlaceholderTableSx(isPlaceholderFetching: boolean): SxProps<Theme> {
  return {
    opacity: isPlaceholderFetching ? 0.6 : 1,
    transition: 'opacity 0.15s',
    ...(isPlaceholderFetching ? { pointerEvents: 'none' } : {}),
  }
}
