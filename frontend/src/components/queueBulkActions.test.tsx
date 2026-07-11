/**
 * Tests for shared queue bulk action factories.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import openLetterService from '@/services/openLetterApi'
import { bulkActionService, commandCenterService } from '@/services/api'
import {
  enqueueLeadsAsBulkResult,
  resolveBulkActions,
  createAddToMailBatchBulkAction,
  createSuppressBulkAction,
  createCreateTaskBulkAction,
  createReactivateBulkAction,
} from './queueBulkActions'

vi.mock('@/services/openLetterApi', () => ({
  default: {
    enqueue: vi.fn(),
  },
}))

vi.mock('@/services/api', () => ({
  bulkActionService: {
    bulkSuppress: vi.fn(),
    bulkCreateTask: vi.fn(),
  },
  commandCenterService: {
    reactivate: vi.fn(),
  },
}))

describe('queueBulkActions', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    vi.clearAllMocks()
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    vi.spyOn(queryClient, 'invalidateQueries')
  })

  const baseCtx = () => ({
    queryClient,
    queryKey: 'queue-todays-action',
    extraQueryKeys: ['queue-counts'],
  })

  it('enqueueLeadsAsBulkResult maps counts and invalidates mail + queue keys', async () => {
    vi.mocked(openLetterService.enqueue).mockResolvedValue({
      added: 2,
      skipped: 1,
      invalid: 0,
      results: [
        { lead_id: 1, status: 'queued' },
        { lead_id: 2, status: 'queued' },
        { lead_id: 3, status: 'already_queued' },
      ],
      queued_count: 3,
      batch_minimum: 50,
      allow_send_below_minimum: false,
      can_send: false,
      items: [],
    })
    const onAfterAction = vi.fn()
    const onEnqueueResult = vi.fn()

    const result = await enqueueLeadsAsBulkResult([1, 2, 3], {
      ...baseCtx(),
      onAfterAction,
      onEnqueueResult,
    })

    expect(openLetterService.enqueue).toHaveBeenCalledWith([1, 2, 3])
    expect(result.successes).toBe(2)
    expect(result.failures).toBe(1)
    expect(result.message).toContain('Added 2')
    expect(onAfterAction).toHaveBeenCalled()
    expect(onEnqueueResult).toHaveBeenCalled()
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['mail-queue'] })
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ['queue-mail-candidates'],
    })
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ['queue-todays-action'],
    })
  })

  it('enqueueLeadsAsBulkResult forwards errors to onEnqueueError', async () => {
    const err = new Error('network')
    vi.mocked(openLetterService.enqueue).mockRejectedValue(err)
    const onEnqueueError = vi.fn()

    await expect(
      enqueueLeadsAsBulkResult([1], { ...baseCtx(), onEnqueueError }),
    ).rejects.toThrow('network')
    expect(onEnqueueError).toHaveBeenCalledWith(err)
  })

  it('resolveBulkActions composes factories in key order', () => {
    const actions = resolveBulkActions(
      ['add_to_mail_batch', 'create_task', 'suppress'],
      baseCtx(),
    )
    expect(actions.map((a) => a.testId)).toEqual([
      'add-to-batch-bulk-action',
      'bulk-create-task',
      'bulk-suppress',
    ])
  })

  it('createAddToMailBatchBulkAction enqueues selected ids', async () => {
    vi.mocked(openLetterService.enqueue).mockResolvedValue({
      added: 1,
      skipped: 0,
      invalid: 0,
      queued_count: 1,
      batch_minimum: 50,
      allow_send_below_minimum: false,
      can_send: false,
      items: [],
    })
    const action = createAddToMailBatchBulkAction(baseCtx())
    const result = await action.onClick([9, 10])
    expect(openLetterService.enqueue).toHaveBeenCalledWith([9, 10])
    expect(result.successes).toBe(1)
  })

  it('createSuppressBulkAction calls bulkSuppress', async () => {
    vi.mocked(bulkActionService.bulkSuppress).mockResolvedValue({
      successes: 2,
      failures: 0,
    })
    const action = createSuppressBulkAction(baseCtx())
    const result = await action.onClick([1, 2])
    expect(bulkActionService.bulkSuppress).toHaveBeenCalledWith([1, 2])
    expect(result).toEqual({ successes: 2, failures: 0 })
  })

  it('createCreateTaskBulkAction creates follow-up tasks', async () => {
    vi.mocked(bulkActionService.bulkCreateTask).mockResolvedValue({
      successes: 3,
      failures: 0,
    })
    const action = createCreateTaskBulkAction(baseCtx())
    const result = await action.onClick([1, 2, 3])
    expect(bulkActionService.bulkCreateTask).toHaveBeenCalledWith([1, 2, 3], {
      title: 'Follow up',
      task_type: 'call_owner_today',
    })
    expect(result.successes).toBe(3)
  })

  it('createReactivateBulkAction loops reactivate and counts failures', async () => {
    vi.mocked(commandCenterService.reactivate)
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValueOnce({})
    const action = createReactivateBulkAction(baseCtx())
    const result = await action.onClick([1, 2, 3])
    expect(commandCenterService.reactivate).toHaveBeenCalledTimes(3)
    expect(result).toEqual({ successes: 2, failures: 1 })
  })
})
