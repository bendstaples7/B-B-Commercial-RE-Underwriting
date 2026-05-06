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
} from '@/types'

// Create axios instance with default config
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 second timeout
})

// Request interceptor for adding auth tokens (future use)
api.interceptors.request.use(
  (config) => {
    // Add user_id to requests (temporary until OAuth is implemented)
    const userId = localStorage.getItem('user_id') || 'default_user'
    if (config.data) {
      config.data.user_id = userId
    }
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
      console.error('API Error:', errorData)
      
      // Handle specific error codes
      if (error.response.status === 429) {
        throw new Error('Rate limit exceeded. Please try again later.')
      }
      
      throw new Error(errorData?.message || 'An error occurred')
    } else if (error.request) {
      // Request made but no response received
      console.error('Network Error:', error.request)
      throw new Error('Network error. Please check your connection.')
    } else {
      // Something else happened
      console.error('Error:', error.message)
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
  startAnalysis: async (address: string): Promise<StartAnalysisResponse> => {
    const response = await api.post<any>('/analysis/start', {
      address,
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
    const response = await api.post<StepResult>(
      `/analysis/${sessionId}/step/${stepNumber}`,
      { approval_data: approvalData }
    )
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

export const multifamilyService = {
  // -------------------------------------------------------------------------
  // Deals (Req 1)
  // -------------------------------------------------------------------------

  /** List all deals owned by the current user (Req 1.5) */
  listDeals: async (): Promise<DealSummary[]> => {
    const response = await api.get<DealListResponse>('/multifamily/deals')
    return response.data.deals
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
