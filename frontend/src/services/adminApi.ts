/**
 * Admin API — background jobs and related admin endpoints.
 */
import api from '@/services/httpClient'

export type CeleryTaskSummary = {
  id?: string | null
  name: string
  args: unknown[]
  kwargs: Record<string, unknown>
  state: string
  worker?: string | null
  time_start?: number | null
  is_mail_submit: boolean
  is_hubspot_pipeline: boolean
}

export type HubSpotPipelineProgress = {
  stage: string
  stage_index: number
  stage_total: number
  label: string
  updated_at?: string | null
  pipeline_running: boolean
}

export type MailCampaignInFlight = {
  id: number
  status: string
  lead_count: number
  olc_order_id?: string | null
  created_at?: string | null
  created_by?: string | null
  error_message?: string | null
  /** Pending in DB but no matching Celery submit task. */
  orphan?: boolean
}

export type BackgroundJobsSnapshot = {
  celery_inspect_ok: boolean
  active: CeleryTaskSummary[]
  reserved: CeleryTaskSummary[]
  scheduled: CeleryTaskSummary[]
  queued: CeleryTaskSummary[]
  queue_depth: number
  hubspot_pipeline: HubSpotPipelineProgress
  mail_campaigns_in_flight: MailCampaignInFlight[]
  busy: boolean
}

export const adminService = {
  getBackgroundJobs: async (): Promise<BackgroundJobsSnapshot> => {
    const response = await api.get<BackgroundJobsSnapshot>('/admin/background-jobs')
    return response.data
  },
}
