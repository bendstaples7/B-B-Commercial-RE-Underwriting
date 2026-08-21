import api from '@/services/httpClient'
import type { SearchParams, SearchResponse } from '@/types'

export const searchService = {
  search: async ({ q, page = 1, per_page = 25, signal }: SearchParams): Promise<SearchResponse> => {
    const response = await api.get<SearchResponse>('/search', {
      params: { q, page, per_page },
      signal,
    })
    return response.data
  },
}
