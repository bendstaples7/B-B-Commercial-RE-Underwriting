/**
 * Property match review and building ownership API service layer
 */
import api from '@/services/api'

export const propertyMatchService = {
  preview: (leadId: number) =>
    api.get(`/leads/${leadId}/property-match/preview`).then(r => r.data),
  approve: (leadId: number) =>
    api.post(`/leads/${leadId}/property-match/approve`).then(r => r.data),
  reject: (leadId: number, action: string, note?: string) =>
    api.post(`/leads/${leadId}/property-match/reject`, { action, note }).then(r => r.data),
  updateAddress: (
    leadId: number,
    data: {
      property_street?: string
      property_city?: string
      property_state?: string
      property_zip?: string
    },
  ) => api.patch(`/leads/${leadId}/property-address`, data).then(r => r.data),
}

export const buildingOwnershipService = {
  get: (leadId: number) =>
    api.get(`/leads/${leadId}/building-ownership`).then(r => r.data),
  analyze: (leadId: number, options?: { force?: boolean }) =>
    api
      .post(`/leads/${leadId}/building-ownership/analyze`, { force: Boolean(options?.force) })
      .then(r => r.data),
  override: (
    leadId: number,
    data: { condo_risk_status: string; building_sale_possible: string; reason: string },
  ) => api.put(`/leads/${leadId}/building-ownership/override`, data).then(r => r.data),
  backfill: (options?: { enqueue_async?: boolean; per_run_cap?: number; last_id?: number }) =>
    api.post('/leads/building-ownership/backfill', options ?? {}).then(r => r.data),
}
