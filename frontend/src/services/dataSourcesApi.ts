/**
 * Data Sources panel API service layer
 */
import api from '@/services/api'
import type { DataSourceStatus } from '@/types'

export const dataSourcesService = {
  getStatus: async (): Promise<DataSourceStatus> => {
    const response = await api.get<DataSourceStatus>('/data-sources/status')
    return response.data
  },
}
