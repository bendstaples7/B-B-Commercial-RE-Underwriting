import api from '@/services/httpClient'
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
