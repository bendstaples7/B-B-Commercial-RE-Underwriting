/**
 * Tests for shared queue bulk action factories.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import openLetterService from '@/services/openLetterApi'
import { bulkActionService, commandCenterService } from '@/services/api'
import {
  enqueueLeadsAsBulkResult,
  bumpMailQueueAfterEnqueue,
  stripMailCandidatesFromCache,
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
    queryClient.setQueryData(['mail-queue'], {
      queued_count: 1,
      batch_minimum: 3,
      allow_send_below_minimum: false,
      can_send: false,
      estimated_cost_per_piece: 1.255,
      estimated_cost_source_sent_at: '2026-07-12T15:00:00Z',
      estimated_total: 1.26,
      items: [],
    })
    queryClient.setQueryData(['queue-mail-candidates', 1], {
      rows: [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }],
      total: 4,
    })
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

    expect(openLetterService.enqueue).toHaveBeenCalledWith(
      [1, 2, 3],
      'queue-todays-action',
    )
    expect(result.successes).toBe(2)
    expect(result.failures).toBe(1)
    expect(result.message).toContain('Added 2')
    expect(onAfterAction).toHaveBeenCalled()
    expect(onEnqueueResult).toHaveBeenCalled()
    expect(queryClient.getQueryData(['mail-queue'])).toMatchObject({
      queued_count: 3,
      can_send: true,
      estimated_total: 3.77,
      estimated_cost_per_piece: 1.255,
      estimated_cost_source_sent_at: '2026-07-12T15:00:00Z',
    })
    expect(queryClient.getQueryData(['queue-mail-candidates', 1])).toEqual({
      rows: [{ id: 3 }, { id: 4 }],
      total: 2,
    })
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['mail-queue'] })
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ['queue-mail-candidates'],
    })
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({
      queryKey: ['queue-todays-action'],
    })
  })

  it('stripMailCandidatesFromCache updates every cached candidate page', () => {
    queryClient.setQueryData(['queue-mail-candidates', 1], {
      rows: [{ id: 1 }, { id: 2 }],
      total: 3,
    })
    queryClient.setQueryData(['queue-mail-candidates', 2], {
      rows: [{ id: 3 }],
      total: 3,
    })

    stripMailCandidatesFromCache(queryClient, [2, 3])

    expect(queryClient.getQueryData(['queue-mail-candidates', 1])).toEqual({
      rows: [{ id: 1 }],
      total: 1,
    })
    expect(queryClient.getQueryData(['queue-mail-candidates', 2])).toEqual({
      rows: [],
      total: 1,
    })
  })

  it('bumpMailQueueAfterEnqueue preserves cached items and below-minimum override', () => {
    queryClient.setQueryData(['mail-queue'], {
      queued_count: 2,
      batch_minimum: 50,
      allow_send_below_minimum: true,
      can_send: false,
      estimated_cost_per_piece: 1.25,
      estimated_total: 2.5,
      items: [{ id: 4, lead_id: 8 }],
    })

    bumpMailQueueAfterEnqueue(queryClient, { added: 2 })

    expect(queryClient.getQueryData(['mail-queue'])).toMatchObject({
      queued_count: 4,
      can_send: true,
      estimated_total: 5,
      items: [{ id: 4, lead_id: 8 }],
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
    expect(openLetterService.enqueue).toHaveBeenCalledWith(
      [9, 10],
      'queue-todays-action',
    )
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
