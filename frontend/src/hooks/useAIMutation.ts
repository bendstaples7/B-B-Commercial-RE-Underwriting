/**
 * useAIMutation — wraps useMutation for long-running AI fetch operations.
 *
 * Encapsulates:
 *   - The mutation itself (delegated to the caller via mutationFn)
 *   - Cycling progress labels (changes every 10s while pending)
 *   - Inline status state (success/warning/error message shown after completion)
 *
 * IMPORTANT: Button disabled/loading state is driven directly from
 * mutation.isPending — never mirrored into local useState. This prevents
 * the race condition where a useEffect resets local state in the same render
 * that isPending is still false (TanStack Query v5 transitions isPending
 * asynchronously on the next render after mutate() is called).
 *
 * Usage:
 *   const { mutation, labelIdx, labels, status, setStatus, handleFetch } =
 *     useAIMutation({
 *       mutationFn: () => multifamilyService.fetchSaleCompsAI(dealId),
 *       labels: ['Searching…', 'Analyzing…', 'Almost done…'],
 *       onSuccess: (result, invalidate) => {
 *         invalidate()
 *         setStatus(result.added === 0
 *           ? { message: 'No comps found.', severity: 'warning' }
 *           : { message: result.message, severity: 'success' })
 *       },
 *     })
 *
 *   // In JSX:
 *   <Button disabled={mutation.isPending} onClick={handleFetch}>
 *     {mutation.isPending ? labels[labelIdx] : 'Fetch Comps'}
 *   </Button>
 *   <Collapse in={!!status}>
 *     {status && <Alert severity={status.severity}>{status.message}</Alert>}
 *   </Collapse>
 */
import { useState, useEffect } from 'react'
import { useMutation, useQueryClient, MutationFunction } from '@tanstack/react-query'

export type AIStatus = {
  message: string
  severity: 'success' | 'error' | 'warning' | 'info'
} | null

interface UseAIMutationOptions<TData> {
  /** The async function that performs the AI fetch. */
  mutationFn: MutationFunction<TData>
  /** Labels cycled every 10s while the mutation is pending. */
  labels: string[]
  /** Query keys to invalidate on success. */
  invalidateKeys?: unknown[][]
  /** Called on success. Use setStatus to show a result message. */
  onSuccess?: (data: TData, setStatus: (s: AIStatus) => void) => void
  /** Called on error. Defaults to showing the error message. */
  onError?: (err: Error, setStatus: (s: AIStatus) => void) => void
}

interface UseAIMutationResult<TData> {
  /** The underlying TanStack Query mutation. Drive button state from mutation.isPending. */
  mutation: ReturnType<typeof useMutation<TData, Error>>
  /** Current index into the labels array. */
  labelIdx: number
  /** The labels array passed in (for convenience). */
  labels: string[]
  /** Current inline status message. Set to null to dismiss. */
  status: AIStatus
  setStatus: (s: AIStatus) => void
  /** Click handler — clears status and fires the mutation. */
  handleFetch: () => void
}

export function useAIMutation<TData>({
  mutationFn,
  labels,
  invalidateKeys = [],
  onSuccess,
  onError,
}: UseAIMutationOptions<TData>): UseAIMutationResult<TData> {
  const queryClient = useQueryClient()
  const [labelIdx, setLabelIdx] = useState(0)
  const [status, setStatus] = useState<AIStatus>(null)

  const mutation = useMutation<TData, Error>({
    mutationFn,
    onSuccess: (data) => {
      // Invalidate all provided query keys
      for (const key of invalidateKeys) {
        queryClient.invalidateQueries({ queryKey: key })
      }
      if (onSuccess) {
        onSuccess(data, setStatus)
      }
    },
    onError: (err) => {
      if (onError) {
        onError(err, setStatus)
      } else {
        setStatus({ message: err.message ?? 'An error occurred', severity: 'error' })
      }
    },
  })

  // Cycle labels while pending. Driven directly from mutation.isPending —
  // no intermediate useState mirror. labels.length is stable (static array).
  useEffect(() => {
    if (!mutation.isPending) {
      setLabelIdx(0)
      return
    }
    const labelsLen = labels.length
    const id = setInterval(() => {
      setLabelIdx((i) => (i + 1) % labelsLen)
    }, 10_000)
    return () => clearInterval(id)
  }, [mutation.isPending, labels.length])

  const handleFetch = () => {
    setStatus(null)
    // mutationFn takes no arguments for AI fetch operations
    ;(mutation.mutate as () => void)()
  }

  return { mutation, labelIdx, labels, status, setStatus, handleFetch }
}
