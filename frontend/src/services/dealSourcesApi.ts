/**
 * Deal / capture source catalog — Source dropdown builtins + custom values.
 */
import api from '@/services/api'

export interface DealSourceOption {
  name: string
  is_builtin: boolean
}

export interface CreateDealSourceResult extends DealSourceOption {
  created: boolean
}

export const dealSourcesApi = {
  async list(): Promise<DealSourceOption[]> {
    const response = await api.get<{ sources: DealSourceOption[] }>('/deal-sources')
    return response.data.sources ?? []
  },

  async create(name: string): Promise<CreateDealSourceResult> {
    const response = await api.post<CreateDealSourceResult>('/deal-sources', { name })
    return response.data
  },
}

export default dealSourcesApi
