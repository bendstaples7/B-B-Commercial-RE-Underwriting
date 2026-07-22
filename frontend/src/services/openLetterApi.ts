/**
 * Open Letter Connect API client
 */
import api from '@/services/api'

export interface MailCreativePreset {
  id: string
  label: string
  first_name?: string | null
  last_name?: string | null
  phone?: string | null
  email?: string | null
  website?: string | null
  include_email?: boolean
  include_website?: boolean
  envelope_color?: string | null
  font_name?: string | null
  font_color?: string | null
  olc_template_id?: number | null
  olc_template_name?: string | null
  sender_display_name?: string | null
}

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
  creative_presets?: MailCreativePreset[]
  active_creative_preset_id?: string | null
  /** Auto-confirmed from the selected OLC template design (not user-selected). */
  template_style?: {
    font_name?: string | null
    font_color?: string | null
    fill?: string | null
    template_id?: number | string | null
    confirmed_from?: string
  } | null
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
  page?: number
  per_page?: number
  total?: number
}

export interface EnqueueLeadResult {
  lead_id: number
  status: string
  error?: string
  owner_name?: string | null
  property_street?: string | null
  sale_date?: string | null
  rescheduled_to?: string | null
  rescheduled_task_count?: number
  skip_trace_scheduled?: boolean
  skip_trace_task_id?: number | null
  removed_queue_item_count?: number
}

export type EnqueueResult = Omit<MailQueueSummary, 'items'> & {
  attempt_id?: number
  added: number
  skipped: number
  invalid: number
  results?: EnqueueLeadResult[]
  items?: MailQueueItem[]
}

export interface MailEnqueueAttemptSummary {
  id: number
  requested_count: number
  added: number
  skipped: number
  invalid: number
  source_queue?: string | null
  created_at?: string | null
}

export interface MailEnqueueAttempt extends MailEnqueueAttemptSummary {
  results: EnqueueLeadResult[]
}

export type EnqueuePreviewResult = Omit<MailQueueSummary, 'items'> & {
  dry_run: true
  would_add: number
  would_skip: number
  would_fail: number
  candidate_count: number
  results?: EnqueueLeadResult[]
  items?: MailQueueItem[]
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
  creative?: MailCreativePreset | null
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
  address_feedback?: {
    corrected?: number
    failed?: number
    verified?: number
    unchanged?: number
  } | null
}

export interface CreativeRollupRow {
  sender_display_name: string
  envelope_color: string
  font_name: string
  font_color: string
  include_email: boolean
  include_website: boolean
  campaign_count: number
  lead_count: number
  response_count: number
  response_rate?: number | null
  scan_rate?: number | null
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

  getTemplateStyle: (templateId: number): Promise<{
    font_name?: string | null
    font_color?: string | null
    fill?: string | null
    template_id?: number | string | null
    confirmed_from?: string
  }> =>
    api.get(`/open-letter/templates/${templateId}/style`).then((r) => r.data),

  getQueue: (params?: { page?: number; per_page?: number }): Promise<MailQueueSummary> =>
    api.get('/mail-queue/', { params }).then((r) => r.data),

  // The staged batch view must show every queued item, but /mail-queue/ now
  // paginates (max 100/page). Aggregate all pages so batches above the page
  // size are not silently hidden while queued_count reports the full total.
  getAllQueued: async (): Promise<MailQueueSummary> => {
    const perPage = 100
    const first: MailQueueSummary = await api
      .get('/mail-queue/', { params: { page: 1, per_page: perPage } })
      .then((r) => r.data)
    const total = first.total ?? first.items.length
    if (first.items.length >= total) return first
    const pageCount = Math.ceil(total / perPage)
    const restPages = await Promise.all(
      Array.from({ length: pageCount - 1 }, (_, i) =>
        api
          .get('/mail-queue/', { params: { page: i + 2, per_page: perPage } })
          .then((r) => (r.data as MailQueueSummary).items ?? []),
      ),
    )
    return { ...first, items: [...first.items, ...restPages.flat()] }
  },

  enqueue: (leadIds: number[], sourceQueue?: string): Promise<EnqueueResult> =>
    api.post('/mail-queue/', {
      lead_ids: leadIds,
      ...(sourceQueue ? { source_queue: sourceQueue } : {}),
    }).then((r) => r.data),

  listEnqueueAttempts: (limit = 20): Promise<{ attempts: MailEnqueueAttemptSummary[] }> =>
    api.get('/mail-queue/attempts', { params: { limit } }).then((r) => r.data),

  getEnqueueAttempt: (attemptId: number): Promise<MailEnqueueAttempt> =>
    api.get(`/mail-queue/attempts/${attemptId}`).then((r) => r.data),

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

  listCampaigns: (page = 1, perPage = 25): Promise<{
    campaigns: MailCampaign[]
    total: number
    creative_rollup?: CreativeRollupRow[]
  }> =>
    api.get('/mail-queue/campaigns', { params: { page, per_page: perPage } }).then((r) => r.data),

  getCampaign: (id: number, refresh = false): Promise<MailCampaign> =>
    api.get(`/mail-queue/campaigns/${id}`, { params: refresh ? { refresh: 'true' } : {} }).then((r) => r.data),

  redispatchCampaign: (id: number): Promise<MailCampaign> =>
    api.post(`/mail-queue/campaigns/${id}/redispatch`).then((r) => r.data),

  cancelCampaign: (
    id: number,
    opts?: { release_queue?: boolean },
  ): Promise<MailCampaign & {
    olc_cancel_ok?: boolean
    olc_cancel_detail?: string
    requeued_count?: number
    queue_held?: boolean
    warning?: string | null
  }> =>
    api.post(`/mail-queue/campaigns/${id}/cancel`, {
      release_queue: Boolean(opts?.release_queue),
    }).then((r) => r.data),

  campaignsForLead: (leadId: number, days = 90): Promise<{ campaigns: MailCampaign[] }> =>
    api.get(`/mail-queue/campaigns/for-lead/${leadId}`, { params: { days } }).then((r) => r.data),
}

export default openLetterService
