import api from '@/services/api'
import type { EntityResolutionResult, EntityResolutionStatus } from '@/types'

export type EntityResolutionAction =
  | 'resolve'
  | 'research_nonprofit'
  | 'mark_nonprofit'

/**
 * Illinois LLC entity resolution API (domain module — not appended to api.ts).
 */
export const entityResolutionApi = {
  async getStatus(leadId: number): Promise<EntityResolutionStatus> {
    const response = await api.get<EntityResolutionStatus>(
      `/leads/${leadId}/entity-resolution`,
    )
    return response.data
  },

  async resolve(
    leadId: number,
    options?: {
      dry_run?: boolean
      async?: boolean
      action?: EntityResolutionAction
    },
  ): Promise<EntityResolutionResult | { queued: boolean; lead_id: number; message: string }> {
    const response = await api.post(`/leads/${leadId}/entity-resolution`, options ?? {})
    return response.data
  },
}
