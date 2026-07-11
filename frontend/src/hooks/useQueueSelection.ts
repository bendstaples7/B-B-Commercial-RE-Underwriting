/**
 * Shared selection state for QueueTable work queues.
 * Clears selection when the page changes so checkboxes stay page-scoped.
 */
import { useCallback, useState } from 'react'

export function useQueueSelection() {
  const [selectedIds, setSelectedIds] = useState<number[]>([])

  const clearSelection = useCallback(() => {
    setSelectedIds([])
  }, [])

  /** Clear selection, then run the queue's page handler (clamp / setPage). */
  const onPageChangeWithClear = useCallback(
    (handler: (page: number) => void) => (newPage: number) => {
      setSelectedIds([])
      handler(newPage)
    },
    [],
  )

  return {
    selectedIds,
    onSelectionChange: setSelectedIds,
    clearSelection,
    onPageChangeWithClear,
  }
}
