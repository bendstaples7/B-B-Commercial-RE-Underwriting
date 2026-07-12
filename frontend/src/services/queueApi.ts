import api from '@/services/httpClient'
import type {
  BulkActionResult,
  QueueCounts,
  QueueNavigation,
  QueuePage,
} from '@/types'

export const queueService = {
  getCounts: (): Promise<QueueCounts> =>
    api.get('/queues/counts').then(r => r.data),
  getTodaysAction: (
    page = 1,
    perPage = 20,
    outreach?: string | null,
  ): Promise<QueuePage> =>
    api.get('/queues/todays-action', {
      params: {
        page,
        per_page: perPage,
        ...(outreach ? { outreach } : {}),
      },
    }).then(r => r.data),
  getTodaysActionOutreachCounts: (): Promise<Record<string, number>> =>
    api.get('/queues/todays-action/outreach-counts').then(r => r.data),
  getTodaysActionLeadIds: (
    outreach?: string | null,
  ): Promise<{ lead_ids: number[]; total: number; outreach: string | null }> =>
    api.get('/queues/todays-action/lead-ids', {
      params: outreach ? { outreach } : {},
    }).then(r => r.data),
  getPreviouslyWarm: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/previously-warm', { params: { page, per_page: perPage } }).then(r => r.data),
  getFollowUpOverdue: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/follow-up-overdue', { params: { page, per_page: perPage } }).then(r => r.data),
  getNoNextAction: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/no-next-action', { params: { page, per_page: perPage } }).then(r => r.data),
  getNoNextActionStatusCounts: (): Promise<Record<string, number>> =>
    api.get('/queues/no-next-action/status-counts').then(r => r.data),
  getNoNextActionLeadIds: (leadStatus: string): Promise<{ lead_ids: number[]; total: number }> =>
    api.get('/queues/no-next-action/lead-ids', { params: { lead_status: leadStatus } }).then(r => r.data),
  bulkUpdateNoNextActionStatus: (payload: {
    source_status: string
    status: string
    reason?: string
  }): Promise<BulkActionResult & { total_matched?: number }> =>
    api.post('/queues/no-next-action/bulk-update-status', payload).then(r => r.data),
  getNeedsReview: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/needs-review', { params: { page, per_page: perPage } }).then(r => r.data),
  getDoNotContact: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/do-not-contact', { params: { page, per_page: perPage } }).then(r => r.data),
  getMissingPropertyMatch: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/missing-property-match', { params: { page, per_page: perPage } }).then(r => r.data),
  getMailCandidates: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/mail-candidates', { params: { page, per_page: perPage } }).then(r => r.data),
  getNavigation: (
    queueKey: string,
    leadId: number,
    options?: { outreach?: string | null },
  ): Promise<QueueNavigation> =>
    api.get(`/queues/${queueKey}/navigation`, {
      params: {
        lead_id: leadId,
        ...(options?.outreach ? { outreach: options.outreach } : {}),
      },
    }).then(r => r.data),
}
