/**
 * Shared bulk (and matching row) actions for QueueTable work queues.
 *
 * Queue pages compose via resolveBulkActions([...keys], ctx) — do not
 * reimplement enqueue / suppress / create-task / reactivate handlers per queue.
 */
import PostAddIcon from '@mui/icons-material/PostAdd'
import type { QueryClient } from '@tanstack/react-query'
import openLetterService from '@/services/openLetterApi'
import { bulkActionService, commandCenterService } from '@/services/api'
import {
  formatEnqueueSummary,
  type EnqueueCounts,
} from '@/utils/formatEnqueueSummary'
import type { BulkActionResult } from '@/types'
import type { BulkAction, RowAction } from './QueueTable'

export type QueueBulkActionKey =
  | 'add_to_mail_batch'
  | 'create_task'
  | 'suppress'
  | 'reactivate'

export interface QueueBulkActionContext {
  queryClient: QueryClient
  /** Primary queue query key prefix, e.g. 'queue-todays-action'. */
  queryKey: string
  extraQueryKeys?: string[]
  onAfterAction?: () => void
  /** Optional feedback hook (e.g. Ready to Mail snackbar). */
  onEnqueueResult?: (result: EnqueueCounts) => void
  onEnqueueError?: (error: unknown) => void
}

const MAIL_QUERY_KEYS = ['mail-queue', 'queue-mail-candidates', 'queue-counts'] as const

export function invalidateMailQueries(queryClient: QueryClient) {
  for (const key of MAIL_QUERY_KEYS) {
    queryClient.invalidateQueries({ queryKey: [key] })
  }
}

function invalidateQueueQueries(
  queryClient: QueryClient,
  queryKey: string,
  extraQueryKeys?: string[],
) {
  queryClient.invalidateQueries({ queryKey: [queryKey] })
  for (const key of extraQueryKeys ?? []) {
    queryClient.invalidateQueries({ queryKey: [key] })
  }
}

function invalidateAfterQueueAction(ctx: QueueBulkActionContext) {
  invalidateQueueQueries(ctx.queryClient, ctx.queryKey, ctx.extraQueryKeys)
  ctx.queryClient.invalidateQueries({ queryKey: ['queue-counts'] })
  ctx.onAfterAction?.()
}

/** Core enqueue used by bulk + row Add to mail batch actions. */
export async function enqueueLeadsAsBulkResult(
  leadIds: number[],
  ctx: QueueBulkActionContext,
): Promise<BulkActionResult> {
  try {
    const result = await openLetterService.enqueue(leadIds)
    invalidateMailQueries(ctx.queryClient)
    invalidateQueueQueries(ctx.queryClient, ctx.queryKey, ctx.extraQueryKeys)
    ctx.onEnqueueResult?.(result)
    ctx.onAfterAction?.()
    return {
      successes: result.added,
      failures: result.skipped + result.invalid,
      message: formatEnqueueSummary(result),
    }
  } catch (err) {
    ctx.onEnqueueError?.(err)
    throw err
  }
}

export function createAddToMailBatchBulkAction(ctx: QueueBulkActionContext): BulkAction {
  return {
    label: 'Add to mail batch',
    testId: 'add-to-batch-bulk-action',
    onClick: (ids) => enqueueLeadsAsBulkResult(ids, ctx),
  }
}

export function createAddToMailBatchRowAction(ctx: QueueBulkActionContext): RowAction {
  return {
    label: 'Add to batch',
    icon: <PostAddIcon fontSize="small" />,
    testId: 'add-to-batch-row-action',
    onClick: async (row) => {
      await enqueueLeadsAsBulkResult([row.id], ctx)
    },
  }
}

export function createSuppressBulkAction(ctx: QueueBulkActionContext): BulkAction {
  return {
    label: 'Suppress',
    testId: 'bulk-suppress',
    onClick: async (ids) => {
      const result = await bulkActionService.bulkSuppress(ids)
      invalidateAfterQueueAction(ctx)
      return result
    },
  }
}

export function createCreateTaskBulkAction(ctx: QueueBulkActionContext): BulkAction {
  return {
    label: 'Create task',
    testId: 'bulk-create-task',
    onClick: async (ids) => {
      const result = await bulkActionService.bulkCreateTask(ids, {
        title: 'Follow up',
        task_type: 'call_owner_today',
      })
      invalidateAfterQueueAction(ctx)
      return result
    },
  }
}

export function createReactivateBulkAction(ctx: QueueBulkActionContext): BulkAction {
  return {
    label: 'Reactivate',
    testId: 'bulk-reactivate',
    onClick: async (ids) => {
      const results = await Promise.allSettled(
        ids.map((id) => commandCenterService.reactivate(id)),
      )
      const successes = results.filter((r) => r.status === 'fulfilled').length
      const failures = results.length - successes
      invalidateAfterQueueAction(ctx)
      return { successes, failures }
    },
  }
}

const FACTORIES: Record<
  QueueBulkActionKey,
  (ctx: QueueBulkActionContext) => BulkAction
> = {
  add_to_mail_batch: createAddToMailBatchBulkAction,
  create_task: createCreateTaskBulkAction,
  suppress: createSuppressBulkAction,
  reactivate: createReactivateBulkAction,
}

/** Compose standard BulkAction[] for a QueueTable from shared keys. */
export function resolveBulkActions(
  keys: QueueBulkActionKey[],
  ctx: QueueBulkActionContext,
): BulkAction[] {
  return keys.map((key) => FACTORIES[key](ctx))
}
