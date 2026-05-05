/**
 * Condo Filter API service layer
 */
import api from '@/services/api'
import type {
  CondoFilterParams,
  CondoFilterResultsResponse,
  AddressGroupDetail,
  CondoAnalysisSummary,
  CondoOverrideRequest,
} from '@/types'

export const condoFilterService = {
  /**
   * Trigger full condo filter analysis on all commercial/mixed-use leads.
   * Returns summary counts by status and building_sale_possible.
   */
  async runAnalysis(): Promise<CondoAnalysisSummary> {
    const response = await api.post<CondoAnalysisSummary>('/condo-filter/analyze')
    return response.data
  },

  /**
   * Get paginated, filtered analysis results.
   */
  async getResults(params?: CondoFilterParams): Promise<CondoFilterResultsResponse> {
    const response = await api.get<CondoFilterResultsResponse>('/condo-filter/results', {
      params,
    })
    return response.data
  },

  /**
   * Get full detail for a single address group including linked leads.
   */
  async getDetail(id: number): Promise<AddressGroupDetail> {
    const response = await api.get<AddressGroupDetail>(`/condo-filter/results/${id}`)
    return response.data
  },

  /**
   * Apply manual override to an address group and cascade to linked leads.
   */
  async applyOverride(id: number, data: CondoOverrideRequest): Promise<AddressGroupDetail> {
    const response = await api.put<AddressGroupDetail>(
      `/condo-filter/results/${id}/override`,
      data,
    )
    return response.data
  },

  /**
   * Export filtered analysis results as CSV. Returns a Blob for browser download.
   */
  async exportCsv(params?: CondoFilterParams): Promise<Blob> {
    const response = await api.get('/condo-filter/export/csv', {
      params,
      responseType: 'blob',
    })
    return response.data
  },
}
