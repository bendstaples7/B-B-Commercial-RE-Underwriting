/**
 * Tests for useQueueSelection — page-scoped selection for QueueTable.
 */
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useQueueSelection } from './useQueueSelection'

describe('useQueueSelection', () => {
  it('tracks selected ids via onSelectionChange', () => {
    const { result } = renderHook(() => useQueueSelection())

    act(() => {
      result.current.onSelectionChange([1, 2])
    })
    expect(result.current.selectedIds).toEqual([1, 2])

    act(() => {
      result.current.clearSelection()
    })
    expect(result.current.selectedIds).toEqual([])
  })

  it('clears selection when page changes via onPageChangeWithClear', () => {
    const { result } = renderHook(() => useQueueSelection())
    const pageHandler = vi.fn()

    act(() => {
      result.current.onSelectionChange([5, 6])
    })

    const wrapped = result.current.onPageChangeWithClear(pageHandler)
    act(() => {
      wrapped(2)
    })

    expect(result.current.selectedIds).toEqual([])
    expect(pageHandler).toHaveBeenCalledWith(2)
  })
})
