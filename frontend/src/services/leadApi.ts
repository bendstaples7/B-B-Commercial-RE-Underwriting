/**
 * Lead management API service layer
 */
import api from '@/services/api'
import type {
  LeadListFilters,
  LeadListResponse,
  LeadDetail,
  ScoringWeights,
  SheetInfo,
  FieldMapping,
  ImportJob,
  ImportJobListResponse,
  DataSource,
  EnrichmentRecord,
  MarketingList,
  MarketingListsResponse,
  MarketingListMembersResponse,
  OutreachStatus,
} from '@/types'

/**
 * Helper to read user_id from localStorage (used for GET query params).
 */
function getUserId(): string {
  return localStorage.getItem('user_id') || 'default_user'
}

export const leadService = {
  // ---------------------------------------------------------------------------
  // Lead Management
  // ---------------------------------------------------------------------------

  /**
   * List leads with optional filtering, sorting, and pagination.
   */
  async listLeads(filters?: LeadListFilters): Promise<LeadListResponse> {
    const response = await api.get<LeadListResponse>('/leads/', { params: filters })
    return response.data
  },

  /**
   * Get full lead detail including enrichment records, marketing lists, and analysis session.
   */
  async getLeadDetail(leadId: number): Promise<LeadDetail> {
    const response = await api.get<LeadDetail>(`/leads/${leadId}`)
    return response.data
  },

  /**
   * Start an analysis session from a lead record.
   */
  async analyzeLead(leadId: number): Promise<{ session_id: string; lead_id: number; [key: string]: any }> {
    const response = await api.post(`/leads/${leadId}/analyze`)
    return response.data
  },

  // ---------------------------------------------------------------------------
  // Scoring
  // ---------------------------------------------------------------------------

  /**
   * Get current scoring weights for a user.
   */
  async getScoringWeights(userId?: string): Promise<ScoringWeights> {
    const response = await api.get<ScoringWeights>('/leads/scoring/weights', {
      params: { user_id: userId || getUserId() },
    })
    return response.data
  },

  /**
   * Update scoring weights and trigger bulk rescore.
   */
  async updateScoringWeights(weights: {
    property_characteristics_weight: number
    data_completeness_weight: number
    owner_situation_weight: number
    location_desirability_weight: number
  }): Promise<ScoringWeights & { leads_rescored: number }> {
    const response = await api.put<ScoringWeights & { leads_rescored: number }>(
      '/leads/scoring/weights',
      weights,
    )
    return response.data
  },

  // ---------------------------------------------------------------------------
  // Import
  // ---------------------------------------------------------------------------

  /**
   * Authenticate with Google Sheets via OAuth2.
   * Phase 1: Returns auth_url when only client_id/secret provided.
   * Phase 2: Exchanges auth_code for tokens when auth_code provided.
   */
  async authenticateGoogleSheets(credentials: Record<string, any>): Promise<{ message: string; user_id: string; auth_url?: string; redirect_uri?: string }> {
    const response = await api.post<{ message: string; user_id: string; auth_url?: string; redirect_uri?: string }>(
      '/leads/import/auth',
      { credentials },
    )
    return response.data
  },

  /**
   * List available sheets from a Google Spreadsheet.
   */
  async listSheets(spreadsheetId: string, userId?: string): Promise<{ spreadsheet_id: string; sheets: SheetInfo[] }> {
    const response = await api.get<{ spreadsheet_id: string; sheets: SheetInfo[] }>(
      '/leads/import/sheets',
      { params: { spreadsheet_id: spreadsheetId, user_id: userId || getUserId() } },
    )
    return response.data
  },

  /**
   * Read headers from a selected sheet.
   */
  async readHeaders(
    spreadsheetId: string,
    sheetName: string,
    userId?: string,
  ): Promise<{ spreadsheet_id: string; sheet_name: string; headers: string[]; auto_mapping: Record<string, string> }> {
    const response = await api.get<{
      spreadsheet_id: string
      sheet_name: string
      headers: string[]
      auto_mapping: Record<string, string>
    }>('/leads/import/headers', {
      params: {
        spreadsheet_id: spreadsheetId,
        sheet_name: sheetName,
        user_id: userId || getUserId(),
      },
    })
    return response.data
  },

  /**
   * Save or update a field mapping for a spreadsheet/sheet combination.
   */
  async saveFieldMapping(data: {
    spreadsheet_id: string
    sheet_name: string
    mapping: Record<string, string>
  }): Promise<FieldMapping> {
    const response = await api.post<FieldMapping>('/leads/import/mapping', data)
    return response.data
  },

  /**
   * Start an import job.
   */
  async startImport(data: {
    spreadsheet_id: string
    sheet_name: string
    field_mapping_id?: number
    lead_category?: 'residential' | 'commercial'
  }): Promise<ImportJob> {
    const response = await api.post<ImportJob>('/leads/import/start', data)
    return response.data
  },

  /**
   * List import jobs with optional filtering.
   */
  async listImportJobs(params?: {
    user_id?: string
    status?: string
    page?: number
    per_page?: number
  }): Promise<ImportJobListResponse> {
    const response = await api.get<ImportJobListResponse>('/leads/import/jobs', { params })
    return response.data
  },

  /**
   * Get import job status and progress.
   */
  async getImportJob(jobId: number): Promise<ImportJob> {
    const response = await api.get<ImportJob>(`/leads/import/jobs/${jobId}`)
    return response.data
  },

  /**
   * Re-run a previous import using the same spreadsheet and field mapping.
   */
  async rerunImport(jobId: number): Promise<ImportJob & { original_job_id: number }> {
    const response = await api.post<ImportJob & { original_job_id: number }>(
      `/leads/import/jobs/${jobId}/rerun`,
    )
    return response.data
  },

  // ---------------------------------------------------------------------------
  // Enrichment
  // ---------------------------------------------------------------------------

  /**
   * List all registered data sources.
   */
  async listDataSources(): Promise<{ sources: DataSource[]; total: number }> {
    const response = await api.get<{ sources: DataSource[]; total: number }>(
      '/leads/enrichment/sources',
    )
    return response.data
  },

  /**
   * Enrich a single lead from a specified data source.
   */
  async enrichLead(leadId: number, sourceName: string): Promise<EnrichmentRecord> {
    const response = await api.post<EnrichmentRecord>(`/leads/${leadId}/enrich`, {
      source_name: sourceName,
    })
    return response.data
  },

  /**
   * Bulk enrich leads from a specified data source.
   */
  async bulkEnrich(
    leadIds: number[],
    sourceName: string,
  ): Promise<{ message: string; lead_count: number; source_name: string; async: boolean }> {
    const response = await api.post<{
      message: string
      lead_count: number
      source_name: string
      async: boolean
    }>('/leads/enrichment/bulk', {
      lead_ids: leadIds,
      source_name: sourceName,
    })
    return response.data
  },

  // ---------------------------------------------------------------------------
  // Marketing Lists
  // ---------------------------------------------------------------------------

  /**
   * List marketing lists with optional filtering.
   */
  async listMarketingLists(params?: {
    user_id?: string
    page?: number
    per_page?: number
  }): Promise<MarketingListsResponse> {
    const response = await api.get<MarketingListsResponse>('/leads/marketing/lists', { params })
    return response.data
  },

  /**
   * Create a new marketing list.
   */
  async createMarketingList(data: {
    name: string
    filter_criteria?: Record<string, any>
  }): Promise<MarketingList> {
    const response = await api.post<MarketingList>('/leads/marketing/lists', data)
    return response.data
  },

  /**
   * Rename an existing marketing list.
   */
  async renameMarketingList(listId: number, name: string): Promise<MarketingList> {
    const response = await api.put<MarketingList>(`/leads/marketing/lists/${listId}`, { name })
    return response.data
  },

  /**
   * Delete a marketing list.
   */
  async deleteMarketingList(listId: number): Promise<{ message: string; id: number }> {
    const response = await api.delete<{ message: string; id: number }>(
      `/leads/marketing/lists/${listId}`,
    )
    return response.data
  },

  /**
   * Get paginated members of a marketing list.
   */
  async getListMembers(
    listId: number,
    params?: { page?: number; per_page?: number },
  ): Promise<MarketingListMembersResponse> {
    const response = await api.get<MarketingListMembersResponse>(
      `/leads/marketing/lists/${listId}/members`,
      { params },
    )
    return response.data
  },

  /**
   * Add leads to a marketing list.
   */
  async addListMembers(
    listId: number,
    leadIds: number[],
  ): Promise<{ list_id: number; leads_added: number; leads_requested: number }> {
    const response = await api.post<{
      list_id: number
      leads_added: number
      leads_requested: number
    }>(`/leads/marketing/lists/${listId}/members`, { lead_ids: leadIds })
    return response.data
  },

  /**
   * Remove leads from a marketing list.
   */
  async removeListMembers(
    listId: number,
    leadIds: number[],
  ): Promise<{ list_id: number; leads_removed: number; leads_requested: number }> {
    const response = await api.delete<{
      list_id: number
      leads_removed: number
      leads_requested: number
    }>(`/leads/marketing/lists/${listId}/members`, {
      data: { lead_ids: leadIds },
    })
    return response.data
  },

  /**
   * Update the outreach status for a lead within a marketing list.
   */
  async updateOutreachStatus(
    listId: number,
    leadId: number,
    status: OutreachStatus,
  ): Promise<{
    list_id: number
    lead_id: number
    outreach_status: string
    status_updated_at: string | null
  }> {
    const response = await api.put<{
      list_id: number
      lead_id: number
      outreach_status: string
      status_updated_at: string | null
    }>(`/leads/marketing/lists/${listId}/members/${leadId}/status`, { status })
    return response.data
  },
}
