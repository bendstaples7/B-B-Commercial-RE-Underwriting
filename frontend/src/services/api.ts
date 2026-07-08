/**
 * API service layer for backend communication
 */
import axios, { AxiosError, AxiosInstance } from 'axios'
import type {
  AnalysisSession,
  StartAnalysisResponse,
  StepResult,
  ErrorResponse,
  Report,
  PropertyScoreResponse,
  RecalculateRequest,
  RecalculateResponse,
  SearchResponse,
  SearchParams,
} from '@/types'
import {
  HubSpotConfigSchema,
  HubSpotImportRunSchema,
  HubSpotImportRunListSchema,
  HubSpotMatchListSchema,
  PipelineStatusSchema,
} from '@/services/schemas'

// Create axios instance with default config
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 second timeout
})

// Request interceptor — sends user identity via header, not body.
// Injecting user_id into the request body breaks Marshmallow schemas that
// don't declare it, causing 400 validation errors on endpoints like /confirm.
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('session_token')
    if (token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    // Keep X-User-Id for backward compatibility during transition
    const userId = localStorage.getItem('user_id') || 'default_user'
    config.headers['X-User-Id'] = userId
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ErrorResponse>) => {
    if (error.response) {
      // Server responded with error status
      const errorData = error.response.data
      const url = error.config?.url ?? 'unknown'
      const status = error.response.status

      // Handle 401 Unauthorized — clear session and redirect to login.
      // Exclude /auth/login itself: a 401 there means wrong credentials,
      // not an expired session, so the LoginPage handles it directly.
      if (status === 401 && !url.includes('/auth/login')) {
        const returnUrl = window.location.pathname + window.location.search
        localStorage.removeItem('session_token')
        localStorage.removeItem('user_id')
        window.location.href = `/login?returnUrl=${encodeURIComponent(returnUrl)}`
        return Promise.reject(error)
      }

      // Extract the real message — backend uses several shapes:
      //   { error: { message: "..." } }  — structured error object
      //   { error: "..." }               — plain string error (auth endpoints)
      //   { message: "..." }             — direct message field
      const errorField = (errorData as any)?.error
      const message =
        errorField?.message ||
        (typeof errorField === 'string' ? errorField : null) ||
        errorData?.message ||
        'An error occurred'

      console.error(`[API] ${status} ${url}:`, message, errorData)

      // Handle specific error codes
      if (status === 429) {
        throw new Error('Rate limit exceeded. Please try again later.')
      }

      throw new Error(message)
    } else if (error.request) {
      // Request made but no response received
      console.error('[API] Network error — no response received:', error.request)
      throw new Error('Network error. Please check your connection.')
    } else {
      // Something else happened
      console.error('[API] Request setup error:', error.message)
      throw new Error(error.message)
    }
  }
)

export const analysisService = {
  /**
   * Health check endpoint
   */
  healthCheck: async (): Promise<{ status: string }> => {
    const response = await api.get('/health')
    return response.data
  },

  /**
   * Start a new analysis session
   */
  startAnalysis: async (address: string, latitude?: number, longitude?: number): Promise<StartAnalysisResponse> => {
    const userId = localStorage.getItem('user_id') || 'default'
    const response = await api.post<any>('/analysis/start', {
      address,
      user_id: userId,
      ...(latitude != null && longitude != null ? { latitude, longitude } : {}),
    })
    const raw = response.data
    // Map snake_case backend response to camelCase frontend type
    return {
      sessionId: raw.session_id,
      message: raw.message ?? '',
      propertyFacts: raw.property_facts ?? undefined,
    }
  },

  /**
   * Get current session state
   */
  getSession: async (sessionId: string): Promise<AnalysisSession> => {
    const response = await api.get<AnalysisSession>(`/analysis/${sessionId}`)
    return response.data
  },

  /**
   * Advance to the next workflow step
   */
  advanceToStep: async (
    sessionId: string,
    stepNumber: number,
    approvalData?: Record<string, any>
  ): Promise<StepResult> => {
    // Step 2 (comparable search) calls Gemini which can take up to 2 minutes
    const timeout = stepNumber === 2 ? 180000 : 30000
    const response = await api.post<StepResult>(
      `/analysis/${sessionId}/step/${stepNumber}`,
      { approval_data: approvalData },
      { timeout }
    )
    // Step 2 returns 202 Accepted — treat as a pending result
    if (response.status === 202) {
      return { status: 'accepted', sessionId } as unknown as StepResult
    }
    return response.data
  },

  /**
   * Update data for a specific workflow step
   */
  updateStepData: async (
    sessionId: string,
    stepNumber: number,
    data: Record<string, any>
  ): Promise<StepResult> => {
    const response = await api.put<StepResult>(
      `/analysis/${sessionId}/step/${stepNumber}`,
      data
    )
    return response.data
  },

  /**
   * Navigate back to a previous workflow step
   */
  goBackToStep: async (
    sessionId: string,
    stepNumber: number
  ): Promise<AnalysisSession> => {
    const response = await api.post<AnalysisSession>(
      `/analysis/${sessionId}/back/${stepNumber}`
    )
    return response.data
  },

  /**
   * Generate analysis report
   */
  generateReport: async (sessionId: string): Promise<Report> => {
    const response = await api.get<{ report: Report }>(
      `/analysis/${sessionId}/report`
    )
    return response.data.report
  },

  /**
   * Export report to Excel
   */
  exportToExcel: async (sessionId: string): Promise<Blob> => {
    const response = await api.get(`/analysis/${sessionId}/export/excel`, {
      responseType: 'blob',
    })
    return response.data
  },

  /**
   * Export report to Google Sheets
   */
  exportToGoogleSheets: async (
    sessionId: string,
    credentials: Record<string, any>
  ): Promise<{ url: string; message: string }> => {
    const response = await api.post<{ url: string; message: string }>(
      `/analysis/${sessionId}/export/sheets`,
      { credentials }
    )
    return response.data
  },
}

/**
 * Lead scoring API service
 *
 * Backend endpoints are mounted at `/api/lead-scores`. Since the axios
 * instance's baseURL is `/api`, request paths here are relative to that
 * (e.g. `/lead-scores/:leadId`).
 */
export const leadScoreService = {
  getLeadScore: (leadId: number) =>
    api.get<PropertyScoreResponse>(`/lead-scores/${leadId}`),
  recalculate: (params: RecalculateRequest) =>
    api.post<RecalculateResponse>('/lead-scores/recalculate', params),
}

// Retry configuration for React Query
export const queryConfig = {
  retry: (failureCount: number, error: Error) => {
    // Don't retry on 4xx errors (client errors)
    if (error.message.includes('Rate limit') || error.message.includes('400')) {
      return false
    }
    // Retry up to 3 times for network errors and 5xx errors
    return failureCount < 3
  },
  retryDelay: (attemptIndex: number) => {
    // Exponential backoff: 1s, 2s, 4s
    return Math.min(1000 * 2 ** attemptIndex, 30000)
  },
  staleTime: 5 * 60 * 1000, // 5 minutes
  cacheTime: 10 * 60 * 1000, // 10 minutes
}

export default api

// ---------------------------------------------------------------------------
// Multifamily Underwriting Pro Forma API Service
// ---------------------------------------------------------------------------
import type {
  DealSummary,
  DealCreatePayload,
  Deal,
  DealKanbanCard,
  MFUnit,
  RentRollEntry,
  RentRollSummary,
  MarketRentAssumption,
  RentComp,
  RentCompRollup,
  MFSaleComp,
  SaleCompRollup,
  RehabPlanEntry,
  RehabMonthlyRollup,
  LenderProfile,
  DealLenderSelection,
  FundingSource,
  ProFormaResult,
  MFValuation,
  SourcesAndUses,
  Dashboard,
  MFImportResult,
  DealListResponse,
  DealScenario,
  MFLenderType,
  FundingSourceType,
  OccupancyStatus,
} from '@/types'

// ---------------------------------------------------------------------------
// Shared polling helper
// ---------------------------------------------------------------------------

/** Sentinel error thrown when an async job reaches a terminal FAILED state. */
class AsyncJobTerminalError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AsyncJobTerminalError'
  }
}

/**
 * Poll an async job until it completes or times out.
 *
 * @param statusUrlFn - Function that returns the status URL given the job ID.
 * @param jobId - The job ID returned by the enqueue step.
 * @param errorLabel - Human-readable label used in timeout/failure messages.
 * @returns The final result payload when status === 'done'.
 * @throws Error when status === 'failed' or max attempts exceeded.
 */
async function pollAsyncJob(
  statusUrlFn: (jobId: string) => string,
  jobId: string,
  errorLabel: string
): Promise<{ added: number; skipped: number; message: string }> {
  const maxAttempts = 100
  let lastError: Error | null = null
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(resolve => setTimeout(resolve, 3000))
    try {
      const statusResponse = await api.get<{
        status: 'pending' | 'running' | 'done' | 'failed'
        added?: number
        skipped?: number
        message?: string
        error?: string
      }>(statusUrlFn(jobId))
      const result = statusResponse.data
      if (result.status === 'done') {
        return { added: result.added ?? 0, skipped: result.skipped ?? 0, message: result.message ?? '' }
      }
      if (result.status === 'failed') {
        throw new AsyncJobTerminalError(result.error ?? `${errorLabel} failed.`)
      }
      lastError = null  // reset on successful poll
    } catch (err) {
      if (err instanceof AsyncJobTerminalError) throw err  // re-throw terminal failures — never retry
      lastError = err instanceof Error ? err : new Error(String(err))
      // continue polling on transient errors
    }
  }
  throw new Error(`${errorLabel} timed out after 5 minutes.${lastError ? ` Last error: ${lastError.message}` : ''}`)
}

export const multifamilyService = {
  // -------------------------------------------------------------------------
  // Deals (Req 1)
  // -------------------------------------------------------------------------

  /** List all deals owned by the current user (Req 1.5) */
  listDeals: async (): Promise<DealSummary[]> => {
    const response = await api.get<DealListResponse>('/multifamily/deals')
    return response.data.deals
  },

  /** List deals filtered by status (for Kanban per-column fetch) */
  listDealsByStatus: async (status: string): Promise<DealKanbanCard[]> => {
    const response = await api.get<DealListResponse>(
      `/multifamily/deals?status=${encodeURIComponent(status)}`
    )
    return response.data.deals as DealKanbanCard[]
  },

  /** Get full deal detail including all child records (Req 1.4) */
  getDeal: async (dealId: number): Promise<Deal> => {
    const response = await api.get<Deal>(`/multifamily/deals/${dealId}`)
    return response.data
  },

  /** Create a new deal (Req 1.1) */
  createDeal: async (payload: DealCreatePayload): Promise<Deal> => {
    const response = await api.post<Deal>('/multifamily/deals', payload)
    return response.data
  },

  /** Update deal fields (Req 1.6) */
  updateDeal: async (dealId: number, payload: Partial<DealCreatePayload>): Promise<Deal> => {
    const response = await api.patch<Deal>(`/multifamily/deals/${dealId}`, payload)
    return response.data
  },

  /** Soft-delete a deal (Req 1.7) */
  deleteDeal: async (dealId: number): Promise<void> => {
    await api.delete(`/multifamily/deals/${dealId}`)
  },

  /** Link a deal to an existing lead (Req 14.2) */
  linkDealToLead: async (dealId: number, leadId: number): Promise<void> => {
    await api.post(`/multifamily/deals/${dealId}/link-lead`, { lead_id: leadId })
  },

  // -------------------------------------------------------------------------
  // Units & Rent Roll (Req 2)
  // -------------------------------------------------------------------------

  /** Add a unit to a deal (Req 2.1) */
  addUnit: async (
    dealId: number,
    payload: {
      unit_identifier: string
      unit_type: string
      beds: number
      baths: number
      sqft: number
      occupancy_status: OccupancyStatus
    }
  ): Promise<MFUnit> => {
    const response = await api.post<MFUnit>(`/multifamily/deals/${dealId}/units`, payload)
    return response.data
  },

  /** Update a unit */
  updateUnit: async (
    dealId: number,
    unitId: number,
    payload: Partial<{
      unit_identifier: string
      unit_type: string
      beds: number
      baths: number
      sqft: number
      occupancy_status: OccupancyStatus
    }>
  ): Promise<MFUnit> => {
    const response = await api.patch<MFUnit>(`/multifamily/deals/${dealId}/units/${unitId}`, payload)
    return response.data
  },

  /** Remove a unit from a deal */
  deleteUnit: async (dealId: number, unitId: number): Promise<void> => {
    await api.delete(`/multifamily/deals/${dealId}/units/${unitId}`)
  },

  /** Set the rent roll entry for a unit (Req 2.3) */
  setRentRollEntry: async (
    dealId: number,
    unitId: number,
    payload: {
      current_rent: number
      lease_start_date?: string
      lease_end_date?: string
      notes?: string
    }
  ): Promise<RentRollEntry> => {
    const response = await api.put<RentRollEntry>(
      `/multifamily/deals/${dealId}/units/${unitId}/rent-roll`,
      payload
    )
    return response.data
  },

  /** Get rent roll summary rollup (Req 2.5) */
  getRentRollSummary: async (dealId: number): Promise<RentRollSummary> => {
    const response = await api.get<RentRollSummary>(`/multifamily/deals/${dealId}/rent-roll/summary`)
    return response.data
  },

  // -------------------------------------------------------------------------
  // Market Rents & Rent Comps (Req 3)
  // -------------------------------------------------------------------------

  /** Set market rent assumption for a unit type (Req 3.1) */
  setMarketRentAssumption: async (
    dealId: number,
    unitType: string,
    payload: { target_rent?: number; post_reno_target_rent?: number }
  ): Promise<MarketRentAssumption> => {
    const response = await api.put<MarketRentAssumption>(
      `/multifamily/deals/${dealId}/market-rents/${encodeURIComponent(unitType)}`,
      payload
    )
    return response.data
  },

  /** Add a rent comp (Req 3.2) */
  addRentComp: async (
    dealId: number,
    payload: {
      address: string
      neighborhood?: string
      unit_type: string
      observed_rent: number
      sqft: number
      observation_date: string
      source_url?: string
    }
  ): Promise<RentComp> => {
    const response = await api.post<RentComp>(`/multifamily/deals/${dealId}/rent-comps`, payload)
    return response.data
  },

  /** Delete a rent comp */
  deleteRentComp: async (dealId: number, compId: number): Promise<void> => {
    await api.delete(`/multifamily/deals/${dealId}/rent-comps/${compId}`)
  },

  /** Fetch rent comps via Gemini AI web search and bulk-insert them (Req 3.2)
   *
   * Uses the async Celery path (?async=true): POSTs to start the job (returns
   * immediately with a job_id), then polls /fetch-ai/status/:job_id until done.
   * This prevents any HTTP timeout issues regardless of how long Gemini takes.
   */
  fetchRentCompsAI: async (dealId: number): Promise<{ added: number; skipped: number; message: string }> => {
    // Step 1: enqueue the Celery task
    const startResponse = await api.post<{ job_id: string; status: string }>(
      `/multifamily/deals/${dealId}/rent-comps/fetch-ai?async=true`,
      {}
    )
    const jobId = startResponse.data.job_id

    if (!jobId || typeof jobId !== 'string' || jobId.trim() === '') {
      throw new Error('Server returned an invalid job ID. Please try again.')
    }

    // Step 2: poll until done or failed
    return pollAsyncJob(
      (id) => `/multifamily/deals/${dealId}/rent-comps/fetch-ai/status/${id}`,
      jobId,
      'AI rent comp fetch'
    )
  },

  /** Poll the status of an async AI rent comp fetch job */
  getRentCompsAIJobStatus: async (dealId: number, jobId: string): Promise<{
    status: 'pending' | 'running' | 'done' | 'failed'
    added?: number
    skipped?: number
    message?: string
    error?: string
  }> => {
    const response = await api.get(
      `/multifamily/deals/${dealId}/rent-comps/fetch-ai/status/${jobId}`
    )
    return response.data
  },

  /** Get rent comp rollup by unit type (Req 3.4) */
  getRentCompRollup: async (dealId: number, unitType?: string): Promise<RentCompRollup[]> => {
    const params = unitType ? { unit_type: unitType } : {}
    const response = await api.get<RentCompRollup[]>(
      `/multifamily/deals/${dealId}/rent-comps/rollup`,
      { params }
    )
    return response.data
  },

  // -------------------------------------------------------------------------
  // Sale Comps (Req 4)
  // -------------------------------------------------------------------------

  /** Add a sale comp (Req 4.1) */
  addSaleComp: async (
    dealId: number,
    payload: {
      address: string
      unit_count: number
      status: string
      sale_price: number
      close_date: string
      observed_cap_rate: number
      distance_miles?: number
    }
  ): Promise<MFSaleComp> => {
    const response = await api.post<MFSaleComp>(`/multifamily/deals/${dealId}/sale-comps`, payload)
    return response.data
  },

  /** Delete a sale comp */
  deleteSaleComp: async (dealId: number, compId: number): Promise<void> => {
    await api.delete(`/multifamily/deals/${dealId}/sale-comps/${compId}`)
  },

  /** Get AI-suggested comps pending user review */
  getSuggestedSaleComps: async (dealId: number): Promise<MFSaleComp[]> => {
    const response = await api.get<MFSaleComp[]>(`/multifamily/deals/${dealId}/sale-comps/suggested`)
    return response.data
  },

  /** Confirm a suggested comp — moves it into the confirmed set for rollup stats */
  confirmSaleComp: async (dealId: number, compId: number): Promise<MFSaleComp> => {
    const response = await api.post<MFSaleComp>(`/multifamily/deals/${dealId}/sale-comps/${compId}/confirm`)
    return response.data
  },

  /** Dismiss a suggested comp — removes it from the suggested list */
  dismissSaleComp: async (dealId: number, compId: number): Promise<void> => {
    await api.post(`/multifamily/deals/${dealId}/sale-comps/${compId}/dismiss`)
  },

  /** Hard-delete ALL sale comps for a deal (suggested, dismissed, and confirmed) */
  clearAllSaleComps: async (dealId: number): Promise<{ deleted: number }> => {
    const response = await api.delete<{ deleted: number }>(`/multifamily/deals/${dealId}/sale-comps/clear`)
    return response.data
  },

  /** Confirm all pending suggested comps at once */
  confirmAllSaleComps: async (dealId: number): Promise<{ confirmed: number }> => {
    const response = await api.post<{ confirmed: number }>(`/multifamily/deals/${dealId}/sale-comps/confirm-all`)
    return response.data
  },

  /** Fetch sale comps via Gemini AI web search and bulk-insert them (Req 4.1)
   *
   * Uses the async Celery path (?async=true): POSTs to start the job (returns
   * immediately with a job_id), then polls /fetch-ai/status/:job_id until done.
   * This prevents any HTTP timeout issues regardless of how long Gemini takes.
   */
  fetchSaleCompsAI: async (dealId: number): Promise<{ added: number; skipped: number; message: string }> => {
    // Step 1: enqueue the Celery task
    const startResponse = await api.post<{ job_id: string; status: string }>(
      `/multifamily/deals/${dealId}/sale-comps/fetch-ai?async=true`,
      {}
    )
    const jobId = startResponse.data.job_id

    if (!jobId || typeof jobId !== 'string' || jobId.trim() === '') {
      throw new Error('Server returned an invalid job ID. Please try again.')
    }

    // Step 2: poll until done or failed
    return pollAsyncJob(
      (id) => `/multifamily/deals/${dealId}/sale-comps/fetch-ai/status/${id}`,
      jobId,
      'AI sale comp fetch'
    )
  },

  /** Poll the status of an async AI sale comp fetch job */
  getSaleCompsAIJobStatus: async (dealId: number, jobId: string): Promise<{
    status: 'pending' | 'running' | 'done' | 'failed'
    added?: number
    skipped?: number
    message?: string
    error?: string
  }> => {
    const response = await api.get(
      `/multifamily/deals/${dealId}/sale-comps/fetch-ai/status/${jobId}`
    )
    return response.data
  },

  /** Get sale comp rollup (Req 4.4) */
  getSaleCompRollup: async (dealId: number): Promise<SaleCompRollup> => {
    const response = await api.get<SaleCompRollup>(`/multifamily/deals/${dealId}/sale-comps/rollup`)
    return response.data
  },

  // -------------------------------------------------------------------------
  // Rehab Plan (Req 5)
  // -------------------------------------------------------------------------

  /** Set rehab plan entry for a unit (Req 5.1) */
  setRehabPlanEntry: async (
    dealId: number,
    unitId: number,
    payload: {
      renovate_flag: boolean
      current_rent: number
      suggested_post_reno_rent?: number
      underwritten_post_reno_rent?: number
      rehab_start_month?: number
      downtime_months?: number
      rehab_budget?: number
      scope_notes?: string
    }
  ): Promise<RehabPlanEntry> => {
    const response = await api.put<RehabPlanEntry>(
      `/multifamily/deals/${dealId}/units/${unitId}/rehab`,
      payload
    )
    return response.data
  },

  /** Get monthly rehab rollup (Req 5.6) */
  getRehabRollup: async (dealId: number): Promise<RehabMonthlyRollup[]> => {
    const response = await api.get<RehabMonthlyRollup[]>(`/multifamily/deals/${dealId}/rehab/rollup`)
    return response.data
  },

  // -------------------------------------------------------------------------
  // Lender Profiles (Req 6)
  // -------------------------------------------------------------------------

  /** List lender profiles for the current user */
  listLenderProfiles: async (lenderType?: MFLenderType): Promise<LenderProfile[]> => {
    const params = lenderType ? { lender_type: lenderType } : {}
    const response = await api.get<{ profiles: LenderProfile[] }>('/multifamily/lender-profiles', { params })
    return response.data.profiles
  },

  /** Create a lender profile (Req 6.1, 6.2) */
  createLenderProfile: async (
    payload: Omit<LenderProfile, 'id' | 'created_by_user_id' | 'all_in_rate' | 'created_at' | 'updated_at'>
  ): Promise<LenderProfile> => {
    const response = await api.post<LenderProfile>('/multifamily/lender-profiles', payload)
    return response.data
  },

  /** Update a lender profile */
  updateLenderProfile: async (
    profileId: number,
    payload: Partial<Omit<LenderProfile, 'id' | 'created_by_user_id' | 'all_in_rate' | 'created_at' | 'updated_at'>>
  ): Promise<LenderProfile> => {
    const response = await api.patch<LenderProfile>(`/multifamily/lender-profiles/${profileId}`, payload)
    return response.data
  },

  /** Delete a lender profile */
  deleteLenderProfile: async (profileId: number): Promise<void> => {
    await api.delete(`/multifamily/lender-profiles/${profileId}`)
  },

  /** Attach a lender profile to a deal scenario (Req 6.5–6.7) */
  attachLenderToDeal: async (
    dealId: number,
    scenario: DealScenario,
    payload: { lender_profile_id: number; is_primary?: boolean }
  ): Promise<DealLenderSelection> => {
    const response = await api.post<DealLenderSelection>(
      `/multifamily/deals/${dealId}/scenarios/${scenario}/lenders`,
      payload
    )
    return response.data
  },

  /** Detach a lender selection from a deal scenario */
  detachLenderFromDeal: async (
    dealId: number,
    scenario: DealScenario,
    selectionId: number
  ): Promise<void> => {
    await api.delete(`/multifamily/deals/${dealId}/scenarios/${scenario}/lenders/${selectionId}`)
  },

  // -------------------------------------------------------------------------
  // Funding Sources (Req 7)
  // -------------------------------------------------------------------------

  /** Add a funding source to a deal (Req 7.1) */
  addFundingSource: async (
    dealId: number,
    payload: {
      source_type: FundingSourceType
      total_available: number
      interest_rate: number
      origination_fee_rate: number
    }
  ): Promise<FundingSource> => {
    const response = await api.post<FundingSource>(`/multifamily/deals/${dealId}/funding-sources`, payload)
    return response.data
  },

  /** Update a funding source */
  updateFundingSource: async (
    dealId: number,
    sourceId: number,
    payload: Partial<{
      total_available: number
      interest_rate: number
      origination_fee_rate: number
    }>
  ): Promise<FundingSource> => {
    const response = await api.patch<FundingSource>(
      `/multifamily/deals/${dealId}/funding-sources/${sourceId}`,
      payload
    )
    return response.data
  },

  /** Delete a funding source */
  deleteFundingSource: async (dealId: number, sourceId: number): Promise<void> => {
    await api.delete(`/multifamily/deals/${dealId}/funding-sources/${sourceId}`)
  },

  // -------------------------------------------------------------------------
  // Pro Forma & Computation (Req 8–10, 15)
  // -------------------------------------------------------------------------

  /** Get computed or cached pro forma result (Req 8, 15) */
  getProForma: async (dealId: number): Promise<ProFormaResult> => {
    const response = await api.get<ProFormaResult>(`/multifamily/deals/${dealId}/pro-forma`)
    return response.data
  },

  /** Force recompute of pro forma (bypasses cache) */
  recomputeProForma: async (dealId: number): Promise<ProFormaResult> => {
    const response = await api.post<ProFormaResult>(`/multifamily/deals/${dealId}/pro-forma/recompute`)
    return response.data
  },

  /** Get valuation table (Req 9) */
  getValuation: async (dealId: number): Promise<MFValuation> => {
    const response = await api.get<MFValuation>(`/multifamily/deals/${dealId}/valuation`)
    return response.data
  },

  /** Get Sources & Uses per scenario (Req 10) */
  getSourcesAndUses: async (
    dealId: number
  ): Promise<{ scenario_a: SourcesAndUses; scenario_b: SourcesAndUses }> => {
    const response = await api.get<{ scenario_a: SourcesAndUses; scenario_b: SourcesAndUses }>(
      `/multifamily/deals/${dealId}/sources-and-uses`
    )
    return response.data
  },

  // -------------------------------------------------------------------------
  // Dashboard (Req 11)
  // -------------------------------------------------------------------------

  /** Get summary dashboard for a deal (Req 11) */
  getDashboard: async (dealId: number): Promise<Dashboard> => {
    const response = await api.get<Dashboard>(`/multifamily/deals/${dealId}/dashboard`)
    return response.data
  },

  // -------------------------------------------------------------------------
  // Excel Export / Import (Req 12–13)
  // -------------------------------------------------------------------------

  /** Export deal to Excel workbook (Req 12) */
  exportToExcelMF: async (dealId: number): Promise<Blob> => {
    const response = await api.get(`/multifamily/deals/${dealId}/export/excel`, {
      responseType: 'blob',
    })
    return response.data
  },

  /** Export deal to Google Sheets (Req 12.5) */
  exportToSheetsMF: async (dealId: number): Promise<{ url: string }> => {
    const response = await api.get<{ url: string }>(`/multifamily/deals/${dealId}/export/sheets`)
    return response.data
  },

  /** Import a deal from an Excel workbook (Req 13) */
  importFromExcel: async (file: File): Promise<MFImportResult> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post<MFImportResult>('/multifamily/deals/import/excel', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  // -------------------------------------------------------------------------
  // Admin (Req 15.5)
  // -------------------------------------------------------------------------

  /** Enqueue bulk recompute of all deals (admin) */
  recomputeAllDeals: async (): Promise<{ message: string }> => {
    const response = await api.post<{ message: string }>('/multifamily/admin/recompute-all')
    return response.data
  },
}

// ---------------------------------------------------------------------------
// Commercial OM PDF Intake API Service
// ---------------------------------------------------------------------------
import type {
  OMIntakeJob,
  OMIntakeJobListItem,
  OMIntakeReviewData,
  OMIntakeConfirmRequest,
} from '@/types'

export const omIntakeService = {
  /** Upload an OM PDF and create a new intake job */
  uploadOMPDF: async (file: File): Promise<{ intake_job_id: number; status: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post<{ intake_job_id: number; status: string }>(
      '/om-intake/jobs',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
    return response.data
  },

  /** Get the status and metadata for a single OM intake job */
  getOMJobStatus: async (jobId: number): Promise<OMIntakeJob> => {
    const response = await api.get<OMIntakeJob>(`/om-intake/jobs/${jobId}`)
    return response.data
  },

  /** Get the full review data for a job in REVIEW or CONFIRMED status */
  getOMJobReview: async (jobId: number): Promise<OMIntakeReviewData> => {
    const response = await api.get<OMIntakeReviewData>(`/om-intake/jobs/${jobId}/review`)
    return response.data
  },

  /** Confirm an OM intake job and create a Deal */
  confirmOMJob: async (
    jobId: number,
    confirmedData: OMIntakeConfirmRequest
  ): Promise<{ deal_id: number; status: string }> => {
    const response = await api.post<{ deal_id: number; status: string }>(
      `/om-intake/jobs/${jobId}/confirm`,
      confirmedData
    )
    return response.data
  },

  /** Retry a FAILED OM intake job */
  retryOMJob: async (jobId: number): Promise<{ intake_job_id: number; status: string }> => {
    const response = await api.post<{ intake_job_id: number; status: string }>(
      `/om-intake/jobs/${jobId}/retry`
    )
    return response.data
  },

  /** List the current user's OM intake jobs */
  listOMJobs: async (
    page: number = 1,
    pageSize: number = 25
  ): Promise<{ jobs: OMIntakeJobListItem[]; total: number; page: number; page_size: number }> => {
    const response = await api.get<{
      jobs: OMIntakeJobListItem[]
      total: number
      page: number
      page_size: number
    }>('/om-intake/jobs', { params: { page, page_size: pageSize } })
    return response.data
  },
}

// ---------------------------------------------------------------------------
// HubSpot CRM Migration API Services (Tasks 20.2, 20.3, 20.4)
// ---------------------------------------------------------------------------
import type {
  HubSpotConfig,
  HubSpotImportRun,
  HubSpotMatch,
  Organization,
  OrganizationAuditLog,
  PropertyOrganizationLink,
  OwnerOrganizationLink,
  Interaction,
  CRMTask,
  WebhookLogSummary,
  WebhookLogListResponse,
} from '@/types'

// ---------------------------------------------------------------------------
// Task 20.2 — HubSpot API methods
// ---------------------------------------------------------------------------

export const hubSpotService = {
  /** GET /api/hubspot/config — retrieve current HubSpot config (token masked) */
  getHubSpotConfig: async (): Promise<HubSpotConfig> => {
    const response = await api.get<HubSpotConfig>('/hubspot/config')
    return HubSpotConfigSchema.parse(response.data) as HubSpotConfig
  },

  /** POST /api/hubspot/config — save HubSpot API token and optional portal ID */
  saveHubSpotConfig: async (
    token: string,
    portalId?: string
  ): Promise<HubSpotConfig> => {
    const response = await api.post<HubSpotConfig>('/hubspot/config', {
      token,
      portal_id: portalId,
    })
    return response.data
  },

  /** POST /api/hubspot/config/test — test the stored HubSpot connection */
  testHubSpotConnection: async (): Promise<{
    success: boolean
    account_name?: string
    portal_id?: string
    error?: string
  }> => {
    const response = await api.post<{
      success: boolean
      account_name?: string
      portal_id?: string
      error?: string
    }>('/hubspot/config/test')
    return response.data
  },

  /** POST /api/hubspot/import/trigger — kick off a HubSpot import */
  triggerHubSpotImport: async (
    objectTypes?: string[]
  ): Promise<{ run_ids: number[]; status: string }> => {
    const response = await api.post<{ run_ids: number[]; status: string }>(
      '/hubspot/import/trigger',
      objectTypes ? { object_types: objectTypes } : {}
    )
    return response.data
  },

  /** GET /api/hubspot/import/runs — paginated list of import runs */
  listImportRuns: async (
    page?: number,
    perPage?: number
  ): Promise<{ runs: HubSpotImportRun[]; total: number; page: number; per_page: number }> => {
    const response = await api.get<{
      runs: HubSpotImportRun[]
      total: number
      page: number
      per_page: number
    }>('/hubspot/import/runs', {
      params: { page, per_page: perPage },
    })
    return HubSpotImportRunListSchema.parse(response.data) as typeof response.data
  },

  /** GET /api/hubspot/import/runs/{runId} — get a single import run */
  getImportRun: async (runId: number): Promise<HubSpotImportRun> => {
    const response = await api.get<HubSpotImportRun>(`/hubspot/import/runs/${runId}`)
    return HubSpotImportRunSchema.parse(response.data) as HubSpotImportRun
  },

  /** GET /api/hubspot/review-queue — filterable list of HubSpot match records */
  getReviewQueue: async (filters?: {
    type?: string
    confidence?: string
    page?: number
    per_page?: number
  }): Promise<{ matches: HubSpotMatch[]; total: number; page: number; per_page: number; pending_count?: number }> => {
    const response = await api.get<{
      matches: HubSpotMatch[]
      total: number
      page: number
      per_page: number
      pending_count?: number
    }>('/hubspot/review-queue', { params: filters })
    return HubSpotMatchListSchema.parse(response.data) as typeof response.data
  },

  /** POST /api/hubspot/review-queue/{matchId}/confirm — confirm a match */
  confirmMatch: async (
    matchId: number,
    internalRecordId?: number
  ): Promise<HubSpotMatch> => {
    const response = await api.post<HubSpotMatch>(
      `/hubspot/review-queue/${matchId}/confirm`,
      internalRecordId !== undefined ? { internal_record_id: internalRecordId } : {}
    )
    return response.data
  },

  /** POST /api/hubspot/review-queue/{matchId}/reject — reject a match */
  rejectMatch: async (
    matchId: number,
    internalRecordId?: number
  ): Promise<HubSpotMatch> => {
    const response = await api.post<HubSpotMatch>(
      `/hubspot/review-queue/${matchId}/reject`,
      internalRecordId !== undefined ? { internal_record_id: internalRecordId } : {}
    )
    return response.data
  },

  /** POST /api/hubspot/review-queue/{matchId}/new-record — mark as new record */
  markMatchAsNewRecord: async (matchId: number): Promise<HubSpotMatch> => {
    const response = await api.post<HubSpotMatch>(
      `/hubspot/review-queue/${matchId}/new-record`
    )
    return response.data
  },

  /** POST /api/hubspot/export/backup — trigger a backup export Celery task */
  triggerBackupExport: async (): Promise<{ task_id: string }> => {
    const response = await api.post<{ task_id: string }>('/hubspot/export/backup')
    return response.data
  },

  /** GET /api/hubspot/export/backup/download — download the backup JSON file */
  downloadBackupExport: async (): Promise<Blob> => {
    const response = await api.get('/hubspot/export/backup/download', {
      responseType: 'blob',
    })
    return response.data
  },

  /** GET /api/hubspot/pipeline/status — current pipeline running state and counts */
  getPipelineStatus: async (): Promise<{
    pipeline_running: boolean
    matches: { total: number; high: number; medium: number; unmatched: number }
    interactions: number
    tasks: number
    signals: number
  }> => {
    const response = await api.get('/hubspot/pipeline/status')
    return PipelineStatusSchema.parse(response.data) as ReturnType<typeof PipelineStatusSchema.parse>
  },

  /** GET /api/hubspot/webhook-log — paginated list of webhook logs */
  getWebhookLog: async (params?: {
    page?: number
    per_page?: number
    status?: string
    object_type?: string
  }): Promise<WebhookLogListResponse> => {
    const response = await api.get<WebhookLogListResponse>('/hubspot/webhook-log', { params })
    return response.data
  },

  /** GET /api/hubspot/webhook-log/summary — 24-hour summary */
  getWebhookLogSummary: async (): Promise<WebhookLogSummary> => {
    const response = await api.get<WebhookLogSummary>('/hubspot/webhook-log/summary')
    return response.data
  },

  /** POST /api/hubspot/webhook-log/{logId}/retry — retry a failed event */
  retryWebhookEvent: async (logId: number): Promise<{ success: boolean }> => {
    const response = await api.post<{ success: boolean }>(`/hubspot/webhook-log/${logId}/retry`)
    return response.data
  },

  /** POST /api/hubspot/config — extended to include optional client_secret */
  saveHubSpotConfigWithSecret: async (
    token: string,
    portalId?: string,
    clientSecret?: string
  ): Promise<HubSpotConfig> => {
    const response = await api.post<HubSpotConfig>('/hubspot/config', {
      token,
      portal_id: portalId,
      ...(clientSecret ? { client_secret: clientSecret } : {}),
    })
    return response.data
  },

  /** POST /api/hubspot/config — update only the client secret (no token required) */
  saveClientSecret: async (clientSecret: string): Promise<HubSpotConfig> => {
    const response = await api.post<HubSpotConfig>('/hubspot/config', {
      client_secret: clientSecret,
    })
    return response.data
  },
}

// ---------------------------------------------------------------------------
// Task 20.3 — Organization, Interaction, Task, and Timeline API methods
// ---------------------------------------------------------------------------

export const organizationService = {
  /** GET /api/organizations — paginated, filterable list */
  listOrganizations: async (filters?: {
    name?: string
    org_type?: string
    status?: string
    page?: number
    per_page?: number
  }): Promise<{ organizations: Organization[]; total: number; page: number; per_page: number }> => {
    const response = await api.get<{
      organizations: Organization[]
      total: number
      page: number
      per_page: number
    }>('/organizations', { params: filters })
    return response.data
  },

  /** POST /api/organizations — create a new organization */
  createOrganization: async (
    data: Omit<Organization, 'id' | 'created_at' | 'updated_at'>
  ): Promise<Organization> => {
    const response = await api.post<Organization>('/organizations', data)
    return response.data
  },

  /** GET /api/organizations/{id} — get a single organization */
  getOrganization: async (id: number): Promise<Organization> => {
    const response = await api.get<Organization>(`/organizations/${id}`)
    return response.data
  },

  /** PUT /api/organizations/{id} — update an organization */
  updateOrganization: async (
    id: number,
    data: Partial<Omit<Organization, 'id' | 'created_at' | 'updated_at'>>
  ): Promise<Organization> => {
    const response = await api.put<Organization>(`/organizations/${id}`, data)
    return response.data
  },

  /** DELETE /api/organizations/{id} — soft-delete (sets status=inactive) */
  deleteOrganization: async (id: number): Promise<void> => {
    await api.delete(`/organizations/${id}`)
  },

  /** GET /api/organizations/{id}/audit-log — get audit log entries */
  getOrganizationAuditLog: async (id: number): Promise<OrganizationAuditLog[]> => {
    const response = await api.get<{ audit_log: OrganizationAuditLog[]; total: number }>(`/organizations/${id}/audit-log`)
    return response.data.audit_log
  },

  /** POST /api/organizations/{orgId}/links/properties — link org to a property */
  linkOrganizationToProperty: async (
    orgId: number,
    propertyId: number,
    role: string
  ): Promise<PropertyOrganizationLink> => {
    const response = await api.post<PropertyOrganizationLink>(
      `/organizations/${orgId}/links/properties`,
      { property_id: propertyId, role }
    )
    return response.data
  },

  /** POST /api/organizations/{orgId}/links/owners — link org to an owner */
  linkOrganizationToOwner: async (
    orgId: number,
    ownerId: number,
    role: string
  ): Promise<OwnerOrganizationLink> => {
    const response = await api.post<OwnerOrganizationLink>(
      `/organizations/${orgId}/links/owners`,
      { owner_id: ownerId, role }
    )
    return response.data
  },
}

export const interactionService = {
  /** POST /api/interactions — create a new interaction */
  createInteraction: async (
    data: Omit<Interaction, 'id' | 'created_at' | 'updated_at' | 'is_orphaned'> & {
      associations: Array<{ target_type: string; target_id: number }>
    }
  ): Promise<Interaction> => {
    const response = await api.post<Interaction>('/interactions', data)
    return response.data
  },

  /** PUT /api/interactions/{id} — update an interaction */
  updateInteraction: async (
    id: number,
    data: Partial<Pick<Interaction, 'body' | 'occurred_at' | 'interaction_type'>>
  ): Promise<Interaction> => {
    const response = await api.put<Interaction>(`/interactions/${id}`, data)
    return response.data
  },

  /** DELETE /api/interactions/{id} — delete an interaction */
  deleteInteraction: async (id: number): Promise<void> => {
    await api.delete(`/interactions/${id}`)
  },
}

export const crmTaskService = {
  /** POST /api/tasks — create a new task */
  createTask: async (
    data: Omit<CRMTask, 'id' | 'created_at' | 'updated_at' | 'completion_timestamp'> & {
      associations: Array<{ target_type: string; target_id: number }>
    }
  ): Promise<CRMTask> => {
    const response = await api.post<CRMTask>('/tasks', data)
    return response.data
  },

  /** PUT /api/tasks/{id} — update a task */
  updateTask: async (
    id: number,
    data: Partial<Omit<CRMTask, 'id' | 'created_at' | 'updated_at'>>
  ): Promise<CRMTask> => {
    const response = await api.put<CRMTask>(`/tasks/${id}`, data)
    return response.data
  },

  /** DELETE /api/tasks/{id} — delete a task */
  deleteTask: async (id: number): Promise<void> => {
    await api.delete(`/tasks/${id}`)
  },

  /** POST /api/tasks/{id}/complete — mark a task as completed */
  completeTask: async (id: number): Promise<CRMTask> => {
    const response = await api.post<CRMTask>(`/tasks/${id}/complete`)
    return response.data
  },
}

// ---------------------------------------------------------------------------
// Contact API Service (Property-Contact Model)
// ---------------------------------------------------------------------------
import type {
  Contact,
  PropertyContact,
  ContactCreatePayload,
  ContactUpdatePayload,
  PropertyContactLinkRequest,
} from '@/types'

export const contactService = {
  /** POST /api/contacts/ — create a new contact */
  createContact: async (data: ContactCreatePayload): Promise<Contact> => {
    const response = await api.post<Contact>('/contacts/', data)
    return response.data
  },

  /** GET /api/contacts/{id} — get a contact with phones, emails, and linked properties */
  getContact: async (id: number): Promise<Contact> => {
    const response = await api.get<Contact>(`/contacts/${id}`)
    return response.data
  },

  /** PUT /api/contacts/{id} — update a contact */
  updateContact: async (id: number, data: ContactUpdatePayload): Promise<Contact> => {
    const response = await api.put<Contact>(`/contacts/${id}`, data)
    return response.data
  },

  /** DELETE /api/contacts/{id} — delete a contact (cascades to phones, emails, property links) */
  deleteContact: async (id: number): Promise<void> => {
    await api.delete(`/contacts/${id}`)
  },

  /** GET /api/properties/{propertyId}/contacts — list all contacts linked to a property */
  getPropertyContacts: async (propertyId: number): Promise<PropertyContact[]> => {
    const response = await api.get<PropertyContact[]>(`/properties/${propertyId}/contacts`)
    return response.data
  },

  /** POST /api/properties/{propertyId}/contacts — link a contact to a property */
  linkContactToProperty: async (
    propertyId: number,
    data: PropertyContactLinkRequest
  ): Promise<PropertyContact> => {
    const response = await api.post<PropertyContact>(`/properties/${propertyId}/contacts`, data)
    return response.data
  },

  /** DELETE /api/properties/{propertyId}/contacts/{contactId} — unlink a contact from a property */
  unlinkContactFromProperty: async (propertyId: number, contactId: number): Promise<void> => {
    await api.delete(`/properties/${propertyId}/contacts/${contactId}`)
  },
}

// ── Actionable Lead Command Center API Services ───────────────────────────
import type {
  QueueCounts,
  QueuePage,
  QueueNavigation,
  CommandCenterPayload,
  LeadTask,
  LeadTimelineEntry,
  LogCallPayload,
  LogNotePayload,
  BulkActionResult,
  LeadStatus,
  CRMRecommendedAction,
} from '@/types'

export const queueService = {
  getCounts: (): Promise<QueueCounts> =>
    api.get('/queues/counts').then(r => r.data),
  getTodaysAction: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/todays-action', { params: { page, per_page: perPage } }).then(r => r.data),
  getPreviouslyWarm: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/previously-warm', { params: { page, per_page: perPage } }).then(r => r.data),
  getFollowUpOverdue: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/follow-up-overdue', { params: { page, per_page: perPage } }).then(r => r.data),
  getNoNextAction: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/no-next-action', { params: { page, per_page: perPage } }).then(r => r.data),
  getNeedsReview: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/needs-review', { params: { page, per_page: perPage } }).then(r => r.data),
  getDoNotContact: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/do-not-contact', { params: { page, per_page: perPage } }).then(r => r.data),
  getMissingPropertyMatch: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/missing-property-match', { params: { page, per_page: perPage } }).then(r => r.data),
  getMailCandidates: (page = 1, perPage = 20): Promise<QueuePage> =>
    api.get('/queues/mail-candidates', { params: { page, per_page: perPage } }).then(r => r.data),
  getNavigation: (queueKey: string, leadId: number): Promise<QueueNavigation> =>
    api.get(`/queues/${queueKey}/navigation`, { params: { lead_id: leadId } }).then(r => r.data),
}

import type {
  ProspectAreaFilterConfig,
  ProspectAreaFilterStats,
  ProspectCandidatePage,
  ProspectApproveResult,
  ProspectFeedStatus,
} from '@/types'

export const prospectService = {
  getCount: (): Promise<{ prospect_candidates: number } & ProspectAreaFilterStats> =>
    api.get('/prospects/candidates/count').then(r => r.data),
  getStatus: (): Promise<ProspectFeedStatus> =>
    api.get('/prospects/status').then(r => r.data),
  getAreaFilter: (): Promise<ProspectAreaFilterConfig> =>
    api.get('/prospects/area-filter').then(r => r.data),
  saveAreaFilter: (payload: {
    enabled: boolean;
    geometry?: ProspectAreaFilterConfig['geometry'];
    label?: string | null;
    clear?: boolean;
  }): Promise<ProspectAreaFilterConfig> =>
    api.put('/prospects/area-filter', payload).then(r => r.data),
  getCandidates: (page = 1, perPage = 20, status = 'pending', minScore = 0): Promise<ProspectCandidatePage> =>
    api.get('/prospects/candidates', {
      params: { page, per_page: perPage, status, min_score: minScore },
    }).then(r => r.data),
  getCandidate: (id: number) =>
    api.get(`/prospects/candidates/${id}`).then(r => r.data),
  approveCandidate: (id: number): Promise<ProspectApproveResult> =>
    api.post(`/prospects/candidates/${id}/approve`).then(r => r.data),
  rejectCandidate: (id: number, reason = ''): Promise<unknown> =>
    api.post(`/prospects/candidates/${id}/reject`, { reason }).then(r => r.data),
  syncFeeds: (): Promise<{ summary: Record<string, unknown>; prospect_candidates: number; last_sync_at: string | null }> =>
    api.post('/prospects/sync').then(r => r.data),
}

export const commandCenterService = {
  getCommandCenter: (leadId: number): Promise<CommandCenterPayload> =>
    api.get(`/leads/${leadId}/command-center`).then(r => r.data),
  getRecommendedAction: (leadId: number): Promise<{ recommended_action: CRMRecommendedAction | null }> =>
    api.get(`/leads/${leadId}/recommended-action`).then(r => r.data),
  updateStatus: (leadId: number, status: LeadStatus, reason?: string): Promise<unknown> =>
    api.patch(`/leads/${leadId}/status`, { status, reason: reason || undefined }).then(r => r.data),
  doNotContact: (leadId: number): Promise<unknown> =>
    api.post(`/leads/${leadId}/do-not-contact`).then(r => r.data),
  park: (leadId: number, reactivationDate?: string): Promise<unknown> =>
    api.post(`/leads/${leadId}/park`, { reactivation_date: reactivationDate ?? null }).then(r => r.data),
  reactivate: (leadId: number): Promise<unknown> =>
    api.post(`/leads/${leadId}/reactivate`).then(r => r.data),
  suppress: (leadId: number): Promise<unknown> =>
    api.post(`/leads/${leadId}/suppress`).then(r => r.data),
  getTimeline: (leadId: number, page = 1): Promise<{ entries: LeadTimelineEntry[]; total: number; page: number; per_page: number }> =>
    api.get(`/leads/${leadId}/timeline`, { params: { page } }).then(r => r.data),
  syncHubSpot: (leadId: number): Promise<{
    lead_id: number;
    synced: boolean;
    lead_status?: string;
    hubspot_deal_stage?: string;
    last_hubspot_sync_at?: string | null;
    hubspot_sync_stale?: boolean;
  }> =>
    api.post(`/leads/${leadId}/hubspot-sync`).then(r => r.data),
}

export const leadTaskService = {
  createTask: (leadId: number, data: { title: string; task_type?: string; due_date?: string | null }): Promise<LeadTask> =>
    api.post(`/leads/${leadId}/tasks`, data).then(r => r.data),
  updateTask: (leadId: number, taskId: number, data: { title?: string; due_date?: string | null }): Promise<LeadTask> =>
    api.patch(`/leads/${leadId}/tasks/${taskId}`, data).then(r => r.data),
  completeTask: (leadId: number, taskId: number): Promise<LeadTask> =>
    api.post(`/leads/${leadId}/tasks/${taskId}/complete`).then(r => r.data),
  snoozeTask: (leadId: number, taskId: number, newDueDate: string): Promise<LeadTask> =>
    api.patch(`/leads/${leadId}/tasks/${taskId}`, { new_due_date: newDueDate }).then(r => r.data),
}

export const callLogService = {
  logCall: (leadId: number, payload: LogCallPayload): Promise<LeadTimelineEntry> =>
    api.post(`/leads/${leadId}/calls`, payload).then(r => r.data),
  logNote: (leadId: number, payload: LogNotePayload): Promise<LeadTimelineEntry> =>
    api.post(`/leads/${leadId}/notes`, payload).then(r => r.data),
  markHubSpotTaskDone: (leadId: number, taskId: number): Promise<{ task_id: number; status: string }> =>
    api.post(`/leads/${leadId}/hubspot-tasks/${taskId}/done`).then(r => r.data),
}

export const bulkActionService = {
  bulkSuppress: (leadIds: number[]): Promise<BulkActionResult> =>
    api.post('/leads/bulk/suppress', { lead_ids: leadIds }).then(r => r.data),
  bulkCreateTask: (leadIds: number[], taskData: { title: string; task_type?: string }): Promise<BulkActionResult> =>
    api.post('/leads/bulk/create-task', { lead_ids: leadIds, task_data: taskData }).then(r => r.data),
  bulkDoNotContact: (leadIds: number[]): Promise<BulkActionResult> =>
    api.post('/leads/bulk/do-not-contact', { lead_ids: leadIds }).then(r => r.data),
}

// ---------------------------------------------------------------------------
// Admin Panel API Service
// ---------------------------------------------------------------------------
import type {
  AdminUserSummary,
  AdminLeadParams,
  AdminLeadListResponse,
} from '@/types'

export const adminService = {
  /**
   * GET /api/admin/users — list all users (admin only)
   */
  listUsers: async (): Promise<AdminUserSummary[]> => {
    const response = await api.get<AdminUserSummary[]>('/admin/users')
    return response.data
  },

  /**
   * GET /api/admin/users/:userId/summary — get per-user activity summary (admin only)
   */
  getUserSummary: async (userId: string): Promise<AdminUserSummary> => {
    const response = await api.get<AdminUserSummary>(`/admin/users/${userId}/summary`)
    return response.data
  },

  /**
   * GET /api/admin/leads — paginated cross-user lead list (admin only)
   */
  listLeads: async (params: AdminLeadParams): Promise<AdminLeadListResponse> => {
    const response = await api.get<AdminLeadListResponse>('/admin/leads', { params })
    return response.data
  },

  /**
   * POST /api/admin/users/:userId/reset-password — reset a user's password (admin only)
   */
  resetPassword: async (userId: string, newPassword: string): Promise<void> => {
    await api.post(`/admin/users/${userId}/reset-password`, { new_password: newPassword })
  },

  /**
   * PATCH /api/admin/users/:userId — update a user's display_name or email (admin only)
   */
  updateUser: async (
    userId: string,
    data: { display_name?: string; email?: string },
  ): Promise<Omit<AdminUserSummary, 'lead_count' | 'marketing_list_count' | 'import_job_count'>> => {
    const response = await api.patch<
      Omit<AdminUserSummary, 'lead_count' | 'marketing_list_count' | 'import_job_count'>
    >(`/admin/users/${userId}`, data)
    return response.data
  },
}

// ---------------------------------------------------------------------------
// Pipeline Config API Service
// ---------------------------------------------------------------------------
import type { PipelineStage } from '@/types'

export const pipelineConfigService = {
  /** GET /api/pipeline-stages — fetch all configured pipeline stages ordered by order */
  getStages: async (): Promise<PipelineStage[]> => {
    const response = await api.get<PipelineStage[]>('/pipeline-stages')
    return response.data
  },

  /** PUT /api/pipeline-stages/weights — update stage weights (admin only) */
  updateWeights: async (stages: { stage_name: string; weight: number }[]): Promise<PipelineStage[]> => {
    const response = await api.put<PipelineStage[]>('/pipeline-stages/weights', stages)
    return response.data
  },
}

// ---------------------------------------------------------------------------
// Lead Kanban Service (reads from leads table)
// ---------------------------------------------------------------------------
import type { LeadKanbanResponse } from '@/types'

export const leadKanbanService = {
  /** GET /api/kanban/leads — fetch kanban columns with leads grouped by lead_status */
  getKanbanLeads: async (params?: {
    limit?: number
    column_id?: string
  }): Promise<LeadKanbanResponse> => {
    const response = await api.get<LeadKanbanResponse>('/kanban/leads', { params })
    return response.data
  },

  /** PATCH /api/kanban/leads/:id/move — move a lead to a different lead_status column */
  moveKanbanLead: async (leadId: number, targetAction: string): Promise<void> => {
    await api.patch(`/kanban/leads/${leadId}/move`, { target_action: targetAction })
  },
}

// ---------------------------------------------------------------------------
// Search Service
// ---------------------------------------------------------------------------

export const searchService = {
  search: async ({ q, page = 1, per_page = 25, signal }: SearchParams): Promise<SearchResponse> => {
    const response = await api.get<SearchResponse>('/search', {
      params: { q, page, per_page },
      signal,
    })
    return response.data
  },
}

// ---------------------------------------------------------------------------
// Data Sources Panel API Service
// ---------------------------------------------------------------------------
import type { DataSourceStatus } from '@/types'

export const dataSourcesService = {
  getStatus: async (): Promise<DataSourceStatus> => {
    const response = await api.get<DataSourceStatus>('/data-sources/status')
    return response.data
  },
}
