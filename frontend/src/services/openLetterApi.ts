/**
 * Open Letter Connect API client
 */
import api from '@/services/api'

export interface OpenLetterConfig {
  configured: boolean
  token_source?: 'environment' | 'database' | null
  uses_env_token?: boolean
  requires_user_api_token?: boolean
  use_demo_api?: boolean
  default_product_id?: number | null
  default_template_id?: number | null
  default_template_name?: string | null
  batch_minimum?: number
  allow_send_below_minimum?: boolean
  return_address?: Record<string, unknown> | null
  estimated_cost_per_piece?: number | null
  updated_at?: string | null
}

export interface MailQueueItem {
  id: number
  lead_id: number
  user_id: string
  status: string
  validation_error?: string | null
  campaign_id?: number | null
  created_at?: string | null
  owner_name?: string | null
  property_street?: string | null
  mailing_address?: string | null
  mailing_city?: string | null
  mailing_state?: string | null
  mailing_zip?: string | null
  last_mailed_at?: string | null
  last_sale_at?: string | null
}

export interface MailQueueSummary {
  queued_count: number
  batch_minimum: number
  allow_send_below_minimum: boolean
  can_send: boolean
  estimated_cost_per_piece?: number | null
  estimated_total?: number | null
  items: MailQueueItem[]
}

export interface EnqueueLeadResult {
  lead_id: number
  status: string
  error?: string
}

export type EnqueueResult = MailQueueSummary & {
  added: number
  skipped: number
  invalid: number
  results?: EnqueueLeadResult[]
}

export type EnqueuePreviewResult = MailQueueSummary & {
  dry_run: true
  would_add: number
  would_skip: number
  would_fail: number
  candidate_count: number
  results?: EnqueueLeadResult[]
}

export interface MailCampaign {
  id: number
  olc_order_id?: string | null
  status: string
  lead_count: number
  cost?: number | null
  cost_per_piece?: number | null
  product_id?: number | null
  template_id?: number | null
  template_name?: string | null
  delivery_stats?: Record<string, number> | null
  scan_stats?: { scanned?: number; not_scanned?: number } | null
  scan_rate?: number | null
  response_count: number
  response_rate?: number | null
  created_by: string
  submitted_at?: string | null
  error_message?: string | null
  analytics_synced_at?: string | null
  created_at?: string | null
}

export const openLetterService = {
  getConfig: (): Promise<OpenLetterConfig> =>
    api.get('/open-letter/config').then((r) => r.data),

  saveConfig: (payload: Record<string, unknown>): Promise<OpenLetterConfig> =>
    api.post('/open-letter/config', payload).then((r) => r.data),

  testConfig: (): Promise<{ success: boolean; product_count?: number }> =>
    api.post('/open-letter/config/test').then((r) => r.data),

  listProducts: (): Promise<{ data?: unknown[] }> =>
    api.get('/open-letter/products').then((r) => r.data),

  listTemplates: (params?: { page?: number; page_size?: number }): Promise<{ data?: unknown[] }> =>
    api.get('/open-letter/templates', { params }).then((r) => r.data),

  getQueue: (): Promise<MailQueueSummary> =>
    api.get('/mail-queue/').then((r) => r.data),

  enqueue: (leadIds: number[]): Promise<EnqueueResult> =>
    api.post('/mail-queue/', { lead_ids: leadIds }).then((r) => r.data),

  enqueueCandidates: (limit?: number): Promise<EnqueueResult> =>
    api.post('/mail-queue/enqueue-candidates', { limit: limit ?? null }).then((r) => r.data),

  previewEnqueueCandidates: (limit?: number): Promise<EnqueuePreviewResult> =>
    api
      .post('/mail-queue/enqueue-candidates', { limit: limit ?? null, dry_run: true })
      .then((r) => r.data),

  removeFromQueue: (itemId: number): Promise<MailQueueSummary> =>
    api.delete(`/mail-queue/${itemId}`).then((r) => r.data),

  sendBatch: (force = false): Promise<MailCampaign> =>
    api.post('/mail-queue/send', { force }).then((r) => r.data),

  listCampaigns: (page = 1, perPage = 25): Promise<{ campaigns: MailCampaign[]; total: number }> =>
    api.get('/mail-queue/campaigns', { params: { page, per_page: perPage } }).then((r) => r.data),

  getCampaign: (id: number, refresh = false): Promise<MailCampaign> =>
    api.get(`/mail-queue/campaigns/${id}`, { params: refresh ? { refresh: 'true' } : {} }).then((r) => r.data),

  campaignsForLead: (leadId: number, days = 90): Promise<{ campaigns: MailCampaign[] }> =>
    api.get(`/mail-queue/campaigns/for-lead/${leadId}`, { params: { days } }).then((r) => r.data),
}

export default openLetterService
